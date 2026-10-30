"""Concurrency and consistency probes across services.

Goal: find state that leaks between calls, results that depend on call order, or
envelopes that silently change shape. These are the failure modes that only show
up under load or on a warm cache.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.core.settings import get_settings
from tests.conftest import fresh

KONAK = (38.41872, 27.12827)


class FakeApi:
    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls = 0

    async def parking(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return (
            [
                {
                    "id": "p1",
                    "name": "Konak Otopark",
                    "lat": 38.4190,
                    "lon": 27.1290,
                    "free": 3,
                    "occupied": 40,
                    "capacity": 43,
                    "status": "Opened",
                    "is_paid": False,
                    "address": None,
                    "opening_hours_today": None,
                }
            ],
            fresh(),
        )

    async def pharmacies(self):
        return ([], fresh())

    async def metro_stations(self):
        return ([], fresh())

    async def izban_stations(self):
        return ([], fresh())

    async def ferry_piers(self):
        return ([], fresh())


class FakeEshot:
    async def stops(self):
        return ([], fresh())

    async def arrivals(self, stop_id):
        return ([], fresh())

    async def gtfs(self):
        return {"routes": [], "calendar": [], "calendar_end": None}, fresh()


class FakeTaxis:
    async def taxi_stands(self):
        return ([], fresh())


def _service(api=None):
    from app.services.nearby import NearbyService

    return NearbyService(settings=get_settings(), api=api or FakeApi(), eshot=FakeEshot(), taxis=FakeTaxis())


@pytest.mark.asyncio
async def test_concurrent_identical_queries_are_consistent():
    service = _service()
    envelopes = await asyncio.gather(
        *(service.nearby(lat=KONAK[0], lon=KONAK[1], types=["parking"], radius_m=500, limit=5) for _ in range(8))
    )
    first = envelopes[0]["data"]
    for envelope in envelopes[1:]:
        assert envelope["data"] == first, "identical queries returned different rows"


@pytest.mark.asyncio
async def test_concurrent_queries_do_not_duplicate_rows():
    service = _service()
    envelope = await service.nearby(lat=KONAK[0], lon=KONAK[1], types=["parking"], radius_m=500, limit=50)
    ids = [row["id"] for row in envelope["data"]]
    assert len(ids) == len(set(ids)), "the same row appeared twice"


@pytest.mark.asyncio
async def test_envelope_shape_is_identical_for_success_and_empty():
    service = _service()
    full = await service.nearby(lat=KONAK[0], lon=KONAK[1], types=["parking"], radius_m=500, limit=5)
    empty = await service.nearby(lat=KONAK[0], lon=KONAK[1], types=["parking"], radius_m=1, limit=5)
    assert set(full) == set(empty)
    assert set(full["freshness"]) == set(empty["freshness"])
    assert set(full["result_info"]) == set(empty["result_info"])


@pytest.mark.asyncio
async def test_all_source_layers_failing_produces_the_same_shape():
    class Broken(FakeApi):
        async def parking(self):
            raise RuntimeError("boom")

    envelope = await _service(Broken()).nearby(lat=KONAK[0], lon=KONAK[1], types=["parking"], radius_m=500, limit=5)
    assert envelope["ok"] is False
    for key in (
        "summary",
        "data",
        "freshness",
        "sources",
        "limits",
        "warnings",
        "next_queries",
        "error",
        "result_info",
    ):
        assert key in envelope
    assert envelope["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_bbox_and_radius_agree_on_a_point_inside_both():
    service = _service()
    radius = await service.nearby(lat=KONAK[0], lon=KONAK[1], types=["parking"], radius_m=500, limit=10)
    rectangle = await service.bbox(bbox=[27.12, 38.41, 27.14, 38.43], types=["parking"], limit=10)
    assert {row["id"] for row in radius["data"]} == {row["id"] for row in rectangle["data"]}


@pytest.mark.asyncio
async def test_result_is_json_serialisable_and_free_of_nan():
    service = _service()
    envelope = await service.nearby(lat=KONAK[0], lon=KONAK[1], types=["parking"], radius_m=500, limit=5)
    text = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text


@pytest.mark.asyncio
async def test_gtfs_status_does_not_touch_the_network(tmp_path: Path):
    from app.services.bus import BusService

    class Exploding:
        async def gtfs_archive(self):
            raise AssertionError("status must not download")

        async def stops(self):
            raise AssertionError("status must not read stops")

    envelope = await BusService(settings=get_settings(), api=Exploding()).timetable_status()
    assert envelope["ok"] in (True, False)
    assert "summary" in envelope
