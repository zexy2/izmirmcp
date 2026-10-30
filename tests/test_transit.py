from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.transit import TransitService
from tests.conftest import fresh


class FakeApi:
    async def metro_stations(self):
        return ([{"id": 2, "name": "Konak", "lat": 38.4175, "lon": 27.1283, "active": True, "order": 11}], fresh())

    async def izban_stations(self):
        return ([{"id": 1, "name": "Aliağa", "lat": 38.7889, "lon": 26.9669, "active": None, "order": 38}], fresh())

    async def ferry_piers(self):
        return (
            [{"id": 1, "name": "Konak", "lat": 38.4186, "lon": 27.1258, "active": True, "car_ferry": False}],
            fresh(),
        )

    async def metro_schedule(self):
        return ([{"order": 1, "start": "06:00:00", "end": "06:30:00", "interval_minutes": 7.5}], fresh())

    async def izban_schedule(self, from_id, to_id):
        return (
            [
                {
                    "from": "Aliağa",
                    "from_id": from_id,
                    "to": "Biçerova",
                    "to_id": to_id,
                    "departure": "00:09:00",
                    "arrival": "00:14:00",
                }
            ],
            fresh(),
        )

    async def izdeniz_pier_schedule(self, pier_id, day):
        return (
            {
                "day_id": day,
                "departures": [
                    {
                        "time": "07:30:00",
                        "destinations": ["Karşıyaka"],
                        "car_ferry": False,
                        "cancelled": None,
                        "note": None,
                    }
                ],
            },
            fresh(),
        )

    async def izdeniz_route_schedule(self, from_id, to_id, day):
        return (
            [
                {
                    "route_name": "Test",
                    "piers": [str(from_id), str(to_id)],
                    "trips": [
                        {"times": [{"departure": "07:30:00", "arrival": None}], "cancelled": False, "note": None}
                    ],
                }
            ],
            fresh(),
        )


@pytest.mark.asyncio
async def test_station_listing_respects_limit():
    envelope = await TransitService(settings=get_settings(), api=FakeApi()).stations(mode="metro", limit=1)
    assert envelope["ok"] is True
    assert envelope["data"][0]["name"] == "Konak"
    assert envelope["freshness"]["status"] == "fresh"


@pytest.mark.asyncio
async def test_metro_schedule_rejects_station_pair():
    with pytest.raises(InputValidationError):
        await TransitService(settings=get_settings(), api=FakeApi()).schedule(mode="metro", from_id=1, to_id=2)


@pytest.mark.asyncio
async def test_izban_schedule_requires_both_ids():
    with pytest.raises(InputValidationError):
        await TransitService(settings=get_settings(), api=FakeApi()).schedule(mode="izban", from_id=1)


@pytest.mark.asyncio
async def test_izdeniz_pier_schedule_and_day_bounds():
    service = TransitService(settings=get_settings(), api=FakeApi())
    envelope = await service.schedule(mode="izdeniz", pier_id=1, day=2)
    assert envelope["ok"] is True
    assert envelope["data"][0]["destinations"] == ["Karşıyaka"]
    assert envelope["limits"] == ["mode=izdeniz", "pier_id=1", "day=2"]
    with pytest.raises(InputValidationError):
        await service.schedule(mode="izdeniz", pier_id=1, day=9)


@pytest.mark.asyncio
async def test_izdeniz_route_requires_pier_or_pair():
    with pytest.raises(InputValidationError):
        await TransitService(settings=get_settings(), api=FakeApi()).schedule(mode="izdeniz")
