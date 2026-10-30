"""Adversarial tests for the untested connectors and parser edges.

These probes are written against the *documented* contract (envelope, honesty
rules, no fabricated data) rather than the current implementation. A failure
here is a candidate bug to investigate, not necessarily a design choice.
"""
from __future__ import annotations

import math

import pytest

from app.connectors.city_layers import parse_coordinate, parse_market_days
from app.connectors.izmir_api import IzmirOpenApi
from app.core.settings import get_settings


class StubCache:
    """Replace the cached loader so parsers can be exercised offline."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def cached(self, path: str, key: str):
        self.calls += 1
        from app.core.source_cache import CacheInfo

        return self.payload, CacheInfo(status="fresh", retrieved_at="2026-10-28T00:00:00+00:00")


def _api(payload) -> tuple[IzmirOpenApi, StubCache]:
    api = IzmirOpenApi(get_settings())
    stub = StubCache(payload)
    api._cached = stub.cached  # type: ignore[method-assign]
    return api, stub


# --- izmir_api: parking ---------------------------------------------------


@pytest.mark.asyncio
async def test_parking_skips_rows_without_coordinates():
    api, _stub = _api(
        [
            {"ufid": "a", "name": "Ok", "lat": 38.4, "lng": 27.1},
            {"ufid": "b", "name": "NoLat", "lat": None, "lng": 27.1},
            {"ufid": "c", "name": "NoLng", "lat": 38.4, "lng": None},
            {"ufid": "d", "name": "Text", "lat": "x", "lng": "y"},
        ]
    )
    rows, _info = await api.parking()
    assert [row["id"] for row in rows] == ["a"]


@pytest.mark.asyncio
async def test_parking_does_not_trust_a_non_list_payload():
    api, _stub = _api({"unexpected": "object"})
    rows, _info = await api.parking()
    assert rows == []


@pytest.mark.asyncio
async def test_parking_capacity_requires_two_integers():
    """free+occupied is a capacity only when both are real integers."""
    api, _stub = _api(
        [
            {"ufid": "a", "name": "A", "lat": 38.4, "lng": 27.1,
             "occupancy": {"total": {"free": 3, "occupied": "40"}}},
            {"ufid": "b", "name": "B", "lat": 38.4, "lng": 27.1,
             "occupancy": {"total": {"free": 3, "occupied": 40}}},
        ]
    )
    rows, _info = await api.parking()
    by_id = {row["id"]: row for row in rows}
    assert by_id["a"]["capacity"] is None
    assert by_id["b"]["capacity"] == 43


@pytest.mark.asyncio
async def test_parking_accepts_turkish_decimal_comma():
    api, _stub = _api([{"ufid": "a", "name": "A", "lat": "38,41", "lng": "27,12"}])
    rows, _info = await api.parking()
    assert rows and rows[0]["lat"] == pytest.approx(38.41)


# --- izmir_api: pharmacies ------------------------------------------------


@pytest.mark.asyncio
async def test_pharmacy_skips_rows_without_coordinates():
    api, _stub = _api(
        [
            {"EczaneId": 1, "Adi": "A", "LokasyonX": 38.4, "LokasyonY": 27.1},
            {"EczaneId": 2, "Adi": "B", "LokasyonX": None, "LokasyonY": 27.1},
        ]
    )
    rows, _info = await api.pharmacies()
    assert [row["id"] for row in rows] == [1]


@pytest.mark.asyncio
async def test_pharmacy_sentinel_id_becomes_null():
    api, _stub = _api([{"EczaneId": -1, "Adi": "A", "LokasyonX": 38.4, "LokasyonY": 27.1}])
    rows, _info = await api.pharmacies()
    assert rows[0]["id"] is None


# --- izmir_api: air quality -----------------------------------------------


@pytest.mark.asyncio
async def test_air_quality_groups_by_station_and_keeps_latest_observation():
    api, _stub = _api(
        [
            {"BolgeAdi": "Konak", "BolgeId": 1, "OlcumTarihi": "2026-10-27T10:00:00",
             "GazAdi": "CO", "OlcumDegeri": 1.0},
            {"BolgeAdi": "Konak", "BolgeId": 1, "OlcumTarihi": "2026-10-27T12:00:00",
             "GazAdi": "NO2", "OlcumDegeri": 2.0},
        ]
    )
    rows, _info = await api.air_quality("2026-10-27")
    assert len(rows) == 1
    assert rows[0]["observed_at"] == "2026-10-27T12:00:00"
    assert len(rows[0]["readings"]) == 2


@pytest.mark.asyncio
async def test_air_quality_skips_rows_without_a_station_name():
    api, _stub = _api([{"BolgeAdi": "  ", "GazAdi": "CO", "OlcumDegeri": 1}])
    rows, _info = await api.air_quality("2026-10-27")
    assert rows == []


# --- izmir_api: stations and schedules ------------------------------------


@pytest.mark.asyncio
async def test_metro_stations_skip_invalid_coordinates():
    api, _stub = _api(
        [
            {"IstasyonId": 1, "IstasyonAdi": "A", "Enlem": 38.4, "Boylam": 27.1, "Sira": 1},
            {"IstasyonId": 2, "IstasyonAdi": "B", "Enlem": 999, "Boylam": 27.1, "Sira": 2},
        ]
    )
    rows, _info = await api.metro_stations()
    # A latitude of 999 is not a coordinate; either skip it or reject loudly.
    assert all(-90 <= row["lat"] <= 90 for row in rows)


@pytest.mark.asyncio
async def test_metro_schedule_tolerates_missing_fields():
    api, _stub = _api([{"Sira": 1}, {"Sira": 2, "Aralik": "7,5"}])
    rows, _info = await api.metro_schedule()
    assert len(rows) == 2
    assert rows[1]["interval_minutes"] == pytest.approx(7.5)


@pytest.mark.asyncio
async def test_ferry_piers_skip_invalid_coordinates():
    api, _stub = _api([{"IskeleId": 1, "Adi": "A", "Enlem": None, "Boylam": 27.1}])
    rows, _info = await api.ferry_piers()
    assert rows == []


@pytest.mark.asyncio
async def test_izban_schedule_returns_rows_even_when_fields_are_missing():
    api, _stub = _api([{"HareketIstasyonId": 1}])
    rows, _info = await api.izban_schedule(1, 2)
    assert len(rows) == 1
    assert rows[0]["departure"] is None


@pytest.mark.asyncio
async def test_izdeniz_pier_schedule_handles_missing_departure_list():
    api, _stub = _api({"gunId": 3})
    payload, _info = await api.izdeniz_pier_schedule(1, 3)
    assert payload["departures"] == []
    assert payload["day_id"] == 3


# --- city_layers: coordinate parsing --------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("38.5", 38.5),
        ("38,5", 38.5),
        (38.5, 38.5),
        (None, None),
        ("", None),
        ("nan", None),
        ("inf", None),
        (True, None),
        ("38.5.6", None),
        ("", None),
    ],
)
def test_parse_coordinate_is_strict(value, expected):
    result = parse_coordinate(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_parse_coordinate_rejects_overflow_style_strings():
    assert parse_coordinate("1e400") is None


# --- city_layers: market day parsing --------------------------------------


def test_market_days_matches_turkish_weekdays():
    assert parse_market_days("Cumartesi günü kurulmaktadır") == ["saturday"]
    assert parse_market_days("Pazar günü") == ["sunday"]


def test_market_days_does_not_match_substrings_inside_other_words():
    """'pazartesi' contains 'pazar'; a careless matcher would return both."""
    days = parse_market_days("Pazartesi günleri")
    assert days == ["monday"]


def test_market_days_reports_multiple_days_in_order():
    assert parse_market_days("Salı ve Cuma") == ["tuesday", "friday"]


def test_market_days_returns_empty_for_unparseable_text():
    assert parse_market_days("Her gün") == []
    assert parse_market_days("") == []
    assert parse_market_days(None) == []


# --- geo math -------------------------------------------------------------


def test_haversine_is_symmetric_and_zero_at_the_same_point():
    from app.core.geo import haversine_m

    assert haversine_m(38.4, 27.1, 38.4, 27.1) == 0.0
    a = haversine_m(38.4, 27.1, 38.5, 27.2)
    b = haversine_m(38.5, 27.2, 38.4, 27.1)
    assert a == pytest.approx(b, abs=0.2)


def test_haversine_antipodal_points_do_not_exceed_half_circumference():
    from app.core.geo import haversine_m

    distance = haversine_m(0.0, 0.0, 0.0, 180.0)
    assert distance <= 20_015_000 + 1_000


def test_haversine_rejects_no_input_silently():
    """Non-finite inputs would poison every downstream comparison."""
    from app.core.geo import haversine_m

    with pytest.raises((ValueError, TypeError)):
        haversine_m(math.nan, 27.1, 38.4, 27.1)


# --- per-source fixture variants: malformed, empty, duplicates, schema_drift ---

import json as _json

from app.connectors import http as _http
from app.connectors.ckan import CkanClient, CkanSchemaDriftError
from app.connectors.eshot import EshotConnector
from app.connectors.http import SourceError
from app.connectors.izsu import IzsuClient, parse_dam_csv
from app.connectors.schema import SchemaDriftError, decode_member

MALFORMED_UTF8 = b'[{"name": "\xff\xfe broken"}]'
DAM_HEADER = "BARAJ_KUYU_ID;BARAJ_KUYU_ADI;DURUM_TARIHI;DOLULUK_ORANI\n"

FIXTURES = {
    "izmir_api": {
        "malformed": MALFORMED_UTF8,
        "empty": b"[]",
        "duplicates": _json.dumps([
            {"ufid": "a", "name": "A", "lat": 38.4, "lng": 27.1},
            {"ufid": "a", "name": "A", "lat": 38.4, "lng": 27.1},
        ]).encode(),
        "schema_drift": b'"maintenance"',
    },
    "eshot": {
        "malformed": MALFORMED_UTF8,
        "empty": b"[]",
        "duplicates": _json.dumps([{"OtobusId": 1, "HatNumarasi": "5"}] * 2).encode(),
        "schema_drift": b'{"error": "moved"}',
    },
    "izsu": {
        "malformed": (DAM_HEADER + "1;Tahtal\xc4\xb1;2026-10-01;40\n").encode() + b"\xff",
        "empty": DAM_HEADER.encode(),
        "duplicates": (DAM_HEADER + "1;Tahtalı;2026-10-01;40\n" * 2).encode(),
        "schema_drift": b"ID;NAME;LEVEL\n1;Tahtali;40\n",
    },
    "ckan": {
        "malformed": b'{"success": true, "result": "\xff"}',
        "empty": b'{"success": true, "result": {"results": [], "count": 0}}',
        "duplicates": _json.dumps({"success": True, "result": {
            "results": [{"id": "x"}, {"id": "x"}], "count": 2}}).encode(),
        "schema_drift": b'["not", "an", "envelope"]',
    },
}


def _serve(monkeypatch, body: bytes):
    async def fake_get_bytes(url, **_kwargs):
        return body

    monkeypatch.setattr(_http, "_get_bytes", fake_get_bytes)


async def _call(source: str):
    settings = get_settings()
    if source == "izmir_api":
        return (await IzmirOpenApi(settings).parking())[0]
    if source == "eshot":
        return (await EshotConnector(settings=settings).arrivals("123"))[0]
    if source == "izsu":
        return (await IzsuClient(settings).dams())[0]
    return await CkanClient(settings).package_search(query="x", rows=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", sorted(FIXTURES))
async def test_malformed_utf8_is_a_source_error_not_silent_replacement(monkeypatch, source):
    _serve(monkeypatch, FIXTURES[source]["malformed"])
    with pytest.raises(SourceError):
        await _call(source)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", sorted(FIXTURES))
async def test_schema_drift_is_typed(monkeypatch, source):
    _serve(monkeypatch, FIXTURES[source]["schema_drift"])
    with pytest.raises(SchemaDriftError) as info:
        await _call(source)
    assert info.value.code == "schema_drift"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["izmir_api", "eshot", "ckan"])
async def test_empty_payload_is_empty_not_a_crash(monkeypatch, source):
    _serve(monkeypatch, FIXTURES[source]["empty"])
    result = await _call(source)
    assert result == [] or result.get("results") == []


@pytest.mark.asyncio
async def test_empty_dam_csv_is_a_source_failure(monkeypatch):
    _serve(monkeypatch, FIXTURES["izsu"]["empty"])
    with pytest.raises(ValueError):
        await _call("izsu")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", sorted(FIXTURES))
async def test_duplicate_rows_parse_deterministically(monkeypatch, source):
    _serve(monkeypatch, FIXTURES[source]["duplicates"])
    result = await _call(source)
    rows = result if isinstance(result, list) else result["results"]
    assert len(rows) == 2 and rows[0] == rows[1]


def test_ckan_drift_error_is_still_a_ckan_error():
    from app.connectors.ckan import CkanError

    assert issubclass(CkanSchemaDriftError, CkanError)
    assert issubclass(CkanSchemaDriftError, SchemaDriftError)


def test_gtfs_member_decode_is_strict():
    assert decode_member("\ufeffroute_id\n".encode("utf-8"), name="routes.txt") == "route_id\n"
    with pytest.raises(SourceError):
        decode_member(b"route_id\n\xff", name="routes.txt")


def test_dam_csv_without_required_columns_is_drift():
    with pytest.raises(SchemaDriftError):
        parse_dam_csv("ID;NAME\n1;x\n")
    assert parse_dam_csv("") == []


def test_schema_drift_maps_to_its_own_error_code():
    from app.services.sources import source_failure_envelope

    payload = source_failure_envelope(SchemaDriftError("drift"), summary="x")
    assert payload["error"]["code"] == "schema_drift"
