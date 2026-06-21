"""Redis client setup."""
from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings

redis_client = redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
    max_connections=50,
    socket_timeout=5,
    socket_connect_timeout=5,
    retry_on_timeout=True,
    health_check_interval=30,
)


async def get_redis() -> redis.Redis:
    """FastAPI dependency untuk Redis."""
    return redis_client
