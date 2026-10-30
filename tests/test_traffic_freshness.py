"""Traffic freshness must come from the data, not from retrieval time.

The audit measured ``freshness.status="fresh"`` with ``source_updated_at=null``
while the newest published measurement was 2026-10-22 — eight days old. It also
measured a 6.87 s cold ``limit=2`` call because the service paged all 18,731
rows before cutting. These tests pin both: an explicit newest-observation
freshness basis, and a recent-page path whose fetched volume follows the limit.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.settings import get_settings
from app.core.source_cache import CacheInfo
from app.services.traffic import TrafficService
from tests.conftest import fresh

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def row(minute: int, observed: str, *, segment_from: str = "Marina Kavşağı") -> dict:
    return {
        "segment_from": segment_from,
        "segment_to": "Konak Pier",
        "observed_at": observed,
        "hour": observed[11:19],
        "speed_kmh": 20.0 + minute,
        "duration_minutes": 10.0,
    }


ROWS = [
    row(0, "2026-10-22T19:05:00"),
    row(1, "2026-10-22T18:05:00"),
    row(2, "2026-10-21T19:05:00", segment_from="Zafer Payzın"),
    row(3, "2026-10-21T18:05:00", segment_from="Zafer Payzın"),
]


class FakeApi:
    """Serves the same rows through both the full scan and the recent page."""

    def __init__(self, rows: list[dict] | None = None, *, total: int | None = None):
        self.rows = list(ROWS if rows is None else rows)
        self.total = len(self.rows) if total is None else total
        self.full_calls = 0
        self.recent_calls: list[int] = []

    async def traffic_rows(self):
        self.full_calls += 1
        return self.rows, fresh(self.rows[0]["observed_at"] if self.rows else None)

    async def traffic_recent(self, limit: int):
        self.recent_calls.append(limit)
        return self.rows[:limit], fresh(self.rows[0]["observed_at"] if self.rows else None), self.total


def service(api: FakeApi, *, now: datetime = NOW) -> TrafficService:
    return TrafficService(settings=get_settings(), api=api, now=lambda: now)


@pytest.mark.asyncio
async def test_freshness_is_derived_from_the_newest_published_observation():
    api = FakeApi()

    envelope = await service(api).list(limit=2)

    assert envelope["freshness"]["status"] == "stale"
    assert envelope["freshness"]["source_updated_at"] == "2026-10-22T19:05:00"
    joined = " ".join(envelope["limits"])
    assert "en_yeni_olcum=2026-10-22T19:05:00" in joined
    assert "stale_after_hours=72" in joined
    assert any("stale" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_a_recent_observation_is_reported_fresh():
    rows = [row(0, "2026-10-30T09:00:00")]

    envelope = await service(FakeApi(rows)).list(limit=1)

    assert envelope["freshness"]["status"] == "fresh"
    assert envelope["freshness"]["source_updated_at"] == "2026-10-30T09:00:00"
    assert not any("stale" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_a_missing_timestamp_is_unknown_not_fresh():
    rows = [dict(row(0, "2026-10-22T19:05:00"), observed_at=None)]

    envelope = await service(FakeApi(rows)).list(limit=1)

    assert envelope["freshness"]["status"] == "unknown"
    assert envelope["freshness"]["source_updated_at"] is None
    assert any("bilinmiyor" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_a_stale_cache_fallback_stays_stale_even_if_the_row_is_recent():
    class StaleApi(FakeApi):
        async def traffic_recent(self, limit: int):
            rows, _info, total = await super().traffic_recent(limit)
            return rows, CacheInfo(
                status="stale",
                retrieved_at="2026-10-30T12:00:00+00:00",
                source_updated_at="2026-10-30T09:00:00",
                age_seconds=100.0,
            ), total

    envelope = await service(StaleApi([row(0, "2026-10-30T09:00:00")])).list(limit=1)

    assert envelope["freshness"]["status"] == "stale"


@pytest.mark.asyncio
async def test_a_stale_cache_without_a_timestamp_still_answers():
    class StaleApi(FakeApi):
        async def traffic_recent(self, limit: int):
            rows, _info, total = await super().traffic_recent(limit)
            return rows, CacheInfo(
                status="stale",
                retrieved_at="2026-10-30T12:00:00+00:00",
                source_updated_at=None,
                age_seconds=100.0,
            ), total

    rows = [dict(row(0, "2026-10-22T19:05:00"), observed_at=None)]
    envelope = await service(StaleApi(rows)).list(limit=1)

    assert envelope["ok"] is True
    assert envelope["freshness"]["status"] == "stale"
    assert envelope["freshness"]["source_updated_at"] is None
    assert any("stale" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_an_unfiltered_small_limit_uses_one_recent_page():
    api = FakeApi(total=18_731)

    envelope = await service(api).list(limit=2)

    assert api.recent_calls == [2]
    assert api.full_calls == 0
    assert len(envelope["data"]) == 2
    assert envelope["result_info"]["matched"] == 18_731
    assert envelope["result_info"]["truncated"] is True
    assert "matched_kaynagi=kaynak_toplam" in envelope["limits"]


@pytest.mark.asyncio
async def test_a_filtered_query_still_scans_the_full_history():
    api = FakeApi()

    envelope = await service(api).list(segment="marina", limit=2)

    assert api.full_calls == 1
    assert api.recent_calls == []
    assert envelope["result_info"]["matched"] == 2
    assert "matched_kaynagi=kaynak_toplam" not in envelope["limits"]
    assert len(envelope["data"]) == 2


@pytest.mark.asyncio
async def test_results_are_identical_at_every_limit():
    api = FakeApi(total=18_731)
    expected = list(ROWS)

    for limit in (1, 2, 3, 4, 50):
        envelope = await service(api).list(limit=limit)
        assert [item["observed_at"] for item in envelope["data"]] == [
            item["observed_at"] for item in expected[:limit]
        ]
        assert envelope["result_info"]["matched"] == 18_731
