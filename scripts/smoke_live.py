"""Optional live smoke check. Requires network access; not part of pytest.

Usage: .venv/bin/python scripts/smoke_live.py
"""
from __future__ import annotations

import asyncio
import sys

from app.core.settings import get_settings
from app.services.air import AirQualityService
from app.services.bus import BusService
from app.services.city_services import CityServicesService
from app.services.disruptions import DisruptionService
from app.services.markets import MarketService
from app.services.catalog import CatalogService
from app.services.nearby import NearbyService
from app.services.transit import TransitService
from app.services.water import WaterService

KONAK = (38.41872, 27.12827)


async def check(label: str, coro) -> bool:
    try:
        envelope = await coro
    except Exception as exc:  # noqa: BLE001 - smoke script reports any failure
        print(f"FAIL {label}: {type(exc).__name__}: {exc}")
        return False
    status = "ok" if envelope.get("ok") else "error"
    print(f"{status.upper():5} {label}: {envelope.get('summary')}")
    if not envelope.get("ok"):
        print(f"      error={envelope.get('error')}")
    return True


async def main() -> int:
    settings = get_settings()
    results = await asyncio.gather(        check("nearby",
            NearbyService(settings=settings).nearby(
                lat=KONAK[0], lon=KONAK[1],
                types=["parking", "pharmacy", "metro_station", "ferry_pier", "bus_stop"],
                radius_m=3000, limit=5,
            ),
        ),
        check("nearby_bbox",
            NearbyService(settings=settings).bbox(
                bbox=[27.1200, 38.4100, 27.1400, 38.4300],
                types=["parking", "pharmacy", "metro_station", "ferry_pier", "bus_stop"],
                limit=5,
            ),
        ),
        check("nearby_district",
            NearbyService(settings=settings).district(
                district="Karşıyaka", types=["pharmacy", "parking"], limit=5,
            ),
        ),
        check("water", WaterService(settings=settings).status(limit=5)),
        check("air", AirQualityService(settings=settings).readings(day="2026-10-28", limit=6)),
        check("metro", TransitService(settings=settings).stations(mode="metro", limit=3)),
        check("izban", TransitService(settings=settings).schedule(mode="izban", from_id=1, to_id=2)),
        check("izdeniz", TransitService(settings=settings).schedule(mode="izdeniz", pier_id=1, day=1)),
        check("catalog", CatalogService(settings=settings).search_datasets(query="otopark", limit=3)),
        check("bus_stops", BusService(settings=settings).stops(query="Konak", limit=3)),
        check("bus_nearby", BusService(settings=settings).stops(
            lat=KONAK[0], lon=KONAK[1], radius_m=300, limit=3)),
        check("bus_arrivals", BusService(settings=settings).arrivals(stop_id="10030", limit=3)),
        check("bus_routes", BusService(settings=settings).routes(query="446", limit=2)),
        check("bus_route_detail", BusService(settings=settings).routes(
            query="304", detail=True)),
        check("bus_departures", BusService(settings=settings).departures(
            stop_id="10030", at="2026-10-05T08:00", limit=3)),
        check("market_day", MarketService(settings=settings).schedule(day="cumartesi", limit=3)),
        check("disruptions", DisruptionService(settings=settings).list(active_only=True, limit=3)),
        check("city_wifi", CityServicesService(settings=settings).nearby(
            kinds=["wifi"], lat=KONAK[0], lon=KONAK[1], radius_m=800, limit=3)),
        check("city_library", CityServicesService(settings=settings).nearby(
            kinds=["library"], lat=KONAK[0], lon=KONAK[1], radius_m=800, limit=3)),
        check("city_bbox", CityServicesService(settings=settings).bbox(
            bbox=[27.1200, 38.4100, 27.1400, 38.4300],
            kinds=["wifi", "izmirim_card"], limit=3)),
        check("city_district", CityServicesService(settings=settings).district(
            district="Karşıyaka", kinds=["wifi", "library"], limit=3)),
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
