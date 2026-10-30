from __future__ import annotations

from pathlib import Path

import pytest

from app.core.settings import get_settings
from app.services.nearby import NearbyService
from tests.conftest import fresh


class FakeApi:
    async def parking(self):
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
                },
                {
                    "id": "p2",
                    "name": "Uzak Otopark",
                    "lat": 38.5000,
                    "lon": 27.2000,
                    "free": 1,
                    "occupied": 1,
                    "capacity": 2,
                    "status": "Opened",
                    "is_paid": True,
                    "address": None,
                    "opening_hours_today": None,
                },
            ],
            fresh(),
        )

    async def pharmacies(self):
        return (
            [
                {
                    "id": "f1",
                    "name": "Eczane",
                    "lat": 38.4189,
                    "lon": 27.1285,
                    "phone": None,
                    "address": "Adres",
                    "district": "KONAK",
                    "area_note": None,
                    "duty_date": None,
                },
            ],
            fresh(),
        )

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


def _service(tmp_path: Path) -> NearbyService:
    settings = get_settings()
    scoped = type(settings)(**{**settings.__dict__, "database_path": str(tmp_path / "geo.sqlite3")})
    return NearbyService(settings=scoped, api=FakeApi(), eshot=FakeEshot(), taxis=FakeTaxis())


@pytest.mark.asyncio
async def test_radius_query_uses_the_spatial_store(tmp_path: Path):
    service = _service(tmp_path)
    envelope = await service.nearby(
        lat=38.41872,
        lon=27.12827,
        types=["parking", "pharmacy"],
        radius_m=300,
        limit=10,
    )
    assert envelope["ok"] is True
    assert {row["id"] for row in envelope["data"]} == {"p1", "f1"}
    assert any("mekânsal indeks" in item for item in envelope["limits"])


@pytest.mark.asyncio
async def test_second_query_reuses_the_index_without_refetching(tmp_path: Path):
    service = _service(tmp_path)
    await service.nearby(lat=38.41872, lon=27.12827, types=["parking"], radius_m=300, limit=10)

    class Exploding(FakeApi):
        async def parking(self):
            raise AssertionError("indexed layer must not be re-read on a warm index")

    service.api = Exploding()
    envelope = await service.nearby(
        lat=38.41872,
        lon=27.12827,
        types=["parking"],
        radius_m=300,
        limit=10,
    )
    assert envelope["ok"] is True
    assert {row["id"] for row in envelope["data"]} == {"p1"}


@pytest.mark.asyncio
async def test_bbox_query_uses_the_spatial_store(tmp_path: Path):
    service = _service(tmp_path)
    envelope = await service.bbox(
        bbox=[27.1200, 38.4100, 27.1300, 38.4200],
        types=["parking", "pharmacy"],
        limit=10,
    )
    assert envelope["ok"] is True
    assert {row["id"] for row in envelope["data"]} == {"p1", "f1"}
    assert all(row["distance_m"] is None for row in envelope["data"])


@pytest.mark.asyncio
async def test_decorated_fields_survive_the_index_roundtrip(tmp_path: Path):
    service = _service(tmp_path)
    envelope = await service.nearby(
        lat=38.41872,
        lon=27.12827,
        types=["parking"],
        radius_m=300,
        limit=10,
    )
    row = envelope["data"][0]
    assert row["free"] == 3
    assert row["capacity"] == 43
    assert row["maps_url"].startswith("https://www.google.com/maps?q=")


@pytest.mark.asyncio
async def test_full_layer_replaces_when_the_source_changes(tmp_path: Path):
    """A later fetch must be able to drop a row that disappeared upstream."""
    service = _service(tmp_path)
    await service.nearby(lat=38.41872, lon=27.12827, types=["parking"], radius_m=300, limit=10)

    class Shrunk(FakeApi):
        async def parking(self):
            rows, info = await FakeApi.parking(self)
            return rows[:1], info

    service.api = Shrunk()
    await service.index.refresh(["parking"], {"parking": service.api.parking})
    envelope = await service.nearby(
        lat=38.41872,
        lon=27.12827,
        types=["parking"],
        radius_m=5000,
        limit=10,
    )
    assert {row["id"] for row in envelope["data"]} == {"p1"}
