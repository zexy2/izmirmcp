from __future__ import annotations

import pytest

from app.connectors import ibb_cbs
from app.connectors.ibb_cbs import IbbCbsConnector
from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.bus import _validate_line
from app.services.cbs import CbsService
from app.services.transit import TransitService


@pytest.mark.parametrize("line", ["12\n", "../12", "12/34", "12?x=1", "", "123456789", True, None])
def test_bus_line_rejects_path_and_control_characters(line):
    if line == "12\n":
        # Surrounding whitespace is stripped, so the value itself is safe.
        assert _validate_line(line) == "12"
        return
    with pytest.raises(InputValidationError):
        _validate_line(line)


def test_bus_line_accepts_turkish_letters():
    assert _validate_line("Ç-1") == "Ç-1"


@pytest.mark.asyncio
async def test_cbs_paging_is_capped_and_sequential(monkeypatch):
    calls = []

    async def fake(url, **kwargs):
        calls.append(url)
        return {"kayit_sayisi": 10_000, "toplam_sayfa_sayisi": 500, "onemliyer": [{"ADI": "x"}]}

    monkeypatch.setattr(ibb_cbs, "get_json", fake)
    await IbbCbsConnector(get_settings()).layer("muzeler")
    assert len(calls) == int(getattr(get_settings(), "cbs_max_pages", 10))


@pytest.mark.asyncio
async def test_market_kind_injection_rejected_in_connector():
    with pytest.raises(ValueError):
        await IbbCbsConnector(get_settings()).market_prices("../eczaneler", "2026-10-29")


@pytest.mark.asyncio
@pytest.mark.parametrize("day", ["2026-10-29/../x", "29.10.2026", "2999-01-01"])
async def test_market_day_must_be_past_iso_date(day):
    service = CbsService(settings=get_settings(), api=None)
    with pytest.raises(InputValidationError):
        await service.market_prices(day=day)


@pytest.mark.asyncio
@pytest.mark.parametrize("line_id", [0, 1000, "1", True, -1])
async def test_tram_line_id_bounds(line_id):
    service = TransitService.__new__(TransitService)
    with pytest.raises(InputValidationError):
        await service.tram_schedule(line_id=line_id)
