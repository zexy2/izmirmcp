from __future__ import annotations

from datetime import date

import pytest

from app.connectors import ibb_cbs
from app.connectors.http import SourceError
from app.connectors.ibb_cbs import (
    CBS_LAYERS,
    IbbCbsConnector,
    parse_cbs_rows,
    parse_market_prices,
    parse_pharmacy_rows,
)
from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services import cbs as cbs_service
from app.services.cbs import CbsService
from tests.conftest import fresh

MUSEUM = {
    "ILCE": "KONAK",
    "KAPINO": "1/1A",
    "ENLEM": 38.424956,
    "ACIKLAMA": "Arşiv",
    "MAHALLE": "AKDENİZ",
    "ADI": "APİKAM",
    "BOYLAM": 27.1398,
    "YOL": "Şehit Fethi Bey",
}


def test_layer_allowlist_size_and_shape():
    assert len(CBS_LAYERS) >= 80
    assert len(set(CBS_LAYERS)) == len(CBS_LAYERS)
    assert all(name.isalpha() and name.islower() for name in CBS_LAYERS)


def test_cbs_rows_parse_and_drop_bad_coordinates():
    rows = parse_cbs_rows([MUSEUM, {**MUSEUM, "ENLEM": None}, {**MUSEUM, "ENLEM": "38,41"}, None])
    assert [row["name"] for row in rows] == ["APİKAM", "APİKAM"]
    assert rows[1]["lat"] == 38.41


def test_pharmacy_lokasyon_x_is_latitude():
    rows = parse_pharmacy_rows(
        [
            {
                "LokasyonY": "27.197760",
                "LokasyonX": "38.425863",
                "Adi": "ALTINDAG ECZANESİ",
                "EczaneId": 1,
                "Bolge": "ALTINDAĞ",
            }
        ]
    )
    assert rows[0]["lat"] == pytest.approx(38.425863)
    assert rows[0]["lon"] == pytest.approx(27.19776)


def test_market_price_parse():
    bulletin, rows = parse_market_prices(
        {
            "BultenTarihi": "2026-10-30T00:00:00",
            "HalFiyatListesi": [
                {
                    "MalAdi": "ANANAS",
                    "Birim": "ADET",
                    "AsgariUcret": 100,
                    "AzamiUcret": 150,
                    "OrtalamaUcret": 125,
                    "MalTipAdi": "İTHAL",
                },
                "junk",
            ],
        }
    )
    assert bulletin == "2026-10-30"
    assert rows == [
        {
            "product": "ANANAS",
            "category": "İTHAL",
            "unit": "ADET",
            "min_price": 100.0,
            "max_price": 150.0,
            "avg_price": 125.0,
        }
    ]
    with pytest.raises(SourceError):
        parse_market_prices([])


