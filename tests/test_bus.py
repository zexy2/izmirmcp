from __future__ import annotations

import pytest

from app.connectors.eshot import parse_gtfs_calendar, parse_gtfs_metadata
from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.bus import BusService
from tests.conftest import fresh

STOP_ROWS = [
    {"id": "10030", "name": "Konak", "lat": 38.416218, "lon": 27.126321,
     "routes": ["303", "304"]},
    {"id": "21050", "name": "Münevver Öğretmen Ortaokulu", "lat": 38.512338,
     "lon": 27.051353, "routes": ["346", "446", "810", "816"]},
    {"id": "820001", "name": "Teknofest Alanı", "lat": 38.499314,
     "lon": 27.022115, "routes": []},
]

ARRIVALS = [
    {"bus_id": 12536, "line": "303", "line_name": "BUCA HEYKEL - KONAK",
     "direction": 1, "stops_remaining": 2, "lat": 38.40078, "lon": 27.149745,
     "wheelchair_accessible": True, "bike_rack": False},
]

GTFS_ROUTE = {
    "route_id": "303",
    "short_name": "303",
    "long_name": "BUCA HEYKEL - KONAK",
    "route_type": 3,
    "service_ids": ["3633"],
    "trips": 41,
}

GTFS_CALENDAR = [
    {"service_id": "3633", "monday": True, "tuesday": True, "wednesday": True,
     "thursday": True, "friday": True, "saturday": False, "sunday": False,
     "start_date": "2026-08-05", "end_date": "2026-10-05"},
]


class FakeApi:
    async def stops(self):
        return STOP_ROWS, fresh()

    async def arrivals(self, stop_id):
        return (list(ARRIVALS) if stop_id == "10030" else []), fresh()

    async def gtfs(self):
        return {"routes": [GTFS_ROUTE], "calendar": GTFS_CALENDAR,
                "calendar_end": "2026-10-05"}, fresh()


@pytest.mark.asyncio
async def test_stop_search_filters_by_name_and_reports_total():
    envelope = await BusService(settings=get_settings(), api=FakeApi()).stops(
        query="konak", limit=10
    )
    assert envelope["ok"] is True
    assert [row["id"] for row in envelope["data"]] == ["10030"]
    assert envelope["result_info"]["matched"] == 1


@pytest.mark.asyncio
async def test_stop_search_requires_query_or_coordinates():
    with pytest.raises(InputValidationError):
        await BusService(settings=get_settings(), api=FakeApi()).stops(limit=5)


@pytest.mark.asyncio
async def test_stop_search_rejects_both_query_and_coordinates():
    with pytest.raises(InputValidationError):
        await BusService(settings=get_settings(), api=FakeApi()).stops(
            query="konak", lat=38.4, lon=27.1
        )


@pytest.mark.asyncio
async def test_nearby_stops_are_sorted_and_radius_limited():
    envelope = await BusService(settings=get_settings(), api=FakeApi()).stops(
        lat=38.4162, lon=27.1263, radius_m=1000, limit=10
    )
    assert envelope["ok"] is True
    assert [row["id"] for row in envelope["data"]] == ["10030"]
    assert envelope["data"][0]["distance_m"] < 10


@pytest.mark.asyncio
async def test_unknown_stop_id_raises_lookup_error_with_candidates():
    with pytest.raises(InputValidationError) as excinfo:
        await BusService(settings=get_settings(), api=FakeApi()).arrivals(stop_id="99999999")
    assert excinfo.value.field == "stop_id"


@pytest.mark.asyncio
async def test_arrivals_map_source_fields_and_warn_about_etas():
    envelope = await BusService(settings=get_settings(), api=FakeApi()).arrivals(stop_id="10030")
    assert envelope["ok"] is True
    row = envelope["data"][0]
    assert row["line"] == "303"
    assert row["stops_remaining"] == 2
    assert row["lat"] == 38.40078
    assert row["maps_url"].startswith("https://www.google.com/maps?q=")
    joined = " ".join(envelope["warnings"]).lower()
    assert "eta" in joined or "dakika" in joined


@pytest.mark.asyncio
async def test_arrivals_empty_payload_is_a_warning_not_a_false_all_clear():
    class EmptyApi(FakeApi):
        async def arrivals(self, stop_id):
            return [], fresh()

    envelope = await BusService(settings=get_settings(), api=EmptyApi()).arrivals(stop_id="10030")
    assert envelope["ok"] is True
    assert envelope["data"] == []
    joined = " ".join(envelope["warnings"]).lower()
    assert "yaklaşan otobüs döndürmedi" in joined
    assert "kanıtı değildir" in joined


@pytest.mark.asyncio
async def test_routes_expose_gtfs_calendar_window_and_staleness_warning():
    envelope = await BusService(settings=get_settings(), api=FakeApi()).routes(query="303")
    assert envelope["ok"] is True
    row = envelope["data"][0]
    assert row["route_id"] == "303"
    assert row["calendar_end"] == "2026-10-05"
    assert any("takvim" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_parse_gtfs_calendar_converts_flags_and_dates():
    text = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\n"
        "3633,1,1,1,1,1,0,0,20260805,20261005\n"
    )
    rows = parse_gtfs_calendar(text)
    assert rows[0]["monday"] is True
    assert rows[0]["sunday"] is False
    assert rows[0]["start_date"] == "2026-08-05"
    assert rows[0]["end_date"] == "2026-10-05"


def test_parse_gtfs_metadata_groups_routes_and_feed_window():
    routes = (
        "route_id,route_short_name,route_long_name,route_type\n"
        "303,303,BUCA HEYKEL - KONAK,3\n"
        "5,5,NARLIDERE - ÜÇKUYULAR İSKELE,3\n"
    )
    trips = (
        "route_id,service_id,trip_id,direction_id\n"
        "303,3633,t1,0\n"
        "303,3633,t2,1\n"
    )
    calendar = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\n"
        "3633,1,1,1,1,1,0,0,20260805,20261005\n"
    )
    result = parse_gtfs_metadata(routes=routes, trips=trips, calendar=calendar)
    assert len(result["routes"]) == 2
    route = next(row for row in result["routes"] if row["route_id"] == "303")
    assert route["trips"] == 2
    assert route["service_ids"] == ["3633"]
    assert result["calendar_end"] == "2026-10-05"


class BrokenGtfsApi(FakeApi):
    async def gtfs(self):
        from app.connectors.http import SourceError

        raise SourceError("source did not return a ZIP archive")


class RateLimitedApi(FakeApi):
    async def arrivals(self, stop_id):
        from app.connectors.http import SourceRateLimitedError

        raise SourceRateLimitedError("source rate limit exceeded")


@pytest.mark.asyncio
async def test_dead_gtfs_source_returns_source_unavailable_not_a_raise():
    envelope = await BusService(settings=get_settings(), api=BrokenGtfsApi()).routes(query="446")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert envelope["data"] == []
    assert envelope["freshness"]["status"] == "broken"


@pytest.mark.asyncio
async def test_rate_limited_arrivals_return_source_rate_limited():
    envelope = await BusService(settings=get_settings(), api=RateLimitedApi()).arrivals(
        stop_id="10030"
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_rate_limited"
    assert envelope["error"]["temporary"] is True
