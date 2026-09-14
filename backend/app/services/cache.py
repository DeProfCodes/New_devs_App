import json
import redis.asyncio as redis
from typing import Dict, Any, Optional
import os

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.

    When month/year are supplied, returns that property's revenue for that
    month (using the corrected timezone-aware calculation). Otherwise
    preserves the existing all-time total behaviour.
    """
    if month is not None and year is not None:
        cache_key = f"revenue:{tenant_id}:{property_id}:{year}-{month:02d}"
    else:
        cache_key = f"revenue:{tenant_id}:{property_id}"

    # Try to get from cache
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    if month is not None and year is not None:
        from app.services.reservations import calculate_monthly_revenue

        total, count = await calculate_monthly_revenue(property_id, tenant_id, month, year)
        result = {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "total": str(total),
            "currency": "USD",
            "count": count,
        }
    else:
        # Revenue calculation is delegated to the reservation service.
        from app.services.reservations import calculate_total_revenue

        result = await calculate_total_revenue(property_id, tenant_id)

    # Cache the result for 5 minutes
    await redis_client.setex(cache_key, 300, json.dumps(result))

    return result
