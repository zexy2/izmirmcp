"""Rate limiting for two different problems.

* ``ClientRateLimiter`` / ``ConcurrencyLimiter`` guard *our* HTTP endpoint
  against bursty or abusive callers. They live in process memory on purpose.
* ``AsyncTokenBucket`` guards *upstream* sources, where the limit is imposed by
  the publisher (İZTEK answers 429) and must be shared by every request.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Bucket:
    tokens: float
    updated_at: float
    last_seen_at: float


class SourceRateLimitExceeded(RuntimeError):
    """The caller asked to wait longer than the configured budget."""

    def __init__(self, *, source: str, retry_after_seconds: float):
        super().__init__(f"{source} rate limit exceeded")
        self.source = source
        self.retry_after_seconds = max(0.0, retry_after_seconds)


@dataclass
class AsyncTokenBucket:
    """Per-source token bucket shared by every request to that source.

    A single bucket per upstream is the point: without it, two concurrent tool
    calls can both pass a "should I wait" check and then hit the source at the
    same instant. The lock is what makes the check-and-consume atomic.
    """

    source: str
    capacity: int
    refill_per_second: float
    max_wait_seconds: float
    clock: object = field(default=time.monotonic)
    _tokens: float = None  # type: ignore[assignment]
    _updated_at: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _blocked_until: float = 0.0
    _waits: int = 0

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ValueError("capacity must be at least 1")
        if self.refill_per_second <= 0:
            raise ValueError("refill_per_second must be positive")
        if self.max_wait_seconds < 0:
            raise ValueError("max_wait_seconds must not be negative")
        self._tokens = float(self.capacity)
        self._updated_at = float(self.clock())  # type: ignore[operator]

    def _now(self) -> float:
        return float(self.clock())  # type: ignore[operator]

    def _refill_locked(self, now: float) -> None:
        elapsed = max(0.0, now - self._updated_at)
        self._tokens = min(
            float(self.capacity), self._tokens + elapsed * self.refill_per_second
        )
        self._updated_at = now

    def _retry_after_locked(self, now: float) -> float:
        """Seconds until a token is available, or 0 when one is ready now."""
        if self._blocked_until > now:
            return self._blocked_until - now
        return 0.0 if self._tokens >= 1.0 else (1.0 - self._tokens) / self.refill_per_second

    async def acquire(self) -> None:
        """Take one token, waiting at most ``max_wait_seconds``.

        Raises ``SourceRateLimitExceeded`` when the wait would exceed the
        budget, so a tool can answer with a typed ``source_rate_limited``
        error instead of hanging.
        """
        async with self._lock:
            now = self._now()
            self._refill_locked(now)
            wait = self._retry_after_locked(now)
            if wait > self.max_wait_seconds:
                raise SourceRateLimitExceeded(
                    source=self.source, retry_after_seconds=wait
                )
            if wait > 0:
                self._waits += 1
                await asyncio.sleep(wait)
                self._refill_locked(self._now())
            self._tokens = max(0.0, self._tokens - 1.0)

    def penalize(self, retry_after_seconds: float) -> None:
        """Block the bucket after an upstream 429 so callers back off together."""
        self._blocked_until = self._now() + max(0.0, retry_after_seconds)

    def snapshot(self) -> dict[str, float | str]:
        return {
            "source": self.source,
            "tokens": round(self._tokens, 3),
            "capacity": self.capacity,
            "refill_per_second": self.refill_per_second,
            "waits": self._waits,
        }


@dataclass
class ClientRateLimiter:
    capacity: int
    refill_per_second: float
    max_clients: int
    clock: Any = time.monotonic
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _allowed: int = 0
    _rejected: int = 0

    def __post_init__(self) -> None:
        self.capacity = max(1, int(self.capacity))
        self.refill_per_second = max(1e-6, float(self.refill_per_second))
        self.max_clients = max(1, int(self.max_clients))

    async def acquire(self, client_id: str) -> tuple[bool, float]:
        """Consume one token. Returns ``(allowed, retry_after_seconds)``."""
        now = float(self.clock())
        async with self._lock:
            bucket = self._buckets.get(client_id)
            if bucket is None:
                self._prune_locked(now)
                bucket = _Bucket(float(self.capacity), now, now)
                self._buckets[client_id] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(
                float(self.capacity), bucket.tokens + elapsed * self.refill_per_second
            )
            bucket.updated_at = now
            bucket.last_seen_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                self._allowed += 1
                return True, 0.0
            self._rejected += 1
            return False, (1.0 - bucket.tokens) / self.refill_per_second

    def snapshot(self) -> dict[str, Any]:
        return {
            "tracked_clients": len(self._buckets),
            "capacity": self.capacity,
            "refill_per_second": round(self.refill_per_second, 6),
            "max_clients": self.max_clients,
            "allowed": self._allowed,
            "rejected": self._rejected,
        }

    def _prune_locked(self, now: float) -> None:
        if len(self._buckets) < self.max_clients:
            return
        stale_before = now - max(60.0, self.capacity / self.refill_per_second)
        for client_id in [
            key for key, bucket in self._buckets.items() if bucket.last_seen_at < stale_before
        ]:
            self._buckets.pop(client_id, None)
        while len(self._buckets) >= self.max_clients:
            oldest = min(self._buckets, key=lambda key: self._buckets[key].last_seen_at)
            self._buckets.pop(oldest, None)


@dataclass
class ConcurrencyLimiter:
    max_concurrent: int
    _current: int = 0
    _rejected: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self.max_concurrent = max(1, int(self.max_concurrent))

    async def acquire(self) -> bool:
        async with self._lock:
            if self._current >= self.max_concurrent:
                self._rejected += 1
                return False
            self._current += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._current = max(0, self._current - 1)

    @property
    def current(self) -> int:
        return self._current

    def snapshot(self) -> dict[str, Any]:
        return {
            "current": self._current,
            "max_concurrent": self.max_concurrent,
            "rejected": self._rejected,
        }
