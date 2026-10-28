from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.nearby import NearbyService
from tests.conftest import fresh

KONAK = (38.41872, 27.12827)
KONAK_BBOX = [27.1200, 38.4100, 27.1400, 38.4300]


class FakeApi:
    def __init__(self, *, fail: set[str] | None = None):
        self.fail = fail or set()

    async def parking(self):
        if "parking" in self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": "inside", "name": "İç Otopark", "lat": 38.4190, "lon": 27.1290,
                 "free": 3, "occupied": 40, "capacity": 43, "status": "Opened",
                 "is_paid": False, "address": None, "opening_hours_today": None},
                {"id": "edge", "name": "Kenar Otopark", "lat": 38.4100, "lon": 27.1200,
                 "free": 0, "occupied": 1, "capacity": 1, "status": "Opened",
                 "is_paid": True, "address": None, "opening_hours_today": None},
                {"id": "outside", "name": "Dış Otopark", "lat": 38.5000, "lon": 27.2000,
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
                {"id": 1, "name": "Karşıyaka Bir", "lat": 38.4600, "lon": 27.1100,
                 "phone": None, "address": "Alaybey", "district": "KARŞIYAKA 1",
                 "area_note": None, "duty_date": "2026-10-28T08:00:00"},
                {"id": 2, "name": "Karşıyaka İki", "lat": 38.4610, "lon": 27.1110,
                 "phone": None, "address": "Bostanlı", "district": "KARŞIYAKA 3",
                 "area_note": None, "duty_date": "2026-10-28T08:00:00"},
                {"id": 3, "name": "Gümüşpala", "lat": 38.4620, "lon": 27.1120,
                 "phone": None, "address": "Yamanlar", "district": "GÜMÜŞPALA",
                 "area_note": "24:00DEN SONRA - KARŞIYAKA 4",
                 "duty_date": "2026-10-28T08:00:00"},
                {"id": 4, "name": "Bornova", "lat": 38.4700, "lon": 27.2200,
                 "phone": None, "address": "Erzene", "district": "BORNOVA 1",
                 "area_note": None, "duty_date": "2026-10-28T08:00:00"},
                {"id": 5, "name": "Konak", "lat": 38.4189, "lon": 27.1285,
                 "phone": None, "address": "Konak", "district": "KONAK",
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


class FakeEshot:
    async def stops(self):
        return (
            [
                {"id": "10030", "name": "Konak", "lat": 38.416218, "lon": 27.126321,
                 "routes": ["303"]},
                {"id": "90000", "name": "Dış", "lat": 38.6000, "lon": 27.4000,
                 "routes": []},
            ],
            fresh(),
        )


def service(**kwargs) -> NearbyService:
    return NearbyService(
        settings=get_settings(), api=FakeApi(**kwargs), eshot=FakeEshot()
    )


@pytest.mark.asyncio
async def test_bbox_includes_boundaries_and_excludes_outside():
    envelope = await service().bbox(bbox=KONAK_BBOX, types=["parking"], limit=10)

    assert envelope["ok"] is True
    assert [row["id"] for row in envelope["data"]] == ["inside", "edge"]
    assert {row["kind"] for row in envelope["data"]} == {"parking"}


@pytest.mark.asyncio
async def test_bbox_has_no_distance_and_echoes_the_rectangle():
    envelope = await service().bbox(bbox=KONAK_BBOX, types=["parking"], limit=10)

    assert all(row["distance_m"] is None for row in envelope["data"])
    assert all(row["maps_url"].startswith("https://www.google.com/maps?q=")
               for row in envelope["data"])
    assert f"bbox={','.join(str(value) for value in KONAK_BBOX)}" in envelope["limits"]


@pytest.mark.asyncio
async def test_bbox_rejects_crossed_and_empty_rectangles():
    with pytest.raises(InputValidationError) as crossed:
        await service().bbox(bbox=[27.14, 38.43, 27.12, 38.41], types=["parking"], limit=5)
    assert crossed.value.field == "bbox"

    with pytest.raises(InputValidationError) as empty:
        await service().bbox(bbox=[27.12, 38.41, 27.12, 38.41], types=["parking"], limit=5)
    assert empty.value.field == "bbox"

    with pytest.raises(InputValidationError) as malformed:
        await service().bbox(bbox=[27.12, 38.41, 27.14], types=["parking"], limit=5)
    assert malformed.value.field == "bbox"


@pytest.mark.asyncio
async def test_bbox_reports_truncation_and_total_match():
    envelope = await service().bbox(bbox=KONAK_BBOX, types=["parking"], limit=1)

    assert len(envelope["data"]) == 1
    assert envelope["result_info"]["matched"] == 2
    assert envelope["result_info"]["truncated"] is True
    assert "2" in envelope["summary"]


@pytest.mark.asyncio
async def test_bbox_keeps_partial_results_and_warns_about_coordinate_only_filtering():
    envelope = await service(fail={"parking"}).bbox(
        bbox=KONAK_BBOX, types=["parking", "metro_station"], limit=10
    )

    assert envelope["ok"] is True
    assert [row["kind"] for row in envelope["data"]] == ["metro_station"]
    joined = " ".join(envelope["warnings"]).lower()
    assert "parking" in joined
    assert "koordinat" in joined


@pytest.mark.asyncio
async def test_bbox_empty_rectangle_result_is_not_an_all_clear():
    envelope = await service().bbox(bbox=[27.0, 38.0, 27.01, 38.01], types=["parking"], limit=10)

    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert any("kanıtı değildir" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_district_matches_published_region_text_only():
    envelope = await service().district(district="Karşıyaka", types=["pharmacy"], limit=10)

    assert envelope["ok"] is True
    assert [row["id"] for row in envelope["data"]] == [3, 1, 2]
    assert all(row["distance_m"] is None for row in envelope["data"])
    assert all(row["district_match"] == "published_region_text"
               for row in envelope["data"])
    joined = " ".join(envelope["warnings"]).lower()
    assert "sınır" in joined or "boundary" in joined
    assert "ilçe" in joined


@pytest.mark.asyncio
async def test_district_skips_types_without_a_district_field():
    envelope = await service().district(
        district="Karşıyaka", types=["pharmacy", "parking", "bus_stop"], limit=10
    )

    assert envelope["ok"] is True
    assert {row["kind"] for row in envelope["data"]} == {"pharmacy"}
    joined = " ".join(envelope["warnings"]).lower()
    assert "parking" in joined and "bus_stop" in joined


@pytest.mark.asyncio
async def test_district_with_no_supported_type_is_an_explicit_error():
    with pytest.raises(InputValidationError) as excinfo:
        await service().district(district="Karşıyaka", types=["parking"], limit=5)
    assert excinfo.value.field == "types"
    assert "eczane" in str(excinfo.value).lower() or "pharmacy" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_district_rejects_unknown_names():
    with pytest.raises(InputValidationError) as excinfo:
        await service().district(district="Atlantis", types=["pharmacy"], limit=5)
    assert excinfo.value.field == "district"


@pytest.mark.asyncio
async def test_district_without_matches_is_not_proof_of_no_pharmacy():
    envelope = await service().district(district="Karaburun", types=["pharmacy"], limit=10)

    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert any("kanıtı değildir" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_district_reports_truncation():
    envelope = await service().district(district="Karşıyaka", types=["pharmacy"], limit=2)

    assert len(envelope["data"]) == 2
    assert envelope["result_info"]["matched"] == 3
    assert envelope["result_info"]["truncated"] is True


@pytest.mark.asyncio
async def test_district_source_failure_is_source_unavailable():
    envelope = await service(fail={"pharmacy"}).district(
        district="Karşıyaka", types=["pharmacy"], limit=5
    )

    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
