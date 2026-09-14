"""
Focused regression tests for the bugs found and fixed during the
Base360/Flex debugging assessment:

1. Tenant-scoped revenue cache (cross-tenant privacy leak)
2. Paris month boundary (naive UTC vs property-local timezone)
3. Monthly revenue calculation (total + reservation count)
4. Async DB session handling (get_session() await bug)
5. Tenant/property pairing in the monthly query

These use lightweight in-memory fakes for Redis and the DB session so the
suite runs instantly with no live Postgres/Redis required, and unittest's
built-in IsolatedAsyncioTestCase so no extra test dependency is needed.

Run with:
    cd backend
    python -m unittest tests.test_bugfixes -v
"""
import unittest
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from app.services.cache import get_revenue_summary
from app.services.reservations import calculate_total_revenue, calculate_monthly_revenue

UTC = dt_timezone.utc


# ---------------------------------------------------------------------------
# Lightweight fakes (no live Redis / Postgres required)
# ---------------------------------------------------------------------------

class FakeRedis:
    """In-memory stand-in for the redis.asyncio client used by cache.py."""

    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value


class FakeRow:
    """Mimics a SQLAlchemy result row (attribute access per column)."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class RecordingSession:
    """Fake AsyncSession that returns canned rows in call order and
    records every (query, params) pair it was executed with, so tests can
    assert on exactly what was sent to the database."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params):
        self.calls.append((str(query), dict(params)))
        return FakeResult(self._rows.pop(0))


def make_fake_pool(rows, sessions_out=None):
    """Builds a stand-in class for app.core.database_pool.DatabasePool.
    Must be a zero-arg-constructible class, since reservations.py calls
    DatabasePool() directly."""

    class _FakeDatabasePool:
        def __init__(self):
            self.session_factory = None

        async def initialize(self):
            self.session_factory = True  # any truthy value

        async def get_session(self):
            session = RecordingSession(rows)
            if sessions_out is not None:
                sessions_out.append(session)
            return session

    return _FakeDatabasePool


# ---------------------------------------------------------------------------
# 1. Tenant cache isolation
# ---------------------------------------------------------------------------

class TestTenantCacheIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_same_property_id_different_tenants_never_share_cache(self):
        """Same property_id (prop-001 exists for both tenant-a and
        tenant-b) must resolve to different cache keys and never leak one
        tenant's revenue into the other's response."""
        fake_redis = FakeRedis()
        per_tenant_data = {
            "tenant-a": {"property_id": "prop-001", "tenant_id": "tenant-a",
                         "total": "1000.00", "currency": "USD", "count": 3},
            "tenant-b": {"property_id": "prop-001", "tenant_id": "tenant-b",
                         "total": "500.00", "currency": "USD", "count": 1},
        }

        async def fake_calculate_total_revenue(property_id, tenant_id):
            return per_tenant_data[tenant_id]

        with patch("app.services.cache.redis_client", fake_redis), \
             patch("app.services.reservations.calculate_total_revenue", fake_calculate_total_revenue):
            result_a = await get_revenue_summary("prop-001", "tenant-a")
            result_b = await get_revenue_summary("prop-001", "tenant-b")

        self.assertEqual(result_a["total"], "1000.00")
        self.assertEqual(result_b["total"], "500.00")
        self.assertNotEqual(result_a["total"], result_b["total"])

        # Two distinct keys must exist -- proves tenant scoping, not luck
        self.assertEqual(
            set(fake_redis.store.keys()),
            {"revenue:tenant-a:prop-001", "revenue:tenant-b:prop-001"},
        )


# ---------------------------------------------------------------------------
# 2. Paris month boundary
# ---------------------------------------------------------------------------

class TestParisMonthBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_feb_29_2330_utc_falls_inside_march_paris_local_time(self):
        """2024-02-29 23:30 UTC is 2024-03-01 00:30 in Europe/Paris, so it
        must be counted as March revenue, not February."""
        rows = [
            FakeRow(timezone="Europe/Paris"),          # property lookup
            FakeRow(total=Decimal("2250.000"), count=4),  # aggregate query
        ]
        sessions = []
        with patch("app.core.database_pool.DatabasePool", make_fake_pool(rows, sessions)):
            await calculate_monthly_revenue("prop-001", "tenant-a", 3, 2024)

        _, boundary_params = sessions[0].calls[1]  # the reservations query
        start = boundary_params["start_date"]
        end = boundary_params["end_date"]

        self.assertEqual(start, datetime(2024, 2, 29, 23, 0, tzinfo=UTC))
        self.assertEqual(end, datetime(2024, 3, 31, 22, 0, tzinfo=UTC))

        edge_case_checkin = datetime(2024, 2, 29, 23, 30, tzinfo=UTC)
        self.assertTrue(start <= edge_case_checkin < end)


# ---------------------------------------------------------------------------
# 3. Monthly revenue behaviour (total + count)
# ---------------------------------------------------------------------------

class TestMonthlyRevenueBehaviour(unittest.IsolatedAsyncioTestCase):
    async def test_march_2024_tenant_a_prop_001_totals_2250_count_4(self):
        rows = [
            FakeRow(timezone="Europe/Paris"),
            FakeRow(total=Decimal("2250.000"), count=4),
        ]
        with patch("app.core.database_pool.DatabasePool", make_fake_pool(rows)):
            total, count = await calculate_monthly_revenue("prop-001", "tenant-a", 3, 2024)

        self.assertEqual(total, Decimal("2250.000"))
        self.assertEqual(count, 4)


# ---------------------------------------------------------------------------
# 4. Database session handling (the get_session() await bug)
# ---------------------------------------------------------------------------

class TestDatabaseSessionHandling(unittest.IsolatedAsyncioTestCase):
    async def test_calculate_total_revenue_uses_real_session_not_mock_fallback(self):
        """calculate_total_revenue used to do
        `async with db_pool.get_session() as session:` where get_session()
        is async -- that raises AttributeError on a coroutine, which was
        silently swallowed and produced hardcoded mock data instead. If the
        session is awaited correctly, our fake DB row must come through
        untouched."""
        row = FakeRow(total_revenue=Decimal("1234.560"), reservation_count=7)
        with patch("app.core.database_pool.DatabasePool", make_fake_pool([row])):
            result = await calculate_total_revenue("prop-999", "tenant-a")

        # A broken session path would silently fall back to the hardcoded
        # mock_data dict (which doesn't even have an entry for prop-999,
        # i.e. total '0.00'), never reaching our fake row.
        self.assertEqual(result["total"], "1234.560")
        self.assertEqual(result["count"], 7)


# ---------------------------------------------------------------------------
# 5. Tenant-safe monthly calculation (property_id always paired with tenant_id)
# ---------------------------------------------------------------------------

class TestTenantSafeMonthlyCalculation(unittest.IsolatedAsyncioTestCase):
    async def test_every_query_pairs_property_id_with_tenant_id(self):
        rows = [
            FakeRow(timezone="Europe/Paris"),
            FakeRow(total=Decimal("2250.000"), count=4),
        ]
        sessions = []
        with patch("app.core.database_pool.DatabasePool", make_fake_pool(rows, sessions)):
            await calculate_monthly_revenue("prop-001", "tenant-a", 3, 2024)

        calls = sessions[0].calls
        self.assertEqual(len(calls), 2)  # timezone lookup + aggregate query
        for _, params in calls:
            self.assertEqual(params.get("property_id"), "prop-001")
            self.assertEqual(params.get("tenant_id"), "tenant-a")


if __name__ == "__main__":
    unittest.main()
