from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.nearby import NearbyService
from tests.conftest import fresh

KONAK = (38.41872, 27.12827)


class FakeApi:
    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()

    async def parking(self):
        if "parking" in self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": "p1", "name": "Konak Otopark", "lat": 38.4190, "lon": 27.1290,
                 "free": 3, "occupied": 40, "capacity": 43, "status": "Opened",
                 "is_paid": False, "address": None, "opening_hours_today": "07:00 – 22:00"},
                {"id": "p2", "name": "Uzak Otopark", "lat": 38.50, "lon": 27.20,
                 "free": 1, "occupied": 1, "capacity": 2, "status": "Opened",
                 "is_paid": True, "address": None, "opening_hours_today": None},
            ],
            fresh(),
        )

    async def pharmacies(self):
        if "pharmacy" in self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": 9, "name": "Test Eczanesi", "lat": 38.4189, "lon": 27.1285,
                 "phone": "02320000000", "address": "Test Sok. No:1", "district": "KONAK",
                 "area_note": None, "duty_date": "2026-10-28T08:00:00"},
            ],
            fresh("2026-10-28T08:00:00"),
        )

    async def metro_stations(self):
        if "metro_station" in self.fail:
            raise RuntimeError("boom")
        return ([{"id": 2, "name": "Konak", "lat": 38.4175, "lon": 27.1283,
                  "active": True, "order": 11}], fresh())

    async def izban_stations(self):
        if "izban_station" in self.fail:
            raise RuntimeError("boom")
        return ([], fresh())

    async def ferry_piers(self):
        if "ferry_pier" in self.fail:
            raise RuntimeError("boom")
        return ([{"id": 1, "name": "Konak", "lat": 38.4186, "lon": 27.1258,
                  "active": True, "car_ferry": False}], fresh())


@pytest.mark.asyncio
async def test_nearby_sorts_by_distance_and_applies_radius():
    service = NearbyService(settings=get_settings(), api=FakeApi())
    envelope = await service.nearby(
        lat=KONAK[0], lon=KONAK[1], types=["parking", "pharmacy"],
        radius_m=1000, limit=10, reference_label="Konak",
    )
    assert envelope["ok"] is True
    names = [row["name"] for row in envelope["data"]]
    assert names[0] == "Test Eczanesi"
    assert "Uzak Otopark" not in names
    distances = [row["distance_m"] for row in envelope["data"]]
    assert distances == sorted(distances)
    assert all(row["maps_url"].startswith("https://www.google.com/maps?q=")
               for row in envelope["data"])


@pytest.mark.asyncio
async def test_nearby_returns_partial_results_when_one_source_fails():
    service = NearbyService(settings=get_settings(), api=FakeApi(fail={"parking"}))
    envelope = await service.nearby(
        lat=KONAK[0], lon=KONAK[1], types=["parking", "metro_station"],
        radius_m=2000, limit=10,
    )
    assert envelope["ok"] is True
    assert [row["kind"] for row in envelope["data"]] == ["metro_station"]
    assert any("parking" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_nearby_fails_only_when_every_source_fails():
    service = NearbyService(
        settings=get_settings(),
        api=FakeApi(fail={"parking", "pharmacy", "metro_station", "izban_station", "ferry_pier"}),
    )
    envelope = await service.nearby(
        lat=KONAK[0], lon=KONAK[1],
        types=["parking", "pharmacy", "metro_station", "izban_station", "ferry_pier"],
        radius_m=2000, limit=10,
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"


class FakeEshot:
    def __init__(self, fail: bool = False):
        self.fail = fail

    async def stops(self):
        if self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": "10030", "name": "Konak", "lat": 38.416218, "lon": 27.126321,
                 "routes": ["303", "304"]},
                {"id": "820001", "name": "Uzak Durak", "lat": 38.60, "lon": 27.40,
                 "routes": []},
            ],
            fresh(),
        )


@pytest.mark.asyncio
async def test_nearby_includes_bus_stops_near_konak():
    service = NearbyService(settings=get_settings(), api=FakeApi(), eshot=FakeEshot())
    envelope = await service.nearby(
        lat=KONAK[0], lon=KONAK[1], types=["bus_stop"], radius_m=1000, limit=5,
    )
    assert envelope["ok"] is True
    assert [row["id"] for row in envelope["data"]] == ["10030"]
    assert envelope["data"][0]["routes"] == ["303", "304"]
    assert any("izmir_bus_arrivals" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_nearby_bus_stop_failure_keeps_other_sources():
    service = NearbyService(
        settings=get_settings(), api=FakeApi(), eshot=FakeEshot(fail=True)
    )
    envelope = await service.nearby(
        lat=KONAK[0], lon=KONAK[1], types=["bus_stop", "metro_station"],
        radius_m=1000, limit=5,
    )
    assert envelope["ok"] is True
    assert {row["kind"] for row in envelope["data"]} == {"metro_station"}
    assert any("bus_stop" in warning for warning in envelope["warnings"])
