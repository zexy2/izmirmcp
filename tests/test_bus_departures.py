from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.connectors.http import SourceError, SourceTimeoutError
from app.core.settings import Settings, get_settings
from app.core.validation import InputValidationError
from app.services.bus import BusService
from app.storage.gtfs_schedule import (
    GtfsScheduleError,
    GtfsScheduleStore,
    active_service_ids,
    parse_gtfs_time,
)
from tests.conftest import fresh

ISTANBUL = ZoneInfo("Europe/Istanbul")

CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\r\n"
    "WK,1,1,1,1,1,0,0,20260801,20261009\r\n"
    "SAT,0,0,0,0,0,1,0,20260801,20261009\r\n"
)
CALENDAR_DATES = (
    "service_id,date,exception_type\r\n"
    "WK,20261007,2\r\n"
    "SAT,20261007,1\r\n"
)
FUTURE_CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\r\n"
    "WK,1,1,1,1,1,0,0,20260801,20271231\r\n"
    "SAT,0,0,0,0,0,1,0,20260801,20271231\r\n"
)
ROUTES = (
    "route_id,route_short_name,route_long_name,route_type\r\n"
    "446,446,ÇAMDİBİ - KONAK,3\r\n"
    "303,303,BUCA HEYKEL - KONAK,3\r\n"
)
TRIPS = (
    "route_id,service_id,trip_id,direction_id\r\n"
    "446,WK,T1,0\r\n"
    "303,WK,T2,1\r\n"
    "446,WK,T3,0\r\n"
    "446,WK,T4,0\r\n"
    "303,SAT,T5,0\r\n"
)
STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon\r\n"
    "10030,Konak,38.41872,27.12827\r\n"
    "21050,Münevver Öğretmen Ortaokulu,38.512338,27.051353\r\n"
)
STOP_TIMES = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\r\n"
    "T1,08:10:00,08:10:00,10030,3,0\r\n"
    "T2,09:00:00,09:00:00,10030,5,0\r\n"
    "T3,25:10:00,25:10:00,10030,3,0\r\n"
    "T4,08:20:00,08:20:00,10030,4,1\r\n"
    "T5,10:00:00,10:00:00,10030,1,0\r\n"
)
# Konak and Gazi Bulvarı are ~200 m apart; 21050 is ~11 km north and must not
# leak into a 500 m radius answer.
NEAR_STOPS = STOPS + "10040,Gazi Bulvarı,38.4180,27.1250\r\n"
NEAR_TRIPS = TRIPS + "446,WK,T6,0\r\n"
NEAR_STOP_TIMES = STOP_TIMES + "T6,08:15:00,08:15:00,10040,2,0\r\n"

STOP_ROWS = [
    {"id": "10030", "name": "Konak", "lat": 38.416218, "lon": 27.126321,
     "routes": ["303", "446"]},
]
NEAR_STOP_ROWS = [
    *STOP_ROWS,
    {"id": "10040", "name": "Gazi Bulvarı", "lat": 38.4180, "lon": 27.1250,
     "routes": ["446"]},
    {"id": "21050", "name": "Münevver Öğretmen Ortaokulu", "lat": 38.512338,
     "lon": 27.051353, "routes": ["303"]},
]


def gtfs_zip(
    *,
    calendar: str = CALENDAR,
    calendar_dates: str | None = CALENDAR_DATES,
    stops: str = STOPS,
    trips: str = TRIPS,
    stop_times: str = STOP_TIMES,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("calendar.txt", calendar)
        if calendar_dates is not None:
            archive.writestr("calendar_dates.txt", calendar_dates)
        archive.writestr("routes.txt", ROUTES)
        archive.writestr("trips.txt", trips)
        archive.writestr("stops.txt", stops)
        archive.writestr("stop_times.txt", stop_times)
    return buffer.getvalue()


class FakeApi:
    def __init__(self, archive: bytes | None = None, *, error: Exception | None = None):
        self.archive = archive if archive is not None else gtfs_zip()
        self.error = error
        self.archive_calls = 0

    async def stops(self):
        return STOP_ROWS, fresh()

    async def gtfs_archive(self):
        self.archive_calls += 1
        if self.error is not None:
            raise self.error
        return self.archive


def settings_for(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_path": str(tmp_path / "izmir_mcp.sqlite3"),
        "gtfs_database_path": str(tmp_path / "izmir_mcp_gtfs.sqlite3"),
        "eshot_gtfs_cache_ttl_seconds": 86_400,
        "eshot_gtfs_stale_if_error_seconds": 604_800,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("08:10:00", 29_400), ("25:10:00", 90_600), ("00:00:00", 0), ("7:05", 25_500)],
)
def test_parse_gtfs_time_accepts_published_and_after_midnight_values(text, expected):
    assert parse_gtfs_time(text) == expected