@pytest.mark.asyncio
async def test_connector_pages_only_when_rows_missing(monkeypatch):
    calls = []

    async def fake(url, **kwargs):
        calls.append(url)
        if "sayfa_numarasi=2" in url:
            return {"onemliyer": [{**MUSEUM, "ADI": "B"}]}
        return {"kayit_sayisi": 2, "toplam_sayfa_sayisi": 2, "onemliyer": [MUSEUM]}

    monkeypatch.setattr(ibb_cbs, "get_json", fake)
    rows, _ = await IbbCbsConnector(get_settings()).layer("muzeler")
    assert [row["name"] for row in rows] == ["APİKAM", "B"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_connector_single_page_when_complete(monkeypatch):
    calls = []

    async def fake(url, **kwargs):
        calls.append(url)
        return {"kayit_sayisi": 1, "toplam_sayfa_sayisi": 8, "onemliyer": [MUSEUM]}

    monkeypatch.setattr(ibb_cbs, "get_json", fake)
    await IbbCbsConnector(get_settings()).layer("muzeler")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_connector_rejects_unknown_layer():
    with pytest.raises(ValueError):
        await IbbCbsConnector(get_settings()).layer("../admin")


@pytest.mark.asyncio
async def test_hal_204_is_none(monkeypatch):
    async def empty(url, **kwargs):
        return ""

    monkeypatch.setattr(ibb_cbs, "get_text", empty)
    payload, _ = await IbbCbsConnector(get_settings()).market_prices("balik", "2026-10-29")
    assert payload is None


@pytest.mark.asyncio
async def test_hal_invalid_json_raises(monkeypatch):
    async def bad(url, **kwargs):
        return "<html>"

    monkeypatch.setattr(ibb_cbs, "get_text", bad)
    with pytest.raises(SourceError):
        await IbbCbsConnector(get_settings()).market_prices("balik", "2026-10-28")


class FakeApi:
    def __init__(self, bulletins=None, fail=False):
        self.bulletins = bulletins or {}
        self.fail = fail
        self.days = []

    async def layer(self, name):
        if self.fail:
            raise SourceError("down")
        return parse_cbs_rows([MUSEUM, {**MUSEUM, "ADI": "Uzak", "ENLEM": 38.9, "ILCE": "BERGAMA"}]), fresh()

    async def market_prices(self, kind, day, today=False):
        self.days.append(day)
        return self.bulletins.get(day), fresh()

    async def all_pharmacies(self):
        return parse_pharmacy_rows(
            [
                {
                    "LokasyonY": "27.19",
                    "LokasyonX": "38.42",
                    "Adi": "ALTINDAG ECZANESİ",
                    "EczaneId": 1,
                    "Bolge": "ALTINDAĞ",
                },
                {"LokasyonY": "27.0", "LokasyonX": "38.6", "Adi": "BAŞKA", "EczaneId": 2, "Bolge": "MENEMEN"},
            ]
        ), fresh()


def _service(api):
    return CbsService(settings=get_settings(), api=api)


@pytest.mark.asyncio
async def test_layer_service_invalid_layer_rejected():
    with pytest.raises(InputValidationError) as excinfo:
        await _service(FakeApi()).layer(layer="secret")
    assert excinfo.value.field == "layer"


@pytest.mark.asyncio
async def test_layer_service_near_and_district():
    near = await _service(FakeApi()).layer(layer="muzeler", near_lat=38.425, near_lon=27.14, radius_m=1000)
    assert [row["name"] for row in near["data"]] == ["APİKAM"]
    assert "distance_m" in near["data"][0]
    district = await _service(FakeApi()).layer(layer="muzeler", district="bergama")
    assert [row["name"] for row in district["data"]] == ["Uzak"]
    with pytest.raises(InputValidationError):
        await _service(FakeApi()).layer(layer="muzeler", near_lat=38.4)
    with pytest.raises(InputValidationError):
        await _service(FakeApi()).layer(layer="muzeler", radius_m=100)


@pytest.mark.asyncio
async def test_layer_service_source_failure():
    envelope = await _service(FakeApi(fail=True)).layer(layer="muzeler")
    assert envelope["ok"] is False


@pytest.mark.asyncio
async def test_market_prices_fall_back_to_previous_day(monkeypatch):
    monkeypatch.setattr(cbs_service, "_today", lambda: date(2026, 11, 1))
    api = FakeApi(
        bulletins={"2026-10-30": {"bulletin_date": "2026-10-30", "rows": [{"product": "ANANAS"}, {"product": "ARMUT"}]}}
    )
    envelope = await _service(api).market_prices(kind="sebzemeyve", query="ananas")
    assert envelope["ok"] is True
    assert api.days == ["2026-11-01", "2026-10-31", "2026-10-30"]
    assert envelope["data"] == [{"product": "ANANAS"}]
    assert any("2026-10-30" in item for item in envelope["warnings"])


@pytest.mark.asyncio
async def test_market_prices_all_empty(monkeypatch):
    monkeypatch.setattr(cbs_service, "_today", lambda: date(2026, 11, 1))
    envelope = await _service(FakeApi()).market_prices(kind="balik")
    assert envelope["ok"] is True and envelope["data"] == []
    assert any("204" in item for item in envelope["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"kind": "et"}, {"day": "30.10.2026"}, {"day": "2999-01-01"}])
async def test_market_prices_validation(kwargs):
    with pytest.raises(InputValidationError):
        await _service(FakeApi()).market_prices(**kwargs)


@pytest.mark.asyncio
async def test_pharmacies_all_turkish_casefold_district():
    envelope = await _service(FakeApi()).pharmacies_all(area="altındağ")
    assert [row["name"] for row in envelope["data"]] == ["ALTINDAG ECZANESİ"]
    envelope = await _service(FakeApi()).pharmacies_all(area="ALTINDAĞ")
    assert len(envelope["data"]) == 1
