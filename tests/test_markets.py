from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.markets import MarketService
from tests.conftest import fresh

MARKET_ROWS = [
    {"id": "1", "name": "Adalet Pazaryeri", "district": "BAYRAKLI",
     "neighborhood": "ADALET", "lat": 38.45441058, "lon": 27.17942607,
     "note": "Cumartesi  günü kurulmaktadır", "days": ["saturday"]},
    {"id": "2", "name": "Akıncılar Pazaryeri", "district": "ÖDEMİŞ",
     "neighborhood": "AKINCILAR", "lat": 38.22905679, "lon": 27.97334045,
     "note": "Cumartesi Günü Kurulmnaktadır", "days": ["saturday"]},
    {"id": "3", "name": "Konak Pazarı", "district": "KONAK", "neighborhood": "KONAK",
     "lat": 38.41872, "lon": 27.12827, "note": "", "days": []},
]


class FakeApi:
    async def market_rows(self):
        return MARKET_ROWS, fresh("2026-10-26T00:00:00")


@pytest.mark.asyncio
async def test_market_filters_by_day_and_reports_unknown_day():
    envelope = await MarketService(settings=get_settings(), api=FakeApi()).schedule(
        day="cumartesi", limit=10
    )
    assert envelope["ok"] is True
    assert {row["name"] for row in envelope["data"]} == {"Adalet Pazaryeri", "Akıncılar Pazaryeri"}
    assert any("gün" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_market_rows_without_parsed_day_are_reported_not_hidden():
    envelope = await MarketService(settings=get_settings(), api=FakeApi()).schedule(limit=10)
    assert envelope["ok"] is True
    names = [row["name"] for row in envelope["data"]]
    assert "Konak Pazarı" in names
    assert envelope["data"][0]["day_confidence"] in {"parsed", "unknown"}


@pytest.mark.asyncio
async def test_market_rejects_unknown_day_name():
    with pytest.raises(InputValidationError) as excinfo:
        await MarketService(settings=get_settings(), api=FakeApi()).schedule(day="someday")
    assert excinfo.value.field == "day"


@pytest.mark.asyncio
async def test_market_filters_by_district_case_and_accent_insensitively():
    envelope = await MarketService(settings=get_settings(), api=FakeApi()).schedule(
        district="odemıs", limit=10
    )
    assert [row["name"] for row in envelope["data"]] == ["Akıncılar Pazaryeri"]


@pytest.mark.asyncio
async def test_market_rejects_both_coordinates_missing():
    with pytest.raises(InputValidationError):
        await MarketService(settings=get_settings(), api=FakeApi()).schedule(lat=38.4)
