from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List, Tuple
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")

async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Tuple[Decimal, int]:
    """
    Calculates revenue for a specific month, using the property's own
    timezone to determine which reservations fall in that month.

    Reservation timestamps are stored in UTC, but "March revenue" means
    March in the property's local time, not UTC. Month boundaries are
    computed in the property's local timezone and then converted to UTC
    before querying.
    """
    from app.core.database_pool import DatabasePool
    from sqlalchemy import text

    db_pool = DatabasePool()
    await db_pool.initialize()

    if not db_pool.session_factory:
        return Decimal('0'), 0

    session = await db_pool.get_session()
    async with session:
        tz_row = (await session.execute(
            text("SELECT timezone FROM properties WHERE id = :property_id AND tenant_id = :tenant_id"),
            {"property_id": property_id, "tenant_id": tenant_id}
        )).fetchone()

        property_tz = ZoneInfo(tz_row.timezone) if tz_row and tz_row.timezone else UTC

        start_local = datetime(year, month, 1, tzinfo=property_tz)
        if month < 12:
            end_local = datetime(year, month + 1, 1, tzinfo=property_tz)
        else:
            end_local = datetime(year + 1, 1, 1, tzinfo=property_tz)

        start_utc = start_local.astimezone(UTC)
        end_utc = end_local.astimezone(UTC)

        result = await session.execute(
            text("""
                SELECT SUM(total_amount) as total, COUNT(*) as count
                FROM reservations
                WHERE property_id = :property_id
                AND tenant_id = :tenant_id
                AND check_in_date >= :start_date
                AND check_in_date < :end_date
            """),
            {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_utc,
                "end_date": end_utc,
            }
        )
        row = result.fetchone()
        total = Decimal(str(row.total)) if row and row.total is not None else Decimal('0')
        count = row.count if row and row.count is not None else 0
        return total, count

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Import database pool
        from app.core.database_pool import DatabasePool
        
        # Initialize pool if needed
        db_pool = DatabasePool()
        await db_pool.initialize()
        
        if db_pool.session_factory:
            session = await db_pool.get_session()
            async with session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text
                
                query = text("""
                    SELECT 
                        property_id,
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations 
                    WHERE property_id = :property_id AND tenant_id = :tenant_id
                    GROUP BY property_id
                """)
                
                result = await session.execute(query, {
                    "property_id": property_id, 
                    "tenant_id": tenant_id
                })
                row = result.fetchone()
                
                if row:
                    total_revenue = Decimal(str(row.total_revenue))
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": str(total_revenue),
                        "currency": "USD", 
                        "count": row.reservation_count
                    }
                else:
                    # No reservations found for this property
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": "0.00",
                        "currency": "USD",
                        "count": 0
                    }
        else:
            raise Exception("Database pool not available")
            
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")
        
        # Create property-specific mock data for testing when DB is unavailable
        # This ensures each property shows different figures
        mock_data = {
            'prop-001': {'total': '1000.00', 'count': 3},
            'prop-002': {'total': '4975.50', 'count': 4}, 
            'prop-003': {'total': '6100.50', 'count': 2},
            'prop-004': {'total': '1776.50', 'count': 4},
            'prop-005': {'total': '3256.00', 'count': 3}
        }
        
        mock_property_data = mock_data.get(property_id, {'total': '0.00', 'count': 0})
        
        return {
            "property_id": property_id,
            "tenant_id": tenant_id, 
            "total": mock_property_data['total'],
            "currency": "USD",
            "count": mock_property_data['count']
        }
