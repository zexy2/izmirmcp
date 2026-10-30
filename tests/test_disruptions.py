from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.disruptions import DisruptionService
from tests.conftest import fresh

ROWS = [
    {
        "line": "32",
        "title": "32 NO.LU HAT GEÇİCİ GÜZERGAH DEĞİŞİKLİĞİ",
        "starts_at": "2026-09-24T00:00:00",
        "ends_at": "2026-11-06T00:00:00",
    },
    {
        "line": "41",
        "title": "41-42-46 VE 475 NO.LU HATLARIMIZDA GEÇİCİ GÜZERGAH DEĞİŞİKLİKLERİ",
        "starts_at": "2026-10-22T11:25:00",
        "ends_at": "2026-11-06T00:00:00",
    },
    {"line": "5", "title": "ESKİ DUYURU", "starts_at": "2025-01-01T00:00:00", "ends_at": "2025-02-01T00:00:00"},
]


class FakeApi:
    async def bus_notices(self):
        return ROWS, fresh("2026-10-28T00:00:00")

    async def metro_announcements(self):
        return [], fresh()

    async def ferry_announcements(self):
        return [], fresh()


@pytest.mark.asyncio
async def test_disruptions_are_sorted_with_active_and_window_fields():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        operator="eshot", today="2026-10-28", limit=10
    )
    assert envelope["ok"] is True
    # Active first, then most recently published (41 was published 2026-10-22).
    assert [row["line"] for row in envelope["data"]][:2] == ["41", "32"]
    assert envelope["data"][0]["active"] is True
    assert envelope["data"][2]["active"] is False


@pytest.mark.asyncio
async def test_disruptions_filters_by_line():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        operator="eshot", line="32", today="2026-10-28", limit=10
    )
    assert [row["line"] for row in envelope["data"]] == ["32"]


@pytest.mark.asyncio
async def test_disruptions_active_only_drops_expired_rows():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        operator="eshot", today="2026-10-28", active_only=True, limit=10
    )
    assert {row["line"] for row in envelope["data"]} == {"32", "41"}
    assert all(row["active"] for row in envelope["data"])


@pytest.mark.asyncio
async def test_disruptions_warn_that_notices_are_announcements_not_live_delays():
    envelope = await DisruptionService(settings=get_settings(), api=FakeApi()).list(
        operator="eshot", today="2026-10-28", limit=2
    )
    joined = " ".join(envelope["warnings"]).lower()
    assert "duyuru" in joined
    assert "canlı" in joined


# --- çok operatör ---------------------------------------------------------


class FakeOperatorApi(FakeApi):
    """Same contract as BusNoticeConnector, plus the other operators."""

    def __init__(self, *, failing: set[str] | None = None, empty: set[str] | None = None):
        self.failing = failing or set()
        self.empty = empty or set()

    async def bus_notices(self):
        if "eshot" in self.failing:
            raise RuntimeError("boom")
        return await super().bus_notices()

    async def metro_announcements(self):
        if "metro" in self.failing:
            raise RuntimeError("boom")
        if "metro" in self.empty:
            return [], fresh()
        return (
            [
                {
                    "id": "m1",
                    "title": "Metro sefer düzenlemesi",
                    "summary": "21:00 sonrası sefer aralığı değişti",
                    "published_at": "2026-10-27T10:00:00",
                    "url": None,
                },
            ],
            fresh("2026-10-27T10:00:00"),
        )

    async def ferry_announcements(self):
        if "ferry" in self.failing:
            raise RuntimeError("boom")
        if "ferry" in self.empty:
            return [], fresh()
        return (
            [
                {
                    "id": "f1",
                    "title": "Bergama Vapuru turları başladı",
                    "summary": "Rehberli körfez turu",
                    "published_at": "2026-10-20",
                    "url": None,
                },
            ],
            fresh("2026-10-20"),
        )


@pytest.mark.asyncio
async def test_operator_filter_returns_only_requested_operator():
    envelope = await DisruptionService(
        settings=get_settings(),
        api=FakeOperatorApi(),
        operators=FakeOperatorApi(),
    ).list(operator="metro", today="2026-10-28", limit=10)
    assert envelope["ok"] is True
    assert {row["operator"] for row in envelope["data"]} == {"metro"}
    assert envelope["data"][0]["title"] == "Metro sefer düzenlemesi"


@pytest.mark.asyncio
async def test_all_operators_are_merged_and_each_carries_a_source():
    fake = FakeOperatorApi()
    envelope = await DisruptionService(settings=get_settings(), api=fake, operators=fake).list(
        today="2026-10-28", limit=20
    )
    assert {row["operator"] for row in envelope["data"]} >= {"eshot", "metro", "izdeniz"}
    source_names = {source["name"] for source in envelope["sources"]}
    assert len(source_names) >= 3


@pytest.mark.asyncio
async def test_unreachable_operator_is_reported_as_unavailable_not_healthy():
    fake = FakeOperatorApi(failing={"metro"})
    envelope = await DisruptionService(settings=get_settings(), api=fake, operators=fake).list(
        today="2026-10-28", limit=20
    )
    assert envelope["ok"] is True
    joined = " ".join(envelope["warnings"]).lower()
    assert "metro" in joined
    assert "unavailable" in joined or "okunamadı" in joined
    assert {row["operator"] for row in envelope["data"]} == {"eshot", "izdeniz"}


@pytest.mark.asyncio
async def test_empty_operator_list_is_not_an_all_clear():
    fake = FakeOperatorApi(empty={"metro"})
    envelope = await DisruptionService(settings=get_settings(), api=fake, operators=fake).list(
        operator="metro", today="2026-10-28", limit=10
    )
    assert envelope["ok"] is True
    assert envelope["data"] == []
    joined = " ".join(envelope["warnings"]).lower()
    assert "duyuru yok" in joined or "kanıtı değildir" in joined


@pytest.mark.asyncio
async def test_all_operators_failing_returns_source_unavailable():
    fake = FakeOperatorApi(failing={"metro", "ferry", "eshot"})
    envelope = await DisruptionService(settings=get_settings(), api=fake, operators=fake).list(
        today="2026-10-28", limit=10
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_unknown_operator_is_rejected():
    from app.core.validation import InputValidationError as _IVE

    with pytest.raises(_IVE) as excinfo:
        await DisruptionService(settings=get_settings(), api=FakeOperatorApi(), operators=FakeOperatorApi()).list(
            operator="tramvay", today="2026-10-28", limit=5
        )
    assert excinfo.value.field == "operator"


@pytest.mark.asyncio
async def test_shuttle_variant_is_documented_as_unavailable():
    """İZBAN has no reachable announcement feed; ask it explicitly and get honesty."""
    envelope = await DisruptionService(
        settings=get_settings(), api=FakeOperatorApi(), operators=FakeOperatorApi()
    ).list(operator="izban", today="2026-10-28", limit=5)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    from app.core.geo import normalize_name

    assert "izban" in normalize_name(envelope["warnings"][0])
