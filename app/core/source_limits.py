"""One token bucket per upstream source.

Every publisher that limits us needs its own budget: İZTEK answers 429 under a
burst while CKAN tolerates far more. Sharing one bucket would either throttle
CKAN needlessly or let İZTEK be hammered. Buckets are created lazily from
settings so adding a source only means adding a key here.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.rate_limit import AsyncTokenBucket
from app.core.settings import Settings, get_settings


@dataclass(frozen=True)
class SourceBudget:
    capacity: int
    refill_per_second: float
    max_wait_seconds: float


def _budget(settings: Settings, name: str) -> SourceBudget:
    """Read ``<name>_rate_*`` from settings, defaulting to the İZTEK profile."""
    return SourceBudget(
        capacity=getattr(settings, f"{name}_rate_capacity", 4),
        refill_per_second=getattr(settings, f"{name}_rate_refill_per_second", 2.0),
        max_wait_seconds=getattr(settings, f"{name}_rate_max_wait_seconds", 1.0),
    )


class SourceLimiters:
    """Lazily created, cached per-source buckets."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._buckets: dict[str, AsyncTokenBucket] = {}

    def bucket(self, source: str) -> AsyncTokenBucket:
        bucket = self._buckets.get(source)
        if bucket is None:
            budget = _budget(self._settings, source)
            bucket = AsyncTokenBucket(
                source=source,
                capacity=budget.capacity,
                refill_per_second=budget.refill_per_second,
                max_wait_seconds=budget.max_wait_seconds,
            )
            self._buckets[source] = bucket
        return bucket

    async def acquire(self, source: str) -> None:
        await self.bucket(source).acquire()

    def penalize(self, source: str, retry_after_seconds: float) -> None:
        self.bucket(source).penalize(retry_after_seconds)

    def snapshot(self) -> list[dict[str, object]]:
        return [bucket.snapshot() for bucket in self._buckets.values()]


_limiters: SourceLimiters | None = None


def source_limiters() -> SourceLimiters:
    """Process-wide limiter registry (one bucket per source per process)."""
    global _limiters
    if _limiters is None:
        _limiters = SourceLimiters()
    return _limiters


def reset_source_limiters() -> None:
    """Drop every bucket; used by tests and by settings reloads."""
    global _limiters
    _limiters = None
