"""Bounded per-process tool metrics.

Records counts and latency per tool. Arguments and response text are never
stored: the point is to answer "which tool is slow or failing", not "what did
the caller search for". The buffer is bounded so a long-running server cannot
grow without limit.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

MAX_LATENCY_SAMPLES = 256


@dataclass
class ToolStats:
    calls: int = 0
    errors: int = 0
    truncated: int = 0
    stale: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    error_codes: Counter = field(default_factory=Counter)
    _latencies: deque = field(default_factory=lambda: deque(maxlen=MAX_LATENCY_SAMPLES))

    def observe(
        self,
        *,
        duration_ms: float,
        error_code: str | None,
        truncated: bool,
        stale: bool,
    ) -> None:
        self.calls += 1
        self.total_ms += duration_ms
        self.max_ms = max(self.max_ms, duration_ms)
        self._latencies.append(duration_ms)
        if error_code:
            self.errors += 1
            self.error_codes[error_code] += 1
        if truncated:
            self.truncated += 1
        if stale:
            self.stale += 1

    def percentile(self, fraction: float) -> float | None:
        if not self._latencies:
            return None
        ordered = sorted(self._latencies)
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return round(ordered[index], 1)

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "errors": self.errors,
            "error_codes": dict(self.error_codes),
            "truncated": self.truncated,
            "stale": self.stale,
            "mean_ms": round(self.total_ms / self.calls, 1) if self.calls else None,
            "p50_ms": self.percentile(0.50),
            "p95_ms": self.percentile(0.95),
            "max_ms": round(self.max_ms, 1) if self.calls else None,
        }


class ToolTelemetry:
    """Thread-safe counters; the MCP SDK may call handlers from worker threads."""

    def __init__(self, max_tools: int = 64):
        self.max_tools = max(1, int(max_tools))
        self._stats: dict[str, ToolStats] = {}
        self._lock = threading.Lock()

    def _stats_for(self, tool: str) -> ToolStats:
        stats = self._stats.get(tool)
        if stats is None:
            if len(self._stats) >= self.max_tools:
                # Evict the least-used tool rather than refusing to record.
                victim = min(self._stats, key=lambda key: self._stats[key].calls)
                self._stats.pop(victim, None)
            stats = ToolStats()
            self._stats[tool] = stats
        return stats

    def record(
        self,
        tool: str,
        *,
        duration_ms: float,
        error_code: str | None = None,
        truncated: bool = False,
        stale: bool = False,
    ) -> None:
        with self._lock:
            self._stats_for(tool).observe(
                duration_ms=duration_ms,
                error_code=error_code,
                truncated=truncated,
                stale=stale,
            )

    @contextmanager
    def timer(self, tool: str) -> Iterator[dict[str, Any]]:
        """Time a handler; the caller fills in the outcome fields.

        ``with telemetry.timer("izmir_health") as outcome: ...`` then set
        ``outcome["error_code"]`` / ``outcome["truncated"]`` / ``outcome["stale"]``
        before the block ends.
        """
        outcome: dict[str, Any] = {
            "error_code": None,
            "truncated": False,
            "stale": False,
        }
        started = time.perf_counter()
        try:
            yield outcome
        finally:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            self.record(
                tool,
                duration_ms=elapsed,
                error_code=outcome.get("error_code"),
                truncated=bool(outcome.get("truncated")),
                stale=bool(outcome.get("stale")),
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {tool: stats.snapshot() for tool, stats in sorted(self._stats.items())}

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()


_telemetry = ToolTelemetry()


def tool_telemetry() -> ToolTelemetry:
    return _telemetry


def reset_tool_telemetry() -> None:
    _telemetry.reset()
