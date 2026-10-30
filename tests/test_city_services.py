from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.city_services import CityServicesService
from tests.conftest import fresh


class FakeApi:
    async def wifi_points(self):
        return (
            [
                {
                    "id": "1",
                    "name": "ADNAN SAYGUN",
                    "district": "KONAK",
                    "neighborhood": "MEHMET ALİ AKMAN",
                    "lat": 38.4180,
                    "lon": 27.1280,
                },
                {
                    "id": "2",
                    "name": "UZAK NOKTА",
                    "district": "ÇEŞME",
                    "neighborhood": "MERKEZ",
                    "lat": 38.30,
                    "lon": 26.30,
                },
            ],
            fresh(),
        )

    async def izmirim_card_points(self):
        return (
            [
                {"id": "1", "address": "1639 Sok. No:8/D BAYRAKLI", "lat": 38.4185, "lon": 27.1285},
            ],
            fresh("2023-08-21T00:00:00"),
        )

    async def libraries(self):
        return (
            [
                {
                    "id": "1",
                    "name": "Kent Kütüphanesi",
                    "district": "Konak",
                    "address": "Alsancak Mah. Atatürk Cad. No: 454 Konak/İzmir",
                    "hours": "08.30-17.30",
                    "open_days": "Hafta içi",
                    "opened_year": 2008,
                },
            ],
            fresh(),
        )


@pytest.mark.asyncio
async def test_wifi_nearby_is_radius_limited_and_sorted():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).nearby(
        kinds=["wifi"], lat=38.41872, lon=27.12827, radius_m=3000, limit=10
    )
    assert envelope["ok"] is True
    assert [row["kind"] for row in envelope["data"]] == ["wifi"]
    assert envelope["data"][0]["distance_m"] < 300


@pytest.mark.asyncio
async def test_card_points_report_static_snapshot_age():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).nearby(
        kinds=["izmirim_card"], lat=38.41872, lon=27.12827, radius_m=5000, limit=10
    )
    assert envelope["ok"] is True
    assert envelope["data"][0]["kind"] == "izmirim_card"
    assert any("statik" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_libraries_have_no_coordinates_and_say_so():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).nearby(
        kinds=["library"], lat=38.41872, lon=27.12827, radius_m=5000, limit=10
    )
    assert envelope["ok"] is True
    row = envelope["data"][0]
    assert row["lat"] is None and row["lon"] is None
    assert row["distance_m"] is None
    assert any("koordinat" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected():
    with pytest.raises(InputValidationError) as excinfo:
        await CityServicesService(settings=get_settings(), api=FakeApi()).nearby(
            kinds=["swimming_pool"], lat=38.41872, lon=27.12827, radius_m=500, limit=5
        )
    assert excinfo.value.field == "kinds"


@pytest.mark.asyncio
async def test_partial_failure_keeps_other_layers_and_warns():
    class PartialApi(FakeApi):
        async def wifi_points(self):
            raise RuntimeError("boom")

    envelope = await CityServicesService(settings=get_settings(), api=PartialApi()).nearby(
        kinds=["wifi", "izmirim_card"], lat=38.41872, lon=27.12827, radius_m=5000, limit=10
    )
    assert envelope["ok"] is True
    assert {row["kind"] for row in envelope["data"]} == {"izmirim_card"}
    assert any("wifi" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_duplicate_published_points_are_collapsed():
    class DupApi(FakeApi):
        async def wifi_points(self):
            rows, info = await FakeApi.wifi_points(self)
            return [rows[0], dict(rows[0]), dict(rows[0])], info

    envelope = await CityServicesService(settings=get_settings(), api=DupApi()).nearby(
        kinds=["wifi"], lat=38.41872, lon=27.12827, radius_m=5000, limit=10
    )
    assert len(envelope["data"]) == 1
    assert envelope["result_info"]["matched"] == 1
    assert any("yinelenen" in warning.lower() for warning in envelope["warnings"])
