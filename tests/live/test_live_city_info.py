"""Live checks for İZBAN fare, parking tariffs, traffic cameras and IZSU production."""

from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.city_info import CityInfoService
from tests.live._assertions import assert_ok


@pytest.mark.asyncio
async def test_live_izban_fare_by_id_and_name():
    service = CityInfoService(settings=get_settings())
    rows = assert_ok(await service.izban_fare(from_station=1, to_station=10), keys=("fares", "distance_km"))
    assert rows[0]["fares"]["full"] is not None
    assert_ok(await service.izban_fare(from_station="Aliağa", to_station="Mavişehir", htt=True), keys=("fares",))


@pytest.mark.asyncio
async def test_live_parking_cameras_and_water_production():
    service = CityInfoService(settings=get_settings())
    assert_ok(await service.parking_fees(limit=3), keys=("name", "fees_try"))
    assert_ok(await service.traffic_cameras(lat=38.4222, lon=27.1530, radius_m=5_000, limit=3), keys=("name", "lat"))
    assert_ok(await service.water_production(limit=3), keys=("name", "production"))
