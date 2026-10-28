from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from app.core.envelope import utc_now_iso


@dataclass
class CacheInfo:
    status: Literal["fresh", "stale"]
    retrieved_at: str
    source_updated_at: str | None = None
    age_seconds: float = 0.0


@dataclass
class _Entry:
    value: Any
    stored_at: float
    source_updated_at: str | None


_entries: dict[str, _Entry] = {}
_locks: dict[str, asyncio.Lock] = {}


def clear_cache() -> None:
    _entries.clear()


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def cached_source_data(
    key: str,
    *,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[Any]],
    stale_if_error_seconds: int = 0,
    now: float | None = None,
) -> tuple[Any, CacheInfo]:
    """Return cached data, falling back to a bounded stale copy on source errors.

    The loader may return either a bare value or ``(value, source_updated_at)``.
    """
    current = asyncio.get_running_loop().time() if now is None else now
    async with _lock_for(key):
        entry = _entries.get(key)
        age = current - entry.stored_at if entry is not None else None
        if entry is not None and age is not None and age < ttl_seconds:
            return entry.value, CacheInfo(
                status="fresh",
                retrieved_at=utc_now_iso(),
                source_updated_at=entry.source_updated_at,
                age_seconds=round(age, 1),
            )
        try:
            result = await loader()
        except Exception:
            if (
                entry is not None
                and age is not None
                and age <= ttl_seconds + stale_if_error_seconds
            ):
                return entry.value, CacheInfo(
                    status="stale",
                    retrieved_at=utc_now_iso(),
                    source_updated_at=entry.source_updated_at,
                    age_seconds=round(age, 1),
                )
            raise
        value, source_updated_at = result if isinstance(result, tuple) else (result, None)
        _entries[key] = _Entry(value=value, stored_at=current, source_updated_at=source_updated_at)
        return value, CacheInfo(
            status="fresh",
            retrieved_at=utc_now_iso(),
            source_updated_at=source_updated_at,
            age_seconds=0.0,
        )
