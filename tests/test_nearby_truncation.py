"""Truncation must have one owner across every nearby mode.

The audit reproduced ``izmir_nearby(types=["bus_stop"], radius_m=1000, limit=2)``
answering "2 sonuç bulundu" with ``matched=None`` while the store had already
returned every hit. bbox and district reported the total; radius silently cut.
These tests pin the shared contract: every mode and mobility report the same
``returned/matched/truncated`` triple, and a cold index fetches each layer once.
"""

from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.nearby import NearbyService
from tests.conftest import fresh
from tests.test_nearby import FakeApi


class CountingApi(FakeApi):
    """Counts loader calls so the cold path cannot fetch a layer twice."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def parking(self):
        self.calls += 1
        return await super().parking()


@pytest.mark.asyncio
async def test_radius_reports_matched_and_truncation():
    service = NearbyService(settings=get_settings(), api=FakeApi())

    envelope = await service.nearby(
        lat=38.41872,
        lon=27.12827,
        types=["parking", "pharmacy", "metro_station", "ferry_pier"],
        radius_m=1000,
        limit=2,
    )

    assert envelope["ok"] is True
    assert len(envelope["data"]) == 2
    assert envelope["result_info"]["scope"] == "radius"
    assert envelope["result_info"]["matched"] == 4
    assert envelope["result_info"]["truncated"] is True
    assert "İlk sonuçlar gösteriliyor." in envelope["summary"]


@pytest.mark.asyncio
async def test_radius_without_truncation_says_it_is_complete():
    service = NearbyService(settings=get_settings(), api=FakeApi())

    envelope = await service.nearby(lat=38.41872, lon=27.12827, types=["parking"], radius_m=1000, limit=10)

    assert envelope["result_info"]["matched"] == 1
    assert envelope["result_info"]["truncated"] is False
    assert "İlk sonuçlar gösteriliyor." not in envelope["summary"]


@pytest.mark.asyncio
async def test_cold_index_fetches_each_layer_once(tmp_path):
    api = CountingApi()
    settings = get_settings()
    scoped = type(settings)(**{**settings.__dict__, "database_path": str(tmp_path / "geo.sqlite3")})
    service = NearbyService(settings=scoped, api=api)

    await service.nearby(lat=38.41872, lon=27.12827, types=["parking"], radius_m=500, limit=10)

    assert api.calls == 1


class MobilityApi(FakeApi):
    async def taxi_stands(self):
        return ([], fresh())

    async def charging_points(self):
        return ([], fresh())


@pytest.mark.asyncio
async def test_mobility_reports_the_same_truncation_contract():
    service = NearbyService(
        settings=get_settings(),
        api=MobilityApi(),
        eshot=type(
            "Eshot",
            (),
            {
                "stops": lambda self: _bus_stop(),
            },
        )(),
    )

    envelope = await service.mobility(lat=38.41872, lon=27.12827, radius_m=1000, limit=2)

    assert envelope["result_info"]["scope"] == "mobility_nearby"
    assert envelope["result_info"]["matched"] > 2
    assert envelope["result_info"]["truncated"] is True
    assert "Toplam" in envelope["summary"]


async def _bus_stop():
    return (
        [
            {
                "id": "10030",
                "name": "Konak",
                "lat": 38.416218,
                "lon": 27.126321,
                "routes": ["303"],
            }
        ],
        fresh(),
    )
