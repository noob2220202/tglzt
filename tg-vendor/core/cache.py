import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from core.config import settings

_redis: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized")
    return _redis


async def cache_get(key: str) -> Any | None:
    raw = await get_redis().get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


async def cache_set(key: str, value: Any, ttl_sec: int) -> None:
    serialized = json.dumps(value) if not isinstance(value, str) else value
    await get_redis().set(key, serialized, ex=ttl_sec)


async def cache_delete(key: str) -> None:
    await get_redis().delete(key)


@asynccontextmanager
async def acquire_lock(key: str, ttl_ms: int = 5000) -> AsyncIterator[bool]:
    """SET NX PX lock. Yields True if acquired, False otherwise."""
    r = get_redis()
    acquired = await r.set(key, "1", px=ttl_ms, nx=True)
    try:
        yield bool(acquired)
    finally:
        if acquired:
            await r.delete(key)
