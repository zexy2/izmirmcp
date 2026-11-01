"""izmir_plan_trip composite over fake services — offline."""

from __future__ import annotations

import pytest

from app.core.envelope import success_envelope
from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.mcp import server
from app.services.places import PlaceResolver
from app.services.trip import TripPlanner, validate_depart_at, validate_max_options, validate_place_text


def _stop(kind, sid, name, lat, lon):
    return {"kind": kind, "id": sid, "name": name, "lat": lat, "lon": lon}


STOPS = {
    "Konak": [
        _stop("metro_station", "m-konak", "Konak", 38.4189, 27.1287),
        _stop("ferry_pier", "f-konak", "Konak İskelesi", 38.4192, 27.1260),
        _stop("bus_stop", "b-konak", "Konak", 38.4185, 27.1290),
    ],
    "Karşıyaka": [
        _stop("ferry_pier", "f-ksk", "Karşıyaka İskelesi", 38.4553, 27.1196),
        _stop("izban_station", "i-ksk", "Karşıyaka", 38.4590, 27.1130),
        _stop("bus_stop", "b-ksk", "Karşıyaka", 38.4560, 27.1180),
    ],
    "Bornova": [
        _stop("metro_station", "m-bornova", "Bornova", 38.4580, 27.2120),
        _stop("bus_stop", "b-bornova", "Bornova", 38.4620, 27.2170),
    ],
    "Alsancak": [
        _stop("izban_station", "i-als", "Alsancak", 38.4390, 27.1480),
        _stop("bus_stop", "b-als", "Alsancak", 38.4380, 27.1450),
        _stop("metro_station", "m-basmane", "Basmane", 38.4230, 27.1440),
    ],
}


class FakeNearby:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    async def mobility(self, *, lat, lon, radius_m, limit, reference_label):
        if self.fail:
            raise RuntimeError("upstream down")
        rows = next((rows for key, rows in STOPS.items() if key in reference_label), [])
        return success_envelope(summary="ok", data=rows)


class FakeCityInfo:
    async def izban_fare(self, *, from_station, to_station):
        return success_envelope(summary="ok", data=[{"fares": {"full": 5.12}}])


class FakeDisruptions:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    async def list(self, *, operator, active_only, limit):
        if self.fail:
            return {"ok": False}
        return success_envelope(summary="ok", data=[{"title": f"{operator} duyuru"}])


def _planner(*, nearby_fail=False, disruptions_fail=False):
    return TripPlanner(
        settings=get_settings(),
        resolver=PlaceResolver(),
        nearby=FakeNearby(fail=nearby_fail),
        city_info=FakeCityInfo(),
        disruptions=FakeDisruptions(fail=disruptions_fail),
    )


@pytest.mark.asyncio
async def test_konak_to_karsiyaka_ranks_ferry_and_bus():
    result = await _planner().plan(origin="Konak", destination="Karşıyaka")
    assert result["ok"]
    modes = [o["mode"] for o in result["data"]]
    assert set(modes) == {"izdeniz", "bus"}
    durations = [o["approx_duration_min"] for o in result["data"]]
    assert durations == sorted(durations)
    assert [o["rank"] for o in result["data"]] == [1, 2]
    assert all(o["fare"] is None for o in result["data"])
    assert any("izdeniz duyuru" in w for o in result["data"] for w in o["warnings"])
    assert result["disclaimer"]


@pytest.mark.asyncio
async def test_bornova_to_alsancak_respects_max_options():
    result = await _planner().plan(
        origin="Bornova", destination="Alsancak", max_options=1, depart_at="2026-10-31T08:30"
    )
    assert result["ok"]
    assert len(result["data"]) == 1
    assert result["data"][0]["legs"][1]["type"] == "ride"
    assert any(limit.startswith("depart_at=") for limit in result["limits"])


@pytest.mark.asyncio
async def test_upstream_failure_degrades_to_error_with_warning():
    result = await _planner(nearby_fail=True).plan(origin="Konak", destination="Karşıyaka")
    assert not result["ok"]
    assert result["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_disruption_failure_keeps_partial_options():
    result = await _planner(disruptions_fail=True).plan(origin="Konak", destination="Karşıyaka")
    assert result["ok"] and result["data"]
    assert any("duyuruları alınamadı" in w for w in result["warnings"])


def test_validators():
    with pytest.raises(InputValidationError):
        validate_place_text("x" * 81, "origin")
    with pytest.raises(InputValidationError):
        validate_place_text("  ", "origin")
    with pytest.raises(InputValidationError):
        validate_max_options(6)
    with pytest.raises(InputValidationError):
        validate_max_options(True)
    with pytest.raises(InputValidationError):
        validate_depart_at("yarın sabah")
    assert validate_depart_at(None) is None


@pytest.mark.asyncio
async def test_tool_returns_validation_envelope():
    result = await server.izmir_plan_trip(origin="Konak", destination="Karşıyaka", max_options=9)
    assert not result["ok"]
