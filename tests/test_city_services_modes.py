from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.city_services import CityServicesService
from tests.conftest import fresh

KONAK_BBOX = [27.1200, 38.4100, 27.1400, 38.4300]


class FakeApi:
    def __init__(self, *, fail: set[str] | None = None):
        self.fail = fail or set()

    async def wifi_points(self):
        if "wifi" in self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": "in", "name": "İç Nokta", "district": "KONAK",
                 "neighborhood": "MEHMET ALİ AKMAN", "lat": 38.4190, "lon": 27.1290},
                {"id": "edge", "name": "Kenar Nokta", "district": "KONAK",
                 "neighborhood": "HİSARÖNÜ", "lat": 38.4100, "lon": 27.1200},
                {"id": "out", "name": "Dış Nokta", "district": "ÇEŞME",
                 "neighborhood": "MERKEZ", "lat": 38.5000, "lon": 27.2000},
            ],
            fresh(),
        )

    async def izmirim_card_points(self):
        if "izmirim_card" in self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": "c1", "address": "1639 Sok. No:8/D KONAK",
                 "lat": 38.4195, "lon": 27.1295},
                {"id": "c2", "address": "UZAK BAYRAKLI",
                 "lat": 38.5000, "lon": 27.2000},
            ],
            fresh("2023-08-21T00:00:00"),
        )

    async def libraries(self):
        if "library" in self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": "l1", "name": "Kent Kütüphanesi", "district": "Konak",
                 "address": "Alsancak Mah. Atatürk Cad. No: 454 Konak/İzmir",
                 "hours": "08.30-17.30", "open_days": "Hafta içi", "opened_year": 2008,
                 "lat": None, "lon": None},
                {"id": "l2", "name": "Buca Kütüphanesi", "district": "Buca",
                 "address": "Ufuk Mah. 916 Sk. No: 3 Buca/İzmir",
                 "hours": "08.30-17.30", "open_days": "Hafta içi", "opened_year": 2020,
                 "lat": None, "lon": None},
            ],
            fresh(),
        )


@pytest.mark.asyncio
async def test_bbox_includes_edges_and_drops_outside_points():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).bbox(
        bbox=KONAK_BBOX, kinds=["wifi", "izmirim_card"], limit=10
    )
    assert envelope["ok"] is True
    assert {row["id"] for row in envelope["data"]} == {"in", "edge", "c1"}
    assert all(row["distance_m"] is None for row in envelope["data"])


@pytest.mark.asyncio
async def test_bbox_reports_truncation_with_result_info():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).bbox(
        bbox=KONAK_BBOX, kinds=["wifi", "izmirim_card"], limit=1
    )
    assert envelope["result_info"]["matched"] == 3
    assert envelope["result_info"]["truncated"] is True
    assert len(envelope["data"]) == 1


@pytest.mark.asyncio
async def test_bbox_empty_rectangle_is_not_an_all_clear():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).bbox(
        bbox=[27.0, 38.0, 27.001, 38.001], kinds=["wifi"], limit=10
    )
    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert any("kanıtı değildir" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_bbox_rejects_crossed_and_degenerate_rectangle():
    service = CityServicesService(settings=get_settings(), api=FakeApi())
    with pytest.raises(InputValidationError) as excinfo:
        await service.bbox(bbox=[27.14, 38.41, 27.12, 38.43], kinds=["wifi"], limit=5)
    assert excinfo.value.field == "bbox"
    with pytest.raises(InputValidationError):
        await service.bbox(bbox=[27.12, 38.41, 27.12, 38.43], kinds=["wifi"], limit=5)


@pytest.mark.asyncio
async def test_bbox_warns_that_libraries_have_no_coordinates():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).bbox(
        bbox=KONAK_BBOX, kinds=["library"], limit=10
    )
    assert envelope["data"] == []
    assert any("koordinat" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_bbox_keeps_partial_results_when_one_layer_fails():
    envelope = await CityServicesService(
        settings=get_settings(), api=FakeApi(fail={"wifi"})
    ).bbox(bbox=KONAK_BBOX, kinds=["wifi", "izmirim_card"], limit=10)
    assert envelope["ok"] is True
    assert {row["kind"] for row in envelope["data"]} == {"izmirim_card"}
    assert any("wifi" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_district_lists_all_libraries_without_distance():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).district(
        district="Konak", kinds=["library"], limit=10
    )
    assert envelope["ok"] is True
    assert [row["name"] for row in envelope["data"]] == ["Kent Kütüphanesi"]
    assert envelope["data"][0]["distance_m"] is None
    assert envelope["data"][0]["district_match"] == "published_district_field"


@pytest.mark.asyncio
async def test_district_matches_wifi_and_card_by_address_text():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).district(
        district="Konak", kinds=["wifi", "izmirim_card"], limit=10
    )
    assert {row["id"] for row in envelope["data"]} == {"in", "edge", "c1"}


@pytest.mark.asyncio
async def test_district_with_no_match_is_not_an_all_clear():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).district(
        district="Çeşme", kinds=["library"], limit=10
    )
    assert envelope["data"] == []
    assert any("kanıtı değildir" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_district_reports_truncation():
    envelope = await CityServicesService(settings=get_settings(), api=FakeApi()).district(
        district="Konak", kinds=["wifi", "izmirim_card"], limit=1
    )
    assert envelope["result_info"]["matched"] == 3
    assert envelope["result_info"]["truncated"] is True


@pytest.mark.asyncio
async def test_district_rejects_unknown_district():
    with pytest.raises(InputValidationError) as excinfo:
        await CityServicesService(settings=get_settings(), api=FakeApi()).district(
            district="Atlantis", kinds=["wifi"], limit=5
        )
    assert excinfo.value.field == "district"
