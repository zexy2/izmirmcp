from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.connectors import izsu
from app.connectors.izsu import (
    IzsuClient,
    merge_csv_coordinates,
    parse_dam_csv,
    parse_dam_json,
    turkish_fold,
)
from app.connectors.schema import SchemaDriftError
from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.water import WaterService
from tests.conftest import fresh

PAYLOAD = {
    "data": [
        {
            "id": "a",
            "date": "2026-10-29",
            "waterStatus": 138725000,
            "usableWaterStatus": 119125000,
            "occupancyRate": 41.5,
            "waterLevel": 52.1,
            "damWellFacility": {"id": "t", "name": "Tahtalı Barajı"},
            "maximumWaterCapacity": 306650000,
            "minimumWaterCapacity": 19600000,
            "maximumWaterLevel": 60.5,
            "minimumWaterLevel": 31,
            "usableWaterCapacity": 287050000,
        },
        {
            "id": "b",
            "date": "2026-10-29",
            "occupancyRate": 60.49,
            "waterLevel": 40.2,
            "damWellFacility": {"id": "u", "name": "Ürkmez Barajı"},
        },
        {
            "id": "c",
            "date": "2026-10-29",
            "occupancyRate": 12.0,
            "damWellFacility": {"id": "i", "name": "İZMİR Kuyuları"},
        },
        {"id": "x", "damWellFacility": {"name": ""}},
        "garbage",
    ]
}

CSV_TEXT = """BARAJ_KUYU_ID;BARAJ_KUYU_ADI;DURUM_TARIHI;DOLULUK_ORANI;ENLEM;BOYLAM
1;TAHTALI BARAJI;2026-10-14T00:00:00;42.75;38.157434;27.122630
"""


def test_parse_dam_json_maps_fields_and_skips_bad_rows():
    rows = parse_dam_json(PAYLOAD)
    assert [row["name"] for row in rows] == ["Tahtalı Barajı", "Ürkmez Barajı", "İZMİR Kuyuları"]
    first = rows[0]
    assert first["occupancy_percent"] == 41.5
    assert first["water_level"] == 52.1
    assert first["usable_water_capacity_m3"] == 287050000
    assert first["min_capacity_m3"] == 19600000
    assert first["min_water_level"] == 31
    assert first["max_water_level"] == 60.5
    assert first["water_volume_m3"] == 138725000
    assert first["observed_at"] == "2026-10-29"


@pytest.mark.parametrize("payload", [None, [], {"data": None}, {"items": []}])
def test_parse_dam_json_rejects_unexpected_envelope(payload):
    with pytest.raises(SchemaDriftError):
        parse_dam_json(payload)


def test_parse_dam_json_empty_data_is_empty_list():
    assert parse_dam_json({"data": []}) == []


def test_turkish_fold_handles_dotted_and_dotless_i():
    assert turkish_fold("TAHTALI") == turkish_fold("tahtalı")
    assert turkish_fold("İZMİR") == "izmir"
    assert turkish_fold("TAHTALI") != turkish_fold("tahtali")


def test_merge_csv_coordinates_by_folded_name():
    merged = merge_csv_coordinates(parse_dam_json(PAYLOAD), parse_dam_csv(CSV_TEXT))
    assert merged[0]["lat"] == 38.157434
    assert merged[1]["lat"] is None


class FakeIzsu:
    def __init__(self, payload=PAYLOAD, exc: Exception | None = None):
        self.payload = payload
        self.exc = exc
        self.days: list[str] = []

    async def dam_status(self, day):
        self.days.append(day)
        if self.exc:
            raise self.exc
        return parse_dam_json(self.payload), fresh("2026-10-29")


def _service(client):
    return WaterService(settings=get_settings(), client=client)


@pytest.mark.asyncio
async def test_dam_status_defaults_to_today_and_ranks():
    client = FakeIzsu()
    envelope = await _service(client).dam_status()
    assert client.days == [date.today().isoformat()]
    assert envelope["ok"] is True
    assert [row["name"] for row in envelope["data"]][0] == "Ürkmez Barajı"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["tahtalı", "TAHTALI", "Tahtalı Barajı"])
async def test_dam_name_turkish_casefold(query):
    envelope = await _service(FakeIzsu()).dam_status(date="2026-10-29", dam_name=query)
    assert [row["name"] for row in envelope["data"]] == ["Tahtalı Barajı"]


@pytest.mark.asyncio
async def test_dam_name_dotted_capital_i():
    envelope = await _service(FakeIzsu()).dam_status(dam_name="izmir")
    assert [row["name"] for row in envelope["data"]] == ["İZMİR Kuyuları"]


