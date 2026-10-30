from __future__ import annotations

import httpx
import pytest

from app.core.rate_limit import ClientRateLimiter, ConcurrencyLimiter


@pytest.mark.asyncio
async def test_client_rate_limiter_allows_up_to_capacity_then_blocks():
    limiter = ClientRateLimiter(capacity=3, refill_per_second=0.001, max_clients=10)
    allowed = [await limiter.acquire("1.2.3.4") for _ in range(3)]
    assert all(ok for ok, _retry in allowed)
    blocked, retry_after = await limiter.acquire("1.2.3.4")
    assert blocked is False
    assert retry_after > 0


@pytest.mark.asyncio
async def test_client_rate_limiter_isolates_clients():
    limiter = ClientRateLimiter(capacity=1, refill_per_second=0.001, max_clients=10)
    assert (await limiter.acquire("a"))[0] is True
    assert (await limiter.acquire("a"))[0] is False
    assert (await limiter.acquire("b"))[0] is True


@pytest.mark.asyncio
async def test_client_rate_limiter_refills_over_time():
    now = [100.0]
    limiter = ClientRateLimiter(capacity=1, refill_per_second=1.0, max_clients=10, clock=lambda: now[0])
    assert (await limiter.acquire("a"))[0] is True
    assert (await limiter.acquire("a"))[0] is False
    now[0] += 1.0
    assert (await limiter.acquire("a"))[0] is True


@pytest.mark.asyncio
async def test_client_rate_limiter_bounds_tracked_clients():
    limiter = ClientRateLimiter(capacity=1, refill_per_second=0.001, max_clients=4)
    for index in range(50):
        await limiter.acquire(f"client-{index}")
    assert limiter.snapshot()["tracked_clients"] <= 4


@pytest.mark.asyncio
async def test_concurrency_limiter_rejects_over_the_limit():
    limiter = ConcurrencyLimiter(max_concurrent=2)
    assert await limiter.acquire() is True
    assert await limiter.acquire() is True
    assert await limiter.acquire() is False
    await limiter.release()
    assert await limiter.acquire() is True
