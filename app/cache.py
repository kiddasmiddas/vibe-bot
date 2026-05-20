from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis, from_url

from app.config import settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """Singleton async Redis client. Используется как кэш и как FSM storage."""
    return from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
