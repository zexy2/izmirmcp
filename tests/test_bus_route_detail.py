from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.connectors.http import SourceTimeoutError
from app.core.settings import Settings
from app.core.validation import InputValidationError
from app.services.bus import BusService
from app.storage.gtfs_schedule import GtfsScheduleStore
from tests.conftest import fresh

FUTURE_CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\r\n"
    "WK,1,1,1,1,1,0,0,20260801,20271231\r\n"
)
EXPIRED_CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\r\n"
    "WK,1,1,1,1,1,0,0,20260801,20261009\r\n"
)
ROUTES = (
    "route_id,route_short_name,route_long_name,route_type\r\n304,304,BUCA - KONAK,3\r\n305,305,BAYRAKLI - KONAK,3\r\n"
)
AMBIGUOUS_ROUTES = ROUTES + "999,304,AMBIGUOUS - KONAK,3\r\n"
TRIPS = "route_id,service_id,trip_id,direction_id\r\n304,WK,T10,0\r\n304,WK,T11,0\r\n304,WK,T20,1\r\n305,WK,T30,0\r\n"
STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon\r\n"
    "S1,Birinci Durak,38.4200,27.1300\r\n"
    "S2,İkinci Durak,38.4210,27.1310\r\n"
    "S3,Üçüncü Durak,38.4220,27.1320\r\n"
    "S4,Dördüncü Durak,38.4230,27.1330\r\n"
)
STOP_TIMES = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence\r\n"
    "T10,08:00:00,08:00:00,S1,1\r\n"
    "T10,08:05:00,08:05:00,S2,2\r\n"
    "T10,08:10:00,08:10:00,S3,3\r\n"
    "T10,08:05:00,08:05:00,S2,4\r\n"
    "T11,09:00:00,09:00:00,S1,1\r\n"
    "T11,09:05:00,09:05:00,S3,2\r\n"
    "T11,09:10:00,09:10:00,S2,3\r\n"
    "T20,08:30:00,08:30:00,S3,1\r\n"
    "T20,08:35:00,08:35:00,S2,2\r\n"
    "T20,08:40:00,08:40:00,S1,3\r\n"
    "T30,08:00:00,08:00:00,S4,1\r\n"
)


def archive(
    *,
    routes: str = ROUTES,
    calendar: str = FUTURE_CALENDAR,
    stop_times: str = STOP_TIMES,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("calendar.txt", calendar)
        zf.writestr("routes.txt", routes)
        zf.writestr("trips.txt", TRIPS)
        zf.writestr("stops.txt", STOPS)
        zf.writestr("stop_times.txt", stop_times)
    return buffer.getvalue()


class FakeApi:
    def __init__(self, payload: bytes | None = None, *, error: Exception | None = None):
        self.payload = payload if payload is not None else archive()
        self.error = error

    async def gtfs_archive(self):
        if self.error is not None:
            raise self.error
        return self.payload


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        database_path=str(tmp_path / "izmir_mcp.sqlite3"),
        gtfs_database_path=str(tmp_path / "izmir_mcp_gtfs.sqlite3"),
        eshot_gtfs_cache_ttl_seconds=86_400,
        eshot_gtfs_stale_if_error_seconds=604_800,
    )


def test_find_routes_is_exact_and_not_substring_based(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(archive(), source_url="https://example.invalid/gtfs.zip")

    assert [row["route_id"] for row in store.find_routes("304")] == ["304"]
    assert store.find_routes("30") == []


def test_route_detail_orders_by_stop_sequence_and_preserves_duplicate_stops(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(archive(), source_url="https://example.invalid/gtfs.zip")

    detail = store.route_detail("304")
    direction_zero = next(row for row in detail["directions"] if row["direction_id"] == "0")
    loop = next(
        pattern
        for pattern in direction_zero["patterns"]
        if [stop["stop_id"] for stop in pattern["stops"]] == ["S1", "S2", "S3", "S2"]
    )

    assert loop["stop_count"] == 4
    assert [stop["stop_sequence"] for stop in loop["stops"]] == [1, 2, 3, 4]
    assert [stop["stop_name"] for stop in loop["stops"]] == [
        "Birinci Durak",
        "İkinci Durak",
        "Üçüncü Durak",
        "İkinci Durak",
    ]


def test_route_detail_keeps_variants_separate_and_counts_trips(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(archive(), source_url="https://example.invalid/gtfs.zip")

    detail = store.route_detail("304")
    zero = next(row for row in detail["directions"] if row["direction_id"] == "0")
    one = next(row for row in detail["directions"] if row["direction_id"] == "1")

    assert zero["trip_count"] == 2
    assert zero["pattern_count"] == 2
    assert {pattern["trip_count"] for pattern in zero["patterns"]} == {1}
    assert one["trip_count"] == 1
    assert [stop["stop_id"] for stop in one["patterns"][0]["stops"]] == ["S3", "S2", "S1"]
    assert detail["line"] == "304"
    assert detail["route_long_name"] == "BUCA - KONAK"


@pytest.mark.asyncio
async def test_service_detail_returns_both_directions_and_filters_one(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=FakeApi())

    both = await service.routes(query="304", detail=True, limit=5)
    assert both["ok"] is True
    route = both["data"][0]
    assert route["route_id"] == "304"
    assert [direction["direction_id"] for direction in route["directions"]] == ["0", "1"]

    only_one = await service.routes(query="304", detail=True, direction="1", limit=5)
    assert [direction["direction_id"] for direction in only_one["data"][0]["directions"]] == ["1"]
    # The summary must count the direction actually shown, not the line total.
    assert "1 yayımlanmış sefer" in only_one["summary"]
    assert "3 yayımlanmış sefer" in both["summary"]


@pytest.mark.asyncio
async def test_service_detail_requires_exact_query_and_known_direction(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=FakeApi())

    with pytest.raises(InputValidationError) as missing:
        await service.routes(detail=True)
    assert missing.value.field == "query"

    with pytest.raises(InputValidationError) as unknown:
        await service.routes(query="999", detail=True)
    assert unknown.value.field == "query"

    with pytest.raises(InputValidationError) as direction:
        await service.routes(query="304", detail=True, direction="9")
    assert direction.value.field == "direction"


@pytest.mark.asyncio
async def test_service_detail_rejects_ambiguous_short_name(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=FakeApi(payload=archive(routes=AMBIGUOUS_ROUTES)))

    with pytest.raises(InputValidationError) as excinfo:
        await service.routes(query="304", detail=True)
    assert excinfo.value.field == "query"
    assert "999" in str(excinfo.value) or "multiple" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_service_detail_keeps_stale_calendar_honest(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=FakeApi(payload=archive(calendar=EXPIRED_CALENDAR)))

    envelope = await service.routes(query="304", detail=True)
    assert envelope["ok"] is True
    assert envelope["freshness"]["status"] == "stale"
    assert envelope["limits"] and any("2026-10-09" in limit for limit in envelope["limits"])
    assert any("2026-10-09" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_service_detail_returns_source_error_when_build_fails(tmp_path):
    service = BusService(
        settings=settings_for(tmp_path),
        api=FakeApi(error=SourceTimeoutError("source request timed out")),
    )

    envelope = await service.routes(query="304", detail=True)

    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_timeout"
    assert envelope["data"] == []
