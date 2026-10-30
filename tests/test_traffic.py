"""Historical arterial speed/duration snapshots.

İzmir publishes no live traffic index (``/api/ibb/trafikyogunluk`` is 404). The
only real data is a per-segment history; every answer must say it is historical.
"""
from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.traffic import TrafficService
from tests.conftest import fresh

ROWS = [
    {"segment_from": "Marina Kavşağı", "segment_to": "Konak Pier",
     "observed_at": "2026-10-22T08:15:00", "hour": "08:15:00",
     "speed_kmh": 39.0, "duration_minutes": 10.0},
    {"segment_from": "Marina Kavşağı", "segment_to": "Konak Pier",
     "observed_at": "2026-10-22T09:15:00", "hour": "09:15:00",
     "speed_kmh": 17.0, "duration_minutes": 23.0},
    {"segment_from": "Zafer Payzın", "segment_to": "Çiğli Kavşağı",
     "observed_at": "2026-10-21T18:00:00", "hour": "18:00:00",
     "speed_kmh": 55.0, "duration_minutes": 8.0},
]


class FakeApi:
    async def traffic_rows(self):
        return ROWS, fresh("2026-10-22T00:00:00")

    async def traffic_recent(self, limit):
        return ROWS[:limit], fresh("2026-10-22T00:00:00"), len(ROWS)


@pytest.mark.asyncio
async def test_lists_segment_history_with_a_staleness_warning():
    envelope = await TrafficService(settings=get_settings(), api=FakeApi()).list(limit=10)
    assert envelope["ok"] is True
    assert len(envelope["data"]) == 3
    from app.core.geo import normalize_name

    joined = normalize_name(" ".join(envelope["warnings"]))
    assert "gecmis" in joined or "historical" in joined
    assert "canli" in joined


@pytest.mark.asyncio
async def test_filters_by_date_range_and_reports_total():
    envelope = await TrafficService(settings=get_settings(), api=FakeApi()).list(
        since="2026-10-22", until="2026-10-22", limit=1
    )
    assert envelope["result_info"]["matched"] == 2
    assert envelope["result_info"]["truncated"] is True


@pytest.mark.asyncio
async def test_filters_by_segment_name_case_insensitively():
    envelope = await TrafficService(settings=get_settings(), api=FakeApi()).list(
        segment="marina", limit=10
    )
    assert len(envelope["data"]) == 2
    assert all("Marina" in row["segment_from"] for row in envelope["data"])


@pytest.mark.asyncio
async def test_sorted_most_recent_first():
    envelope = await TrafficService(settings=get_settings(), api=FakeApi()).list(limit=10)
    dates = [row["observed_at"] for row in envelope["data"]]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_rejects_a_backwards_date_range():
    with pytest.raises(InputValidationError) as excinfo:
        await TrafficService(settings=get_settings(), api=FakeApi()).list(
            since="2026-10-22", until="2026-10-01"
        )
    assert excinfo.value.field in {"since", "until"}


@pytest.mark.asyncio
async def test_invalid_date_format_is_rejected():
    with pytest.raises(InputValidationError) as excinfo:
        await TrafficService(settings=get_settings(), api=FakeApi()).list(since="22-10-2026")
    assert excinfo.value.field == "since"


@pytest.mark.asyncio
async def test_source_failure_returns_unavailable():
    class Broken(FakeApi):
        async def traffic_rows(self):
            raise RuntimeError("boom")

        async def traffic_recent(self, limit):
            raise RuntimeError("boom")

    envelope = await TrafficService(settings=get_settings(), api=Broken()).list(limit=5)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_empty_result_is_not_an_all_clear():
    envelope = await TrafficService(settings=get_settings(), api=FakeApi()).list(
        segment="yok-boyle-bir-segment", limit=5
    )
    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert envelope["warnings"]
