"""In-memory TTL cache (per-process). No Redis required."""
import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

_store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)


def cache_get(key: str) -> Any | None:
    entry = _store.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        _store.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, ttl_sec: int) -> None:
    _store[key] = (value, time.monotonic() + ttl_sec)


def cache_delete(key: str) -> None:
    _store.pop(key, None)


# Per-user asyncio locks for purchase dedup (bot process only)
_user_locks: dict[int, asyncio.Lock] = {}


def _get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


@asynccontextmanager
async def acquire_user_lock(user_id: int) -> AsyncIterator[bool]:
    """Yields True if lock acquired immediately, False if already held."""
    lock = _get_lock(user_id)
    if lock.locked():
        yield False
        return
    async with lock:
        yield True
