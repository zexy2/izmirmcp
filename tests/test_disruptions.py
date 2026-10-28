from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.disruptions import DisruptionService
from tests.conftest import fresh

ROWS = [
    {"line": "32", "title": "32 NO.LU HAT GEÇİCİ GÜZERGAH DEĞİŞİKLİĞİ",
     "starts_at": "2026-09-24T00:00:00", "ends_at": "2026-11-06T00:00:00"},
    {"line": "41", "title": "41-42-46 VE 475 NO.LU HATLARIMIZDA GEÇİCİ GÜZERGAH DEĞİŞİKLİKLERİ",
     "starts_at": "2026-10-22T11:25:00", "ends_at": "2026-11-06T00:00:00"},
    {"line": "5", "title": "ESKİ DUYURU", "starts_at": "2025-01-01T00:00:00",
     "ends_at": "2025-02-01T00:00:00"},
]


class FakeApi:
    async def bus_notices(self):
        return ROWS, fresh("2026-10-28T00:00:00")


@pytest.mark.asyncio
async def test_disruptions_are_sorted_with_active_and_window_fields():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        today="2026-10-28", limit=10
    )
    assert envelope["ok"] is True
    assert [row["line"] for row in envelope["data"]][:2] == ["32", "41"]
    assert envelope["data"][0]["active"] is True
    assert envelope["data"][2]["active"] is False


@pytest.mark.asyncio
async def test_disruptions_filters_by_line():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        line="32", today="2026-10-28", limit=10
    )
    assert [row["line"] for row in envelope["data"]] == ["32"]


@pytest.mark.asyncio
async def test_disruptions_active_only_drops_expired_rows():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        today="2026-10-28", active_only=True, limit=10
    )
    assert {row["line"] for row in envelope["data"]} == {"32", "41"}
    assert all(row["active"] for row in envelope["data"])


@pytest.mark.asyncio
async def test_disruptions_warn_that_notices_are_announcements_not_live_delays():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        today="2026-10-28", limit=2
    )
    joined = " ".join(envelope["warnings"]).lower()
    assert "duyuru" in joined
    assert "canlı" in joined
