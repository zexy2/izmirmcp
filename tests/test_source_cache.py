"""Bounded stale-if-error source cache."""
from __future__ import annotations

import pytest

from app.core import source_cache as cache


async def _load(value):
    return value


async def _fail():
    raise RuntimeError("source down")


@pytest.mark.asyncio
async def test_serves_stale_copy_inside_the_grace_window():
    await cache.cached_source_data("a.b", ttl_seconds=10, loader=lambda: _load(1),
                                   stale_if_error_seconds=30, now=0)
    value, info = await cache.cached_source_data("a.b", ttl_seconds=10, loader=_fail,
                                                 stale_if_error_seconds=30, now=20)
    assert value == 1 and info.status == "stale"
    with pytest.raises(RuntimeError):
        await cache.cached_source_data("a.b", ttl_seconds=10, loader=_fail,
                                       stale_if_error_seconds=30, now=41)


@pytest.mark.asyncio
async def test_fresh_hit_does_not_call_the_loader():
    await cache.cached_source_data("a.b", ttl_seconds=10, loader=lambda: _load(1), now=0)
    value, info = await cache.cached_source_data("a.b", ttl_seconds=10, loader=_fail, now=5)
    assert value == 1 and info.status == "fresh"


@pytest.mark.asyncio
async def test_max_entries_evicts_the_oldest():
    for index in range(4):
        await cache.cached_source_data(f"k.{index}", ttl_seconds=100,
                                       loader=lambda i=index: _load(i), now=index, max_entries=3)
    assert cache.peek_with_status("k.0", now=4) is None
    assert {key for key in cache._entries} == {"k.1", "k.2", "k.3"}


@pytest.mark.asyncio
async def test_expired_entries_are_evicted_first():
    await cache.cached_source_data("old.x", ttl_seconds=1, loader=lambda: _load(0), now=0)
    await cache.cached_source_data("keep.x", ttl_seconds=100, loader=lambda: _load(1), now=1)
    await cache.cached_source_data("new.x", ttl_seconds=100, loader=lambda: _load(2),
                                   now=50, max_entries=2)
    assert set(cache._entries) == {"keep.x", "new.x"}


@pytest.mark.asyncio
async def test_failed_first_load_does_not_leak_a_lock():
    for index in range(20):
        with pytest.raises(RuntimeError):
            await cache.cached_source_data(f"bad.{index}", ttl_seconds=10, loader=_fail, now=0)
    assert not any(key.startswith("bad.") for key in cache._locks)


@pytest.mark.asyncio
async def test_peek_reports_fresh_stale_and_expired_without_loading():
    await cache.cached_source_data("p.q", ttl_seconds=10, loader=lambda: _load("v"),
                                   stale_if_error_seconds=10, now=0)
    assert cache.peek_with_status("p.q", now=5)[1].status == "fresh"
    assert cache.peek_with_status("p.q", now=15)[1].status == "stale"
    assert cache.peek_with_status("p.q", now=25) is None
    assert cache.peek_with_status("missing", now=0) is None


@pytest.mark.asyncio
async def test_snapshot_hashes_keys_and_never_leaks_parameters():
    secret_key = "iztek.arrivals.secret-stop-4711"
    await cache.cached_source_data(secret_key, ttl_seconds=10, loader=lambda: _load([]))
    snap = cache.snapshot()
    assert snap["entries"] == 1
    item = snap["items"][0]
    assert item["source"] == "iztek.arrivals"
    assert len(item["cache_key_hash"]) == 16 and item["is_fresh"] is True
    assert "4711" not in repr(snap)


def test_status_route_exposes_the_cache_snapshot():
    from starlette.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert set(body["source_cache"]) == {"entries", "max_entries", "items"}
