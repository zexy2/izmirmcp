"""One owner for the spatial index's state.

The index lifecycle (warmth, age, rebuild policy, built_at stamping) used to be
split: ``NearbyService`` held ``refresh_index``/``_index_age_seconds`` while
``app.storage.geo`` held the SQLite. These tests exercise the storage-owned
``GeoIndex`` directly, including the failure modes the service must report.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.geo import GeoIndex, GeoStore
from tests.conftest import fresh


def parking(*rows):
    return ([dict(row) for row in rows], fresh())


def point(identifier: str, lat: float = 38.419, lon: float = 27.129) -> dict:
    return {"id": identifier, "name": identifier, "lat": lat, "lon": lon}


def test_a_missing_index_is_cold(tmp_path: Path):
    index = GeoIndex(GeoStore(tmp_path / "geo.sqlite3"))

    state = index.state()

    assert state.age_seconds == float("inf")
    assert state.covers(["parking"]) is False
    assert state.ready(["parking"], ttl_seconds=3600) is False


@pytest.mark.asyncio
async def test_cold_index_fetches_once_and_stamps_build_time(tmp_path: Path):
    index = GeoIndex(GeoStore(tmp_path / "geo.sqlite3"))
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return parking(point("p1"))

    outcome = await index.ensure(["parking"], {"parking": loader}, ttl_seconds=3600)

    assert outcome.warm is False
    assert outcome.refreshed == ["parking"]
    assert calls == 1
    assert index.state().covers(["parking"]) is True
    assert index.state().built_at is not None
    assert index.store.counts() == {"parking": 1}


@pytest.mark.asyncio
async def test_warm_fresh_index_does_not_touch_the_loader(tmp_path: Path):
    index = GeoIndex(GeoStore(tmp_path / "geo.sqlite3"))

    async def loader():
        return parking(point("p1"))

    await index.ensure(["parking"], {"parking": loader}, ttl_seconds=3600)

    async def exploding():
        raise AssertionError("a warm, fresh index must not re-read its source")

    outcome = await index.ensure(["parking"], {"parking": exploding}, ttl_seconds=3600)

    assert outcome.warm is True
    assert outcome.refreshed == []


@pytest.mark.asyncio
async def test_stale_index_is_rebuilt(tmp_path: Path):
    store = GeoStore(tmp_path / "geo.sqlite3")
    index = GeoIndex(store)

    async def first():
        return parking(point("p1"))

    await index.ensure(["parking"], {"parking": first}, ttl_seconds=3600)
    store.set_meta("built_at", "2020-01-01T00:00:00+00:00")
    calls = 0

    async def second():
        nonlocal calls
        calls += 1
        return parking(point("p1"), point("p2", 38.420, 27.130))

    outcome = await index.ensure(["parking"], {"parking": second}, ttl_seconds=3600)

    assert calls == 1
    assert outcome.warm is False
    assert outcome.refreshed == ["parking"]
    assert index.store.counts() == {"parking": 2}


@pytest.mark.asyncio
async def test_one_failing_layer_keeps_the_others(tmp_path: Path):
    index = GeoIndex(GeoStore(tmp_path / "geo.sqlite3"))

    async def parking_loader():
        return parking(point("p1"))

    async def pharmacy_loader():
        raise RuntimeError("boom")

    outcome = await index.ensure(
        ["parking", "pharmacy"],
        {"parking": parking_loader, "pharmacy": pharmacy_loader},
        ttl_seconds=0,
    )

    assert outcome.refreshed == ["parking"]
    assert outcome.failed == {"pharmacy": "RuntimeError"}
    assert outcome.answered == ["parking"]
    assert index.store.counts() == {"parking": 1}


@pytest.mark.asyncio
async def test_a_layer_without_coordinates_is_reported_not_wiped(tmp_path: Path):
    index = GeoIndex(GeoStore(tmp_path / "geo.sqlite3"))

    async def parking_loader():
        return parking(point("p1"))

    await index.ensure(["parking"], {"parking": parking_loader}, ttl_seconds=3600)
    index.store.set_meta("built_at", "2020-01-01T00:00:00+00:00")

    async def coordinate_less():
        return ([{"id": "x", "name": "no coords", "lat": None, "lon": None}], fresh())

    outcome = await index.ensure(
        ["parking", "pharmacy"],
        {"parking": parking_loader, "pharmacy": coordinate_less},
        ttl_seconds=60,
    )

    assert "pharmacy" in outcome.empty
    assert index.store.counts() == {"parking": 1}
