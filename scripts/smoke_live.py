"""Optional live smoke check. Requires network access; not part of pytest.

Usage: .venv/bin/python scripts/smoke_live.py
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
import time

from app.core.settings import get_settings
from app.services.air import AirQualityService
from app.services.bus import BusService
from app.services.city_services import CityServicesService
from app.services.disruptions import DisruptionService
from app.services.markets import MarketService
from app.services.neighborhood import NeighborhoodService
from app.services.catalog import CatalogService
from app.services.datastore_sql import DatastoreSqlService
from app.services.nearby import NearbyService
from app.services.traffic import TrafficService
from app.services.transit import TransitService
from app.services.water import WaterService

KONAK = (38.41872, 27.12827)


async def check(label: str, coro, *, expect_unavailable: bool = False) -> bool:
    """Report one live call. ``expect_unavailable`` marks a deliberately-dead source.

    A documented-unavailable source is a pass only when the envelope says
    ``source_unavailable``; any other failure is a real failure.
    """
    try:
        envelope = await coro
    except Exception as exc:  # noqa: BLE001 - smoke script reports any failure
        print(f"FAIL {label}: {type(exc).__name__}: {exc}")
        return False
    if expect_unavailable:
        ok = (
            envelope.get("ok") is False
            and (envelope.get("error") or {}).get("code") == "source_unavailable"
        )
        print(f"{'OK' if ok else 'FAIL':5} {label}: {envelope.get('summary')}")
        return ok
    status = "ok" if envelope.get("ok") else "error"
    print(f"{status.upper():5} {label}: {envelope.get('summary')}")
    if not envelope.get("ok"):
        print(f"      error={envelope.get('error')}")
    return bool(envelope.get("ok"))


async def traffic_recent_check(settings) -> bool:
    """An unfiltered small limit reads one newest-first page and states its basis."""
    started = time.monotonic()
    envelope = await TrafficService(settings=settings).list(limit=2)
    elapsed = time.monotonic() - started
    info = envelope.get("result_info") or {}
    freshness = envelope.get("freshness") or {}
    ok = (
        bool(envelope.get("ok"))
        and isinstance(info.get("matched"), int)
        and info["matched"] >= len(envelope.get("data") or [])
        and bool(freshness.get("source_updated_at"))
        and any("en_yeni_olcum=" in line for line in envelope.get("limits") or [])
    )
    print(
        f"{'OK' if ok else 'FAIL':5} traffic_recent: {envelope.get('summary')} "
        f"| tazelik={freshness.get('status')} "
        f"kaynak={freshness.get('source_updated_at')} ({elapsed:.2f}s)"
    )
    return ok


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
        check("mobility", NearbyService(settings=settings).mobility(
            lat=KONAK[0], lon=KONAK[1], radius_m=1000, limit=6,
            reference_label="Konak",
        )),
        check("water", WaterService(settings=settings).status(limit=5)),
        check("air", AirQualityService(settings=settings).readings(day="2026-10-28", limit=6)),
        check("metro", TransitService(settings=settings).stations(mode="metro", limit=3)),
        check("izban", TransitService(settings=settings).schedule(mode="izban", from_id=1, to_id=2)),
        check("izdeniz", TransitService(settings=settings).schedule(mode="izdeniz", pier_id=1, day=1)),
        check("catalog", CatalogService(settings=settings).search_datasets(query="otopark", limit=3)),
        check("catalog_search", CatalogService(settings=settings).query_resource(
            resource_id="3e63e16e-74a9-40f6-8ad3-043ad4fa4a16", search="Konak", limit=3)),
        check("catalog_sort", CatalogService(settings=settings).query_resource(
            resource_id="3e63e16e-74a9-40f6-8ad3-043ad4fa4a16", sort="ADI desc", limit=2)),
        check("bus_stops", BusService(settings=settings).stops(query="Konak", limit=3)),
        check("taxi_nearby", NearbyService(settings=settings).nearby(
            lat=KONAK[0], lon=KONAK[1], types=["taxi_stand"], radius_m=1500, limit=3)),
        check("bus_nearby", BusService(settings=settings).stops(
            lat=KONAK[0], lon=KONAK[1], radius_m=300, limit=3)),
        check("bus_arrivals", BusService(settings=settings).arrivals(stop_id="10030", limit=3)),
        check("bus_routes", BusService(settings=settings).routes(query="446", limit=2)),
        check("gtfs_status", BusService(settings=settings).timetable_status()),
        check("neighborhood", NeighborhoodService(settings=settings).profile(
            neighborhood="Alsancak", district="Konak")),
        check("neighborhood_district", NeighborhoodService(settings=settings).profile(
            district="Konak", limit=3)),
        check("bus_route_detail", BusService(settings=settings).routes(
            query="304", detail=True)),
        check("bus_departures", BusService(settings=settings).departures(
            stop_id="10030", at="2026-10-05T08:00", limit=3)),
        check("bus_departures_stop_query", BusService(settings=settings).departures(
            stop_query="Konak", limit=3)),
        check("bus_departures_nearby", BusService(settings=settings).departures(
            lat=KONAK[0], lon=KONAK[1], radius_m=300,
            at="2026-10-05T08:00", limit=3)),
        check("market_day", MarketService(settings=settings).schedule(day="cumartesi", limit=3)),
        check("disruptions", DisruptionService(settings=settings).list(active_only=True, limit=3)),
        check("disruptions_metro", DisruptionService(settings=settings).list(
            operator="metro", limit=2)),
        check("disruptions_izdeniz", DisruptionService(settings=settings).list(
            operator="izdeniz", limit=2)),
        check("disruptions_izban_unavailable", DisruptionService(settings=settings).list(
            operator="izban", limit=2), expect_unavailable=True),
        check("city_wifi", CityServicesService(settings=settings).nearby(
            kinds=["wifi"], lat=KONAK[0], lon=KONAK[1], radius_m=800, limit=3)),
        check("city_library", CityServicesService(settings=settings).nearby(
            kinds=["library"], lat=KONAK[0], lon=KONAK[1], radius_m=800, limit=3)),
        check("city_bbox", CityServicesService(settings=settings).bbox(
            bbox=[27.1200, 38.4100, 27.1400, 38.4300],
            kinds=["wifi", "izmirim_card"], limit=3)),
        check("city_district", CityServicesService(settings=settings).district(
            district="Karşıyaka", kinds=["wifi", "library"], limit=3)),
        check("charging_nearby", NearbyService(settings=settings).nearby(
            lat=KONAK[0], lon=KONAK[1], types=["charging_station"], radius_m=3000, limit=3)),
        check("traffic_history", TrafficService(settings=settings).list(
            segment="Konak", limit=3)),
        traffic_recent_check(settings),
        check("datastore_sql", DatastoreSqlService(
            settings=dataclasses.replace(
                settings,
                ckan_sql_allowed_resource_ids=("0c791266-a2e4-4f14-82b8-9a9b102fbf94",),
            )
        ).query(
            resource_id="0c791266-a2e4-4f14-82b8-9a9b102fbf94",
            sql="SELECT COUNT(*) AS n FROM records",
        )),
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
