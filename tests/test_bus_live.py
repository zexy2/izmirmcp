from __future__ import annotations

import pytest

from app.connectors import eshot as eshot_module
from app.connectors.eshot import EshotConnector, parse_comma_number
from app.connectors.http import SourceError
from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.bus import BusService
from tests.conftest import fresh
from tests.test_bus import ARRIVALS, STOP_ROWS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("27,14515167", 27.14515167), ("38.4", 38.4), (27.1, 27.1), ("", None), ("abc", None), (None, None)],
)
def test_comma_decimal_parse(raw, expected):
    assert parse_comma_number(raw) == expected


def _patch(monkeypatch, payload):
    calls = []

    async def fake_get_json(url, **kwargs):
        calls.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    async def no_throttle():
        return None

    monkeypatch.setattr(eshot_module, "get_json", fake_get_json)
    monkeypatch.setattr(eshot_module, "_throttle", no_throttle)
    return calls


@pytest.mark.asyncio
async def test_line_positions_parse_comma_coordinates(monkeypatch):
    calls = _patch(monkeypatch, {
        "HataMesaj": "", "HataVarMi": False,
        "HatOtobusKonumlari": [
            {"OtobusId": 11991, "Yon": 0, "KoorY": "27,14515167", "KoorX": "38,35391167"},
            {"OtobusId": 1, "Yon": 1, "KoorY": "bozuk", "KoorX": "38,1"},
            None,
        ],
    })
    rows, _ = await EshotConnector(settings=get_settings()).line_positions("5")
    assert calls[0].endswith("/hatotobuskonumlari/5")
    assert rows == [{"bus_id": 11991, "line": "5", "direction": 0,
                     "lat": 38.35391167, "lon": 27.14515167}]


@pytest.mark.asyncio
async def test_line_positions_source_error_flag_raises(monkeypatch):
    _patch(monkeypatch, {"HataVarMi": True, "HataMesaj": "x", "HatOtobusKonumlari": []})
    with pytest.raises(SourceError):
        await EshotConnector(settings=get_settings()).line_positions("5")


class FakeApi:
    def __init__(self, positions=None, fail=False):
        self.positions = positions or []
        self.fail = fail

    async def stops(self):
        return STOP_ROWS, fresh()

    async def arrivals(self, stop_id):
        rows = list(ARRIVALS) + [{**ARRIVALS[0], "bus_id": 9, "line": "304"}]
        return (rows if stop_id == "10030" else []), fresh()

    async def line_positions(self, line):
        if self.fail:
            raise SourceError("down")
        return self.positions, fresh()


@pytest.mark.asyncio
async def test_live_positions_envelope():
    api = FakeApi(positions=[{"bus_id": 1, "line": "5", "direction": 0, "lat": 38.4, "lon": 27.1}])
    envelope = await BusService(settings=get_settings(), api=api).line_live_positions(line="5")
    assert envelope["ok"] is True
    assert envelope["data"][0]["maps_url"]
    assert envelope["freshness"]["ttl_seconds"] <= 15


@pytest.mark.asyncio
async def test_live_positions_empty_and_failure():
    service = BusService(settings=get_settings(), api=FakeApi())
    empty = await service.line_live_positions(line="5")
    assert empty["ok"] is True and empty["data"] == []
    assert any("kanıtı değildir" in item for item in empty["warnings"])
    failed = await BusService(settings=get_settings(), api=FakeApi(fail=True)).line_live_positions(line="5")
    assert failed["ok"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "5/../x", "123456789", None, True])
async def test_line_is_validated(bad):
    with pytest.raises(InputValidationError):
        await BusService(settings=get_settings(), api=FakeApi()).line_live_positions(line=bad)


@pytest.mark.asyncio
async def test_line_arrivals_filters_stop_arrivals_by_line():
    envelope = await BusService(settings=get_settings(), api=FakeApi()).line_arrivals(
        line="303", stop_id="10030"
    )
    assert envelope["ok"] is True
    assert [row["line"] for row in envelope["data"]] == ["303"]
    assert envelope["result_info"]["matched"] == 1


@pytest.mark.asyncio
async def test_line_arrivals_without_stop_falls_back_to_positions():
    api = FakeApi(positions=[{"bus_id": 1, "line": "303", "direction": 0, "lat": 38.4, "lon": 27.1}])
    envelope = await BusService(settings=get_settings(), api=api).line_arrivals(line="303")
    assert envelope["ok"] is True and envelope["data"][0]["bus_id"] == 1
