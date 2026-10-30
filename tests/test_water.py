from __future__ import annotations

import pytest

from app.connectors.izsu import parse_dam_csv
from app.core.settings import get_settings
from app.services.water import WaterService
from tests.conftest import fresh

CSV_TEXT = """\ufeffBARAJ_KUYU_ID;BARAJ_KUYU_ADI;DURUM_TARIHI;DOLULUK_ORANI;ENLEM;BOYLAM;MAKSIMUM_SU_KAPASITESI;TUKETILEBILIR_SU_KAPASITESI
1;Tahtalı Barajı;2026-10-14T00:00:00;42.75;38.157434;27.122630;306650000;122723000
2;Balçova Barajı;2026-10-14T00:00:00;44.77;38.372622;27.037422;7759000;3338000
3;Ürkmez Barajı;2026-10-14T00:00:00;60.49;38.097069;26.957450;8625000;4620000
"""


def test_parse_dam_csv_handles_bom_and_semicolons():
    rows = parse_dam_csv(CSV_TEXT)
    assert len(rows) == 3
    assert rows[0]["name"] == "Tahtalı Barajı"
    assert rows[0]["occupancy_percent"] == 42.75
    assert rows[0]["lat"] == 38.157434
    assert rows[2]["max_capacity_m3"] == 8625000


class FakeIzsu:
    async def dams(self):
        return parse_dam_csv(CSV_TEXT), fresh("2026-10-14T00:00:00")


@pytest.mark.asyncio
async def test_water_status_ranks_by_occupancy_and_limits():
    envelope = await WaterService(settings=get_settings(), client=FakeIzsu()).status(limit=2)
    assert envelope["ok"] is True
    assert [row["name"] for row in envelope["data"]] == ["Ürkmez Barajı", "Balçova Barajı"]
    assert envelope["freshness"]["source_updated_at"] == "2026-10-14T00:00:00"


@pytest.mark.asyncio
async def test_faults_are_reported_unavailable_not_empty():
    envelope = await WaterService(settings=get_settings(), client=FakeIzsu()).status(kind="faults")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert envelope["data"] == []
    assert "500" in envelope["warnings"][0]


# Real published header: SU_YUKSEKLIGI duplicates DOLULUK_ORANI (a percentage).
REAL_HEADER_CSV = (
    "\ufeffBARAJ_KUYU_ID;BARAJ_KUYU_ADI;DURUM_TARIHI;SU_DURUMU;DOLULUK_ORANI;SU_YUKSEKLIGI;"
    "TUKETILEBILIR_SU_KAPASITESI;MAKSIMUM_SU_KAPASITESI;MAKSIMUM_SU_YUKSEKLIGI;"
    "MINIMUM_SU_KAPASITESI;MINIMUM_SU_YUKSEKLIGI;BARAJ_SU_DURUMU_GOSTERIMI;SIRA;ENLEM;BOYLAM;"
    "KULLANILABILIR_GOL_SU_HACMI\n"
    "225;Tahtalı Barajı;2026-10-14T00:00:00;142323000;42.75;42.75;122723000;306650000;60.5;"
    "19600000;31.0;;11;38.157434;27.122630;287050000\n"
)


def test_csv_water_level_is_not_the_occupancy_percentage():
    [row] = parse_dam_csv(REAL_HEADER_CSV)
    assert row["occupancy_percent"] == 42.75
    assert row["water_level"] is None


class FailingJsonIzsu:
    async def dam_status(self, day):
        raise OSError("tls handshake failed")

    async def dams_csv(self):
        return parse_dam_csv(REAL_HEADER_CSV), fresh("2026-10-14T00:00:00")


@pytest.mark.asyncio
async def test_csv_fallback_nulls_water_level_with_note():
    envelope = await WaterService(settings=get_settings(), client=FailingJsonIzsu()).dam_status(
        date="2026-10-14"
    )
    assert envelope["ok"] is True
    assert envelope["data"]
    assert all(row["water_level"] is None for row in envelope["data"])
    assert any("water_level" in item and "CSV" in item for item in envelope["limits"])
