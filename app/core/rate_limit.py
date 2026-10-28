"""Per-client request limiting and concurrency control for the HTTP surface.

State is in-process and intentionally volatile: the server is a read-only proxy,
so per-IP token buckets are a safety valve, not an accounting system. Multi-worker
deployments get per-worker budgets, which the README states plainly.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class _Bucket:
    tokens: float
    updated_at: float
    last_seen_at: float


@dataclass
class ClientRateLimiter:
    capacity: int
    refill_per_second: float
    max_clients: int
    clock: Callable[[], float] = time.monotonic
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
        now = self.clock()
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
