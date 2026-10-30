from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.nearby import MOBILITY_TYPES, NearbyService
from tests.conftest import fresh
from tests.test_nearby import FakeApi, FakeCharging, FakeTaxis


class FakeEshot:
    def __init__(self, fail: bool = False):
        self.fail = fail

    async def stops(self):
        if self.fail:
            raise RuntimeError("boom")
        return (
            [
                {"id": "10030", "name": "Konak", "lat": 38.416218, "lon": 27.126321,
                 "routes": ["303", "304"]},
            ],
            fresh(),
        )


class Failing:
    async def taxi_stands(self):
        raise RuntimeError("boom")

    async def charging_points(self):
        raise RuntimeError("boom")


def _service(
    *,
    fail: set[str] | None = None,
    eshot_fail: bool = False,
    all_fail: bool = False,
) -> NearbyService:
    service = NearbyService(
        settings=get_settings(), api=FakeApi(fail=fail), eshot=FakeEshot(fail=eshot_fail)
    )
    if all_fail:
        service.taxis = Failing()
        service.charging = Failing()
    else:
        service.taxis = FakeTaxis()
        service.charging = FakeCharging()
    return service


@pytest.mark.asyncio
async def test_mobility_groups_transport_modes_in_one_answer():
    envelope = await _service().mobility(
        lat=38.41872, lon=27.12827, radius_m=1000, limit=10, reference_label="Konak"
    )

    assert envelope["ok"] is True
    assert envelope["result_info"]["scope"] == "mobility_nearby"
    kinds = {row["kind"] for row in envelope["data"]}
    assert kinds and kinds <= set(MOBILITY_TYPES)
    distances = [row["distance_m"] for row in envelope["data"]]
    assert distances == sorted(distances)


@pytest.mark.asyncio
async def test_mobility_summary_names_the_modes_it_found():
    envelope = await _service().mobility(
        lat=38.41872, lon=27.12827, radius_m=1000, limit=10, reference_label="Konak"
    )

    summary = envelope["summary"]
    assert "metro istasyonu" in summary
    assert "otobüs durağı" in summary
    assert "vapur iskelesi" in summary


@pytest.mark.asyncio
async def test_mobility_excludes_non_transport_layers():
    envelope = await _service().mobility(
        lat=38.41872, lon=27.12827, radius_m=3000, limit=20
    )

    kinds = {row["kind"] for row in envelope["data"]}
    assert "pharmacy" not in kinds
    assert f"modes={','.join(MOBILITY_TYPES)}" in envelope["limits"]
    assert "counts_scope=shown" in envelope["limits"]


@pytest.mark.asyncio
async def test_mobility_says_which_components_it_cannot_cover():
    envelope = await _service().mobility(
        lat=38.41872, lon=27.12827, radius_m=1000, limit=10
    )

    warnings = " ".join(envelope["warnings"]).lower()
    assert "hava kalitesi" in warnings
    assert "trafik" in warnings


@pytest.mark.asyncio
async def test_mobility_points_at_departures_for_the_nearest_stop():
    envelope = await _service().mobility(
        lat=38.41872, lon=27.12827, radius_m=1000, limit=10
    )

    queries = " ".join(envelope["next_queries"])
    assert "izmir_bus_departures" in queries
    assert "10030" in queries


@pytest.mark.asyncio
async def test_mobility_outside_the_province_stays_empty_without_probing():
    envelope = await _service().mobility(lat=40.0, lon=29.0, radius_m=1000, limit=10)

    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert envelope["result_info"]["scope"] == "outside_coverage"


@pytest.mark.asyncio
async def test_mobility_fails_only_when_every_transport_layer_fails():
    envelope = await _service(
        fail={"parking", "metro_station", "izban_station", "ferry_pier"},
        eshot_fail=True,
        all_fail=True,
    ).mobility(lat=38.41872, lon=27.12827, radius_m=1000, limit=10)

    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