@pytest.mark.asyncio
async def test_unknown_dam_is_empty_with_warning():
    envelope = await _service(FakeIzsu()).dam_status(dam_name="Yok Barajı")
    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert "kayıt döndürmedi" in envelope["warnings"][0]


@pytest.mark.asyncio
async def test_empty_day_is_empty_not_error():
    envelope = await _service(FakeIzsu(payload={"data": []})).dam_status(date="2020-01-01")
    assert envelope["ok"] is True
    assert envelope["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["29-10-2026", "2026-13-01", "yesterday"])
async def test_invalid_date_rejected(bad):
    with pytest.raises(InputValidationError):
        await _service(FakeIzsu()).dam_status(date=bad)


@pytest.mark.asyncio
async def test_future_date_rejected():
    future = (date.today() + timedelta(days=2)).isoformat()
    with pytest.raises(InputValidationError):
        await _service(FakeIzsu()).dam_status(date=future)


@pytest.mark.asyncio
async def test_source_failure_is_typed_envelope():
    from app.connectors.http import SourceError

    envelope = await _service(FakeIzsu(exc=SourceError("HTTP 400"))).dam_status()
    assert envelope["ok"] is False
    assert envelope["error"]["code"]


def test_ttl_long_for_past_short_for_today():
    client = IzsuClient(get_settings())
    assert client._ttl_for("2020-01-01") > client._ttl_for(date.today().isoformat())


@pytest.mark.asyncio
async def test_water_status_falls_back_to_csv_when_json_fails(monkeypatch):
    client = IzsuClient(get_settings())

    async def boom(day):
        raise SchemaDriftError("bad json")

    async def csv():
        return parse_dam_csv(CSV_TEXT), fresh("2026-10-14T00:00:00")

    monkeypatch.setattr(client, "dam_status", boom)
    monkeypatch.setattr(client, "dams_csv", csv)
    rows, _info = await client.dams()
    assert rows[0]["name"] == "TAHTALI BARAJI"


@pytest.mark.asyncio
async def test_water_status_prefers_json_and_merges_coordinates(monkeypatch):
    client = IzsuClient(get_settings())

    async def ok(day):
        return parse_dam_json(PAYLOAD), fresh("2026-10-29")

    async def csv():
        return parse_dam_csv(CSV_TEXT), fresh("2026-10-14T00:00:00")

    monkeypatch.setattr(client, "dam_status", ok)
    monkeypatch.setattr(client, "dams_csv", csv)
    rows, info = await client.dams()
    assert rows[0]["usable_water_capacity_m3"] == 287050000
    assert rows[0]["lat"] == 38.157434
    assert info.source_updated_at == "2026-10-29"
    envelope = await WaterService(settings=get_settings(), client=client).status()
    assert envelope["ok"] is True
    assert "min_water_level" in envelope["data"][0]


def test_default_api_base():
    assert izsu.DEFAULT_IZSU_API_BASE_URL == "https://izsu.gov.tr/api/proxy"


class FakeIzsuWithCsv(FakeIzsu):
    async def dams_csv(self):
        return parse_dam_csv(CSV_TEXT), fresh("2026-10-14T00:00:00")


def _tls_error():
    from app.connectors.http import SourceError

    return SourceError("source request failed: ConnectError [SSL: CERTIFICATE_VERIFY_FAILED]")


@pytest.mark.asyncio
async def test_dam_status_tls_error_falls_back_to_csv():
    envelope = await _service(FakeIzsuWithCsv(exc=_tls_error())).dam_status()
    assert envelope["ok"] is True
    assert envelope["data"][0]["name"] == "TAHTALI BARAJI"
    assert "source: csv_fallback" in envelope["limits"]
    assert any("CSV" in w for w in envelope["warnings"])


@pytest.mark.asyncio
async def test_dam_status_past_date_fallback_warns_explicitly():
    past = (date.today() - timedelta(days=3)).isoformat()
    envelope = await _service(FakeIzsuWithCsv(exc=_tls_error())).dam_status(date=past)
    assert envelope["ok"] is True
    assert "source: csv_fallback" in envelope["limits"]
    assert past in envelope["warnings"][0]
    assert "desteklenmiyor" in envelope["warnings"][0]


@pytest.mark.asyncio
async def test_dam_status_fallback_csv_failure_returns_original_error():
    class Broken(FakeIzsu):
        async def dams_csv(self):
            raise ValueError("csv down")

    envelope = await _service(Broken(exc=_tls_error())).dam_status()
    assert envelope["ok"] is False
