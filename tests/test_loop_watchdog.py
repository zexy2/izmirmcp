"""Event-loop watchdog: fires on a stalled loop, stays quiet on a healthy one."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from app.core.loop_watchdog import (
    EventLoopWatchdog,
    start_watchdog,
    validate_watchdog_settings,
)


@pytest.mark.parametrize("value", [0, 5, 60, 3600])
def test_valid_watchdog_settings(value):
    validate_watchdog_settings(SimpleNamespace(event_loop_watchdog_seconds=value))


@pytest.mark.parametrize("value", [1, 4.9, 3601, float("nan"), float("inf")])
def test_invalid_watchdog_settings(value):
    with pytest.raises(ValueError):
        validate_watchdog_settings(SimpleNamespace(event_loop_watchdog_seconds=value))


@pytest.mark.asyncio
async def test_disabled_by_default():
    assert start_watchdog(SimpleNamespace(event_loop_watchdog_seconds=0)) is None
    assert start_watchdog(SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_fires_when_the_loop_is_blocked():
    fired = threading.Event()
    watchdog = EventLoopWatchdog(asyncio.get_running_loop(), timeout_seconds=0.2,
                                 interval_seconds=0.05, on_stall=lambda _s: fired.set())
    watchdog.start()
    try:
        time.sleep(0.6)  # deliberately block the loop
        assert fired.wait(1.0)
    finally:
        watchdog.stop()


@pytest.mark.asyncio
async def test_quiet_while_the_loop_is_responsive():
    fired = threading.Event()
    watchdog = EventLoopWatchdog(asyncio.get_running_loop(), timeout_seconds=0.3,
                                 interval_seconds=0.05, on_stall=lambda _s: fired.set())
    watchdog.start()
    try:
        for _ in range(12):
            await asyncio.sleep(0.05)
        assert not fired.is_set()
    finally:
        watchdog.stop()