@pytest.mark.parametrize("text", ["", "aa:bb", "08:70:00", "08:10:99", "-1:00:00", None])
def test_parse_gtfs_time_rejects_invalid_values(text):
    assert parse_gtfs_time(text) is None


def test_active_service_ids_applies_weekday_window_and_exceptions():
    calendar = [
        {"service_id": "WK", "monday": 1, "tuesday": 1, "wednesday": 1,
         "thursday": 1, "friday": 1, "saturday": 0, "sunday": 0,
         "start_date": "20260801", "end_date": "20261009"},
        {"service_id": "OLD", "monday": 1, "tuesday": 1, "wednesday": 1,
         "thursday": 1, "friday": 1, "saturday": 0, "sunday": 0,
         "start_date": "20250101", "end_date": "20251009"},
    ]
    exceptions = [
        {"service_id": "WK", "date": "20261007", "exception_type": 2},
        {"service_id": "SAT", "date": "20261007", "exception_type": 1},
    ]
    active = active_service_ids(calendar, exceptions, datetime(2026, 10, 7).date())
    assert active == {"SAT"}
    assert active_service_ids(calendar, [], datetime(2026, 10, 12).date()) == set()


def test_store_build_swaps_in_a_queryable_database(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    meta = store.rebuild(gtfs_zip(), source_url="https://example.invalid/gtfs.zip")

    assert meta["calendar_end"] == "2026-10-09"
    assert meta["stop_times_rows"] == 5
    assert meta["skipped_stop_times"] == 0
    assert store.metadata()["stop_times_rows"] == 5


def test_failed_rebuild_keeps_the_previous_database(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(gtfs_zip(), source_url="https://example.invalid/gtfs.zip")
    before = store.metadata()

    with pytest.raises(GtfsScheduleError):
        store.rebuild(b"PK\x03\x04broken", source_url="https://example.invalid/gtfs.zip")

    after = store.metadata()
    assert after is not None
    assert after["built_at"] == before["built_at"]
    assert after["stop_times_rows"] == 5


def test_store_handles_a_feed_without_calendar_dates(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    meta = store.rebuild(
        gtfs_zip(calendar_dates=None), source_url="https://example.invalid/gtfs.zip"
    )
    assert meta["calendar_dates_rows"] == 0
    rows = store.departures(
        stop_id="10030",
        at=datetime(2026, 10, 7, 8, 0, tzinfo=ISTANBUL),
        limit=10,
    )
    assert [row["line"] for row in rows] == ["446", "303", "446"]


def test_departures_are_future_only_sorted_and_exclude_no_pickup(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(gtfs_zip(), source_url="https://example.invalid/gtfs.zip")

    rows = store.departures(
        stop_id="10030",
        at=datetime(2026, 10, 5, 8, 0, tzinfo=ISTANBUL),
        limit=10,
    )

    assert [row["line"] for row in rows] == ["446", "303", "446"]
    assert [row["time"] for row in rows] == ["08:10", "09:00", "01:10"]
    assert rows[0]["scheduled_at"].startswith("2026-10-05T08:10")
    assert rows[2]["scheduled_at"].startswith("2026-10-06T01:10")
    assert all(row["realtime"] is False for row in rows)


def test_previous_service_day_after_midnight_times_are_included(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(
        gtfs_zip(calendar_dates="service_id,date,exception_type\r\nWK,20261007,2\r\n"),
        source_url="https://example.invalid/gtfs.zip",
    )

    rows = store.departures(
        stop_id="10030",
        at=datetime(2026, 10, 7, 0, 30, tzinfo=ISTANBUL),
        limit=10,
    )

    assert [row["trip_id"] for row in rows] == ["T3"]
    assert rows[0]["time"] == "01:10"
    assert rows[0]["service_date"] == "2026-10-06"


def test_exception_removal_empties_the_day_and_addition_adds_saturday_service(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(
        gtfs_zip(
            calendar_dates="service_id,date,exception_type\r\nWK,20261007,2\r\n"
        ),
        source_url="https://example.invalid/gtfs.zip",
    )

    removed = store.departures(
        stop_id="10030",
        at=datetime(2026, 10, 7, 8, 0, tzinfo=ISTANBUL),
        limit=10,
    )
    assert removed == []

    store.rebuild(gtfs_zip(), source_url="https://example.invalid/gtfs.zip")
    added = store.departures(
        stop_id="10030",
        at=datetime(2026, 10, 7, 9, 30, tzinfo=ISTANBUL),
        limit=10,
    )
    assert [row["line"] for row in added] == ["303"]


def test_line_filter_matches_route_short_name_case_insensitively(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(gtfs_zip(), source_url="https://example.invalid/gtfs.zip")

    rows = store.departures(
        stop_id="10030",
        at=datetime(2026, 10, 5, 8, 0, tzinfo=ISTANBUL),
        limit=10,
        line="303",
    )

    assert [row["line"] for row in rows] == ["303"]


@pytest.mark.asyncio
async def test_service_returns_departures_with_stop_and_calendar_context(tmp_path):
    service = BusService(
        settings=settings_for(tmp_path), api=FakeApi(gtfs_zip(calendar=FUTURE_CALENDAR))
    )

    envelope = await service.departures(
        stop_id="10030", at="2026-10-05T08:00", limit=5
    )

    assert envelope["ok"] is True
    assert envelope["data"][0]["line"] == "446"
    assert envelope["data"][0]["stop_name"] == "Konak"
    assert envelope["sources"][0]["name"].startswith("EShot GTFS")
    assert "calendar_end=2027-12-31" in envelope["limits"]
    assert envelope["freshness"]["status"] == "fresh"


@pytest.mark.asyncio
async def test_service_reports_expired_calendar_instead_of_claiming_no_bus(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=FakeApi())

    envelope = await service.departures(
        stop_id="10030", at="2026-10-28T08:00", limit=5
    )

    assert envelope["ok"] is True
    assert envelope["data"] == []
    joined = " ".join(envelope["warnings"]).lower()
    assert "2026-10-09" in joined
    assert "servis tanımlamıyor" in joined or "takvim" in joined
    assert envelope["freshness"]["status"] == "stale"


@pytest.mark.asyncio
async def test_service_reuses_the_local_database_within_ttl(tmp_path):
    api = FakeApi()
    service = BusService(settings=settings_for(tmp_path), api=api)

    await service.departures(stop_id="10030", at="2026-10-05T08:00", limit=5)
    await service.departures(stop_id="10030", at="2026-10-05T09:00", limit=5)

    assert api.archive_calls == 1


@pytest.mark.asyncio
async def test_service_uses_bounded_stale_database_when_download_fails(tmp_path):
    api = FakeApi(gtfs_zip(calendar=FUTURE_CALENDAR))
    service = BusService(
        settings=settings_for(
            tmp_path,
            eshot_gtfs_cache_ttl_seconds=0,
            eshot_gtfs_stale_if_error_seconds=86_400,
        ),
        api=api,
    )
    first = await service.departures(stop_id="10030", at="2026-10-05T08:00", limit=5)
    assert first["freshness"]["status"] == "fresh"

    api.error = SourceTimeoutError("source request timed out")
    second = await service.departures(stop_id="10030", at="2026-10-05T09:00", limit=5)

    assert second["ok"] is True
    assert second["freshness"]["status"] == "stale"
    assert any("yenilenemedi" in warning.lower() for warning in second["warnings"])


@pytest.mark.asyncio
async def test_service_returns_source_error_when_no_database_can_be_built(tmp_path):
    service = BusService(
        settings=settings_for(tmp_path, eshot_gtfs_cache_ttl_seconds=0),
        api=FakeApi(error=SourceTimeoutError("source request timed out")),
    )

    envelope = await service.departures(stop_id="10030", at="2026-10-05T08:00", limit=5)

    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_timeout"
    assert envelope["data"] == []


@pytest.mark.asyncio
async def test_service_rejects_published_stop_missing_from_the_gtfs_timetable(tmp_path):
    class PublishedOnlyStopApi(FakeApi):
        async def stops(self):
            return [
                *STOP_ROWS,
                {"id": "99999", "name": "Eski Durak", "lat": 38.4, "lon": 27.1,
                 "routes": []},
            ], fresh()

    with pytest.raises(InputValidationError) as excinfo:
        await BusService(settings=settings_for(tmp_path), api=PublishedOnlyStopApi()).departures(
            stop_id="99999", at="2026-10-05T08:00", limit=5
        )
    assert excinfo.value.field == "stop_id"


@pytest.mark.asyncio
async def test_service_rejects_unknown_stop_without_inventing_departures(tmp_path):
    with pytest.raises(InputValidationError) as excinfo:
        await BusService(settings=settings_for(tmp_path), api=FakeApi()).departures(
            stop_id="99999999", at="2026-10-05T08:00", limit=5
        )
    assert excinfo.value.field == "stop_id"


@pytest.mark.asyncio
async def test_service_rejects_invalid_at_value(tmp_path):
    with pytest.raises(InputValidationError) as excinfo:
        await BusService(settings=settings_for(tmp_path), api=FakeApi()).departures(
            stop_id="10030", at="sabah", limit=5
        )
    assert excinfo.value.field == "at"


@pytest.mark.asyncio
async def test_service_marks_truncated_results(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=FakeApi())

    envelope = await service.departures(stop_id="10030", at="2026-10-05T08:00", limit=1)

    assert len(envelope["data"]) == 1
    assert envelope["result_info"]["truncated"] is True


# --- nearby stops and name discovery ---------------------------------------


def test_store_merges_departures_for_several_stops_in_time_order(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(
        gtfs_zip(stops=NEAR_STOPS, trips=NEAR_TRIPS, stop_times=NEAR_STOP_TIMES),
        source_url="https://example.invalid/gtfs.zip",
    )

    rows = store.departures_at_stops(
        stop_ids=["10040", "10030"],
        at=datetime(2026, 10, 5, 8, 0, tzinfo=ISTANBUL),
        limit=10,
    )

    # T3 (25:10) rolls to the next day and must sort last, not first.
    assert [row["stop_id"] for row in rows[:2]] == ["10030", "10040"]
    assert [row["time"] for row in rows[:2]] == ["08:10", "08:15"]
    assert [row["stop_name"] for row in rows[:2]] == ["Konak", "Gazi Bulvarı"]
    assert [row["minutes_from_now"] for row in rows[:2]] == [10.0, 15.0]
    assert [row["scheduled_at"] for row in rows] == sorted(
        row["scheduled_at"] for row in rows
    )


def test_store_rejects_an_empty_stop_list(tmp_path):
    store = GtfsScheduleStore(tmp_path / "schedule.sqlite3")
    store.rebuild(gtfs_zip(), source_url="https://example.invalid/gtfs.zip")

    with pytest.raises(GtfsScheduleError):
        store.departures_at_stops(
            stop_ids=[], at=datetime(2026, 10, 5, 8, 0, tzinfo=ISTANBUL), limit=5
        )


class NearApi(FakeApi):
    """Published stop list with two nearby stops and one far stop."""

    async def stops(self):
        return NEAR_STOP_ROWS, fresh()


class NearTimetableApi(NearApi):
    def __init__(self):
        super().__init__(
            gtfs_zip(stops=NEAR_STOPS, trips=NEAR_TRIPS, stop_times=NEAR_STOP_TIMES)
        )


@pytest.mark.asyncio
async def test_stop_query_returns_stop_candidates_not_departures(tmp_path):
    api = NearApi()
    envelope = await BusService(settings=settings_for(tmp_path), api=api).departures(
        stop_query="gazi", limit=5
    )

    assert envelope["ok"] is True
    assert [row["id"] for row in envelope["data"]] == ["10040"]
    assert envelope["data"][0]["match"] == "exact"
    assert envelope["result_info"]["scope"] == "stop_candidates"
    assert any(limit.startswith("mode=stop_query") for limit in envelope["limits"])
    warning_text = " ".join(envelope["warnings"]).lower()
    assert "kalkış" in warning_text and "değil" in warning_text
    # Discovery must not download or build a 2M-row timetable.
    assert api.archive_calls == 0


@pytest.mark.asyncio
async def test_stop_query_ranks_an_exact_name_before_a_longer_one(tmp_path):
    class NameApi(NearApi):
        async def stops(self):
            return [
                {"id": "52047", "name": "Güzel Konak", "lat": 38.4, "lon": 27.1,
                 "routes": []},
                {"id": "10030", "name": "Konak", "lat": 38.416218,
                 "lon": 27.126321, "routes": ["446"]},
                {"id": "10031", "name": "Konak İskele", "lat": 38.42, "lon": 27.13,
                 "routes": []},
            ], fresh()

    envelope = await BusService(settings=settings_for(tmp_path), api=NameApi()).departures(
        stop_query="Konak", limit=3
    )

    assert [row["id"] for row in envelope["data"]] == ["10030", "10031", "52047"]


@pytest.mark.asyncio
async def test_stop_query_fuzzy_matches_are_labelled(tmp_path):
    envelope = await BusService(settings=settings_for(tmp_path), api=NearApi()).departures(
        stop_query="Konakk", limit=5
    )

    assert envelope["ok"] is True
    assert envelope["data"][0]["match"] == "fuzzy"
    assert any("fuzzy" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_radius_mode_merges_departures_from_nearby_stops(tmp_path):
    envelope = await BusService(
        settings=settings_for(tmp_path), api=NearTimetableApi()
    ).departures(lat=38.4169, lon=27.1260, radius_m=500, at="2026-10-05T08:00", limit=5)

    assert envelope["ok"] is True
    assert [row["stop_id"] for row in envelope["data"][:2]] == ["10030", "10040"]
    assert [row["time"] for row in envelope["data"][:2]] == ["08:10", "08:15"]
    assert all(row["distance_m"] is not None for row in envelope["data"])
    assert all(row["distance_m"] <= 500 for row in envelope["data"])
    assert "21050" not in {row["stop_id"] for row in envelope["data"]}
    assert any(limit.startswith("mode=radius") for limit in envelope["limits"])
    assert any("stop_count=" in limit for limit in envelope["limits"])


@pytest.mark.asyncio
async def test_radius_mode_without_nearby_stops_is_empty_and_builds_nothing(tmp_path):
    api = NearApi()
    envelope = await BusService(settings=settings_for(tmp_path), api=api).departures(
        lat=38.9, lon=26.9, radius_m=300, at="2026-10-05T08:00", limit=5
    )

    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert api.archive_calls == 0
    assert any("durak" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_departures_require_exactly_one_location_mode(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=NearApi())

    with pytest.raises(InputValidationError) as excinfo:
        await service.departures(stop_id="10030", lat=38.4, lon=27.1)
    assert excinfo.value.field == "stop_id"

    with pytest.raises(InputValidationError) as excinfo:
        await service.departures(stop_query="konak", stop_id="10030")
    assert excinfo.value.field == "stop_query"

    with pytest.raises(InputValidationError):
        await service.departures(at="2026-10-05T08:00")


@pytest.mark.asyncio
async def test_stop_query_rejects_filters_it_cannot_apply(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=NearApi())

    with pytest.raises(InputValidationError) as excinfo:
        await service.departures(stop_query="konak", line="446")
    assert excinfo.value.field == "line"

    with pytest.raises(InputValidationError) as excinfo:
        await service.departures(stop_query="konak", at="2026-10-05T08:00")
    assert excinfo.value.field == "at"


@pytest.mark.asyncio
async def test_radius_mode_validates_coordinates_and_radius(tmp_path):
    service = BusService(settings=settings_for(tmp_path), api=NearApi())

    with pytest.raises(InputValidationError) as excinfo:
        await service.departures(lat=38.4, radius_m=100)
    assert excinfo.value.field == "lat"

    with pytest.raises(InputValidationError) as excinfo:
        await service.departures(lat=38.4, lon=27.1, radius_m=99_999)
    assert excinfo.value.field == "radius_m"

    with pytest.raises(InputValidationError) as excinfo:
        await service.departures(stop_id="10030", radius_m=100)
    assert excinfo.value.field == "radius_m"
