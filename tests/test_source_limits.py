from __future__ import annotations

import pytest

from app.core.rate_limit import AsyncTokenBucket, SourceRateLimitExceeded
from app.core.settings import get_settings
from app.core.source_limits import SourceLimiters, reset_source_limiters, source_limiters


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _bucket(**overrides) -> tuple[AsyncTokenBucket, Clock]:
    clock = Clock()
    params = {
        "source": "test",
        "capacity": 2,
        "refill_per_second": 1.0,
        "max_wait_seconds": 0.5,
    }
    params.update(overrides)
    return AsyncTokenBucket(clock=clock, **params), clock


@pytest.mark.asyncio
async def test_bucket_allows_capacity_without_waiting():
    bucket, _clock = _bucket(capacity=3)
    for _ in range(3):
        await bucket.acquire()


@pytest.mark.asyncio
async def test_bucket_raises_when_the_wait_exceeds_the_budget():
    bucket, _clock = _bucket(capacity=1, refill_per_second=0.1, max_wait_seconds=0.2)
    await bucket.acquire()
    with pytest.raises(SourceRateLimitExceeded) as excinfo:
        await bucket.acquire()
    assert excinfo.value.source == "test"
    assert excinfo.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_bucket_waits_within_the_budget():
    bucket, clock = _bucket(capacity=1, refill_per_second=10.0, max_wait_seconds=1.0)
    await bucket.acquire()
    # The wait is ~0.1s at 10 tokens/s; with a fake clock the sleep still runs,
    # so keep the refill fast enough that the test stays quick.
    clock.advance(0.2)
    await bucket.acquire()


@pytest.mark.asyncio
async def test_refill_restores_tokens_over_time():
    bucket, clock = _bucket(capacity=1, refill_per_second=1.0, max_wait_seconds=2.0)
    await bucket.acquire()
    clock.advance(1.0)
    await bucket.acquire()


@pytest.mark.asyncio
async def test_penalize_blocks_the_source_for_everyone():
    bucket, clock = _bucket(capacity=5, max_wait_seconds=10.0)
    bucket.penalize(5.0)
    assert bucket.snapshot()["tokens"] == pytest.approx(5.0)
    clock.advance(6.0)
    await bucket.acquire()


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        AsyncTokenBucket(source="x", capacity=0, refill_per_second=1.0, max_wait_seconds=1.0)
    with pytest.raises(ValueError):
        AsyncTokenBucket(source="x", capacity=1, refill_per_second=0, max_wait_seconds=1.0)


def test_registry_returns_one_bucket_per_source():
    reset_source_limiters()
    limiters = source_limiters()
    assert limiters.bucket("iztek") is limiters.bucket("iztek")
    assert limiters.bucket("iztek") is not limiters.bucket("ckan")
    reset_source_limiters()


@pytest.mark.asyncio
async def test_registry_acquire_and_snapshot():
    reset_source_limiters()
    limiters = SourceLimiters(get_settings())
    await limiters.acquire("iztek")
    snapshot = limiters.snapshot()
    assert snapshot and snapshot[0]["source"] == "iztek"
    reset_source_limiters()
