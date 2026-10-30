from __future__ import annotations

import pytest

from app.connectors.http import SourceError
from app.connectors.izmir_api import IzmirOpenApi
from app.core.settings import get_settings
from app.core.source_cache import CacheInfo
from app.core.validation import InputValidationError
from app.services.transit import TransitService
from tests.conftest import fresh

LINES = [
    {
        "Aciklama": "Kara Tarafı",
        "Adi": "Fahrettin Altay - Halkapınar",
        "HatId": 1,
        "HatBaslangic": "Fahrettin Altay",
        "HatBitis": "Halkapınar",
    },
    None,
]
STATIONS = [
    {"Boylam": 27.069416, "IstasyonId": 21, "Adi": "Fahrettin Altay", "Enlem": 38.397748},
    {"Boylam": 999, "IstasyonId": 22, "Adi": "Bozuk", "Enlem": 38.4},
]
FREQ = [{"Sira": 1, "BaslangicSaati": "06:00:00", "TarifeId": 1, "BitisSaati": "06:30:00", "Aralik": 7.5, "SeferId": 1}]


def _api(payloads: dict[str, object]) -> IzmirOpenApi:
    api = IzmirOpenApi(get_settings())

    async def cached(path: str, key: str):
        return payloads[path], CacheInfo(status="fresh", retrieved_at="2026-10-30T00:00:00+00:00")

    api._cached = cached  # type: ignore[method-assign]
    return api


@pytest.mark.asyncio
async def test_tram_connector_parses_lines_stations_and_frequency():
    api = _api({"tramvay/hatlar": LINES, "tramvay/istasyonlar/1": STATIONS, "tramvay/seferler/1": FREQ})
    lines, _ = await api.tram_lines()
    assert lines == [
        {
            "line_id": 1,
            "name": "Fahrettin Altay - Halkapınar",
            "side": "Kara Tarafı",
            "start": "Fahrettin Altay",
            "end": "Halkapınar",
        }
    ]
    stations, _ = await api.tram_stations(1)
    assert [row["id"] for row in stations] == [21]
    freq, _ = await api.tram_schedule(1)
    assert freq[0]["interval_minutes"] == 7.5


@pytest.mark.asyncio
async def test_tram_schedule_service_combines_stations_and_frequency():
    api = _api({"tramvay/istasyonlar/1": STATIONS, "tramvay/seferler/1": FREQ})
    envelope = await TransitService(settings=get_settings(), api=api).tram_schedule(line_id=1)
    assert envelope["ok"] is True
    assert envelope["data"][0]["stations"][0]["name"] == "Fahrettin Altay"
    assert envelope["data"][0]["frequency"][0]["start"] == "06:00:00"


@pytest.mark.asyncio
async def test_tram_schedule_empty_source_warns():
    api = _api({"tramvay/istasyonlar/9": [], "tramvay/seferler/9": []})
    envelope = await TransitService(settings=get_settings(), api=api).tram_schedule(line_id=9)
    assert envelope["ok"] is True
    assert any("izmir_tram_lines" in item for item in envelope["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, -1, 1000, True, "1"])
async def test_tram_schedule_rejects_bad_line_id(bad):
    with pytest.raises(InputValidationError):
        await TransitService(settings=get_settings(), api=_api({})).tram_schedule(line_id=bad)


@pytest.mark.asyncio
async def test_tram_lines_source_failure_is_typed():
    class Broken:
        async def tram_lines(self):
            raise SourceError("down")

    envelope = await TransitService(settings=get_settings(), api=Broken()).tram_lines()
    assert envelope["ok"] is False


@pytest.mark.asyncio
async def test_tram_lines_service_lists_rows():
    class Fake:
        async def tram_lines(self):
            return [{"line_id": 1, "name": "x", "side": None, "start": None, "end": None}], fresh()

    envelope = await TransitService(settings=get_settings(), api=Fake()).tram_lines()
    assert envelope["ok"] is True and len(envelope["data"]) == 1
