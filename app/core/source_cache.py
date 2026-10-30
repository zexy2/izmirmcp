"""Process-local TTL cache for upstream source payloads.

Bounded (``max_entries``, expired-first then oldest eviction), single-flight per
key, and stale-if-error: a recent copy is served, marked ``stale``, when the
source fails. ``snapshot()`` exposes hashed keys only, so /status never leaks
the request parameters that make up a cache key.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from app.core.envelope import utc_now_iso

DEFAULT_MAX_ENTRIES = 512


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
    ttl_seconds: float = 0.0
    stale_if_error_seconds: float = 0.0
    retrieved_at: str = ""


_entries: dict[str, _Entry] = {}
_locks: dict[str, asyncio.Lock] = {}


def clear_cache() -> None:
    _entries.clear()
    _locks.clear()


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _max_entries() -> int:
    try:
        from app.core.settings import get_settings

        value = getattr(get_settings(), "source_cache_max_entries", DEFAULT_MAX_ENTRIES)
        return max(1, int(value))
    except Exception:
        return DEFAULT_MAX_ENTRIES


def _now() -> float:
    return asyncio.get_running_loop().time()


def _evict_before_insert(key: str, *, now: float, max_entries: int) -> None:
    expired = [
        other for other, entry in _entries.items()
        if other != key and now - entry.stored_at >= entry.ttl_seconds + entry.stale_if_error_seconds
    ]
    for other in expired:
        _entries.pop(other, None)
        _locks.pop(other, None)
    while key not in _entries and len(_entries) >= max_entries:
        oldest = min(_entries, key=lambda other: _entries[other].stored_at)
        _entries.pop(oldest, None)
        _locks.pop(oldest, None)


async def cached_source_data(
    key: str,
    *,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[Any]],
    stale_if_error_seconds: int = 0,
    now: float | None = None,
    max_entries: int | None = None,
) -> tuple[Any, CacheInfo]:
    """Return cached data, falling back to a bounded stale copy on source errors.

    The loader may return either a bare value or ``(value, source_updated_at)``.
    """
    current = _now() if now is None else now
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
            if entry is None:
                # Never cache the lock of a key that has never loaded: a stream
                # of unique failing keys would otherwise grow _locks forever.
                _locks.pop(key, None)
            raise
        value, source_updated_at = result if isinstance(result, tuple) else (result, None)
        _evict_before_insert(
            key, now=current, max_entries=max_entries if max_entries is not None else _max_entries()
        )
        retrieved = utc_now_iso()
        _entries[key] = _Entry(
            value=value,
            stored_at=current,
            source_updated_at=source_updated_at,
            ttl_seconds=ttl_seconds,
            stale_if_error_seconds=stale_if_error_seconds,
            retrieved_at=retrieved,
        )
        return value, CacheInfo(
            status="fresh",
            retrieved_at=retrieved,
            source_updated_at=source_updated_at,
            age_seconds=0.0,
        )


def peek_with_status(
    key: str, *, stale_if_error_seconds: int | None = None, now: float | None = None
) -> tuple[Any, CacheInfo] | None:
    """Inspect an existing entry without refreshing it or calling upstream."""
    entry = _entries.get(key)
    if entry is None:
        return None
    current = _now() if now is None else now
    age = current - entry.stored_at
    grace = entry.stale_if_error_seconds if stale_if_error_seconds is None else stale_if_error_seconds
    if age >= entry.ttl_seconds + grace:
        return None
    return entry.value, CacheInfo(
        status="fresh" if age < entry.ttl_seconds else "stale",
        retrieved_at=utc_now_iso(),
        source_updated_at=entry.source_updated_at,
        age_seconds=round(age, 1),
    )


def _cache_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _source_label(key: str) -> str:
    parts = key.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else key


def snapshot(now: float | None = None) -> dict[str, Any]:
    """Cache health for /status: labels and hashed keys, never raw keys."""
    if now is None:
        try:
            now = _now()
        except RuntimeError:
            now = None
    rows = []
    for key, entry in sorted(_entries.items(), key=lambda item: _cache_key_hash(item[0])):
        row: dict[str, Any] = {
            "source": _source_label(key),
            "cache_key_hash": _cache_key_hash(key),
            "refreshed_at": entry.retrieved_at or None,
        }
        if now is not None:
            age = now - entry.stored_at
            row["age_seconds"] = round(max(0.0, age), 1)
            row["is_fresh"] = age < entry.ttl_seconds
        rows.append(row)
    return {"entries": len(rows), "max_entries": _max_entries(), "items": rows}
