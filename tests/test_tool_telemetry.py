from __future__ import annotations

import pytest

from app.core.tool_telemetry import ToolTelemetry, reset_tool_telemetry, tool_telemetry


def test_records_counts_and_latency():
    telemetry = ToolTelemetry()
    telemetry.record("izmir_health", duration_ms=12.0)
    telemetry.record("izmir_health", duration_ms=8.0)
    stats = telemetry.snapshot()["izmir_health"]
    assert stats["calls"] == 2
    assert stats["errors"] == 0
    assert stats["mean_ms"] == 10.0
    assert stats["max_ms"] == 12.0


def test_records_error_codes():
    telemetry = ToolTelemetry()
    telemetry.record("izmir_nearby", duration_ms=1.0, error_code="validation_error")
    telemetry.record("izmir_nearby", duration_ms=1.0, error_code="source_unavailable")
    telemetry.record("izmir_nearby", duration_ms=1.0, error_code="source_unavailable")
    stats = telemetry.snapshot()["izmir_nearby"]
    assert stats["errors"] == 3
    assert stats["error_codes"] == {"source_unavailable": 2, "validation_error": 1}


def test_truncated_and_stale_are_counted_separately():
    telemetry = ToolTelemetry()
    telemetry.record("t", duration_ms=1.0, truncated=True)
    telemetry.record("t", duration_ms=1.0, stale=True)
    stats = telemetry.snapshot()["t"]
    assert stats["truncated"] == 1
    assert stats["stale"] == 1
    assert stats["errors"] == 0


def test_percentiles_are_bounded_and_ordered():
    telemetry = ToolTelemetry()
    for value in range(1, 101):
        telemetry.record("t", duration_ms=float(value))
    stats = telemetry.snapshot()["t"]
    assert stats["p50_ms"] <= stats["p95_ms"] <= stats["max_ms"]


def test_latency_samples_are_bounded():
    telemetry = ToolTelemetry()
    for _ in range(2000):
        telemetry.record("t", duration_ms=1.0)
    assert len(telemetry.snapshot()["t"]) >= 1
    assert telemetry.snapshot()["t"]["calls"] == 2000


def test_timer_context_records_an_outcome():
    telemetry = ToolTelemetry()
    with telemetry.timer("izmir_bus_stops") as outcome:
        outcome["error_code"] = "validation_error"
    stats = telemetry.snapshot()["izmir_bus_stops"]
    assert stats["calls"] == 1
    assert stats["error_codes"] == {"validation_error": 1}


def test_timer_records_even_when_the_block_raises():
    telemetry = ToolTelemetry()
    with pytest.raises(RuntimeError):
        with telemetry.timer("t"):
            raise RuntimeError("boom")
    assert telemetry.snapshot()["t"]["calls"] == 1


def test_tool_capacity_is_bounded():
    telemetry = ToolTelemetry(max_tools=2)
    for name in ("a", "b", "c"):
        telemetry.record(name, duration_ms=1.0)
    assert len(telemetry.snapshot()) == 2


def test_reset_clears_everything():
    telemetry = ToolTelemetry()
    telemetry.record("t", duration_ms=1.0)
    telemetry.reset()
    assert telemetry.snapshot() == {}


def test_module_singleton_is_shared():
    reset_tool_telemetry()
    tool_telemetry().record("t", duration_ms=1.0)
    assert "t" in tool_telemetry().snapshot()
    reset_tool_telemetry()
