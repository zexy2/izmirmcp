from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.air import AirQualityService
from tests.conftest import fresh


class FakeApi:
    async def air_quality(self, day: str):
        return (
            [
                {"station": "ÇİĞLİ", "station_id": 6, "observed_at": "2026-10-27T00:00:00",
                 "readings": [{"pollutant": "PM10", "value": 10.0, "unit": None},
                              {"pollutant": "SO2", "value": 3.0, "unit": None}]},
                {"station": "ALSANCAK", "station_id": 1, "observed_at": "2026-10-27T00:00:00",
                 "readings": [{"pollutant": "PM10", "value": None, "unit": None}]},
            ],
            fresh(),
        )


@pytest.mark.asyncio
async def test_air_quality_lists_readings_without_inventing_units():
    envelope = await AirQualityService(settings=get_settings(), api=FakeApi()).readings(
        day="2026-10-28", limit=10
    )
    assert envelope["ok"] is True
    assert len(envelope["data"]) == 3
    assert all(row["unit"] is None for row in envelope["data"])
    assert any("observed_at" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_air_quality_station_filter_is_case_and_accent_insensitive():
    envelope = await AirQualityService(settings=get_settings(), api=FakeApi()).readings(
        day="2026-10-28", station="cigli", limit=10
    )
    assert {row["station"] for row in envelope["data"]} == {"ÇİĞLİ"}
