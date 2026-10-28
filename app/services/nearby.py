from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.eshot import EshotConnector
from app.connectors.izmir_api import IzmirOpenApi
from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.geo import haversine_m
from app.core.settings import Settings
from app.services import sources

SUPPORTED_TYPES = (
    "parking",
    "pharmacy",
    "metro_station",
    "izban_station",
    "ferry_pier",
    "bus_stop",
)

GENERAL_LIMITS = [
    "Distances are straight-line metres from the supplied or resolved reference point.",
    "Static station and pier locations do not prove live service or accessibility.",
]


def _maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


def _common(kind: str, item: dict[str, Any], lat: float, lon: float, source_name: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": item.get("id"),
        "name": item.get("name"),
        "lat": item["lat"],
        "lon": item["lon"],
        "distance_m": haversine_m(lat, lon, item["lat"], item["lon"]),
        "maps_url": _maps_url(item["lat"], item["lon"]),
        "source": source_name,
    }


class NearbyService:
    def __init__(
        self,
        *,
        settings: Settings,
        api: IzmirOpenApi | None = None,
        eshot: EshotConnector | None = None,
    ):
        self.settings = settings
        self.api = api or IzmirOpenApi(settings)
        self.eshot = eshot or EshotConnector(settings=settings)

    async def nearby(
        self,
        *,
        lat: float,
        lon: float,
        types: list[str],
        radius_m: int,
        limit: int,
        reference_label: str | None = None,
    ) -> dict[str, Any]:
        loaders = {
            "parking": (self.api.parking, sources.PARKING),
            "pharmacy": (self.api.pharmacies, sources.PHARMACY),
            "metro_station": (self.api.metro_stations, sources.METRO),
            "izban_station": (self.api.izban_stations, sources.IZBAN),
            "ferry_pier": (self.api.ferry_piers, sources.FERRY),
            "bus_stop": (self.eshot.stops, sources.ESHOT_STOPS),
        }
        selected = [kind for kind in SUPPORTED_TYPES if kind in set(types)]
        results = await asyncio.gather(
            *(loaders[kind][0]() for kind in selected), return_exceptions=True
        )

        rows: list[dict[str, Any]] = []
        used_sources: list[Source] = []
        warnings: list[str] = []
        statuses: list[str] = []
        observed: list[str] = []

        for kind, outcome in zip(selected, results):
            _loader, source = loaders[kind]
            if isinstance(outcome, BaseException):
                warnings.append(f"{kind} verisi okunamadı ({type(outcome).__name__}); sonuç kısmi.")
                continue
            items, info = outcome
            used_sources.append(source)
            statuses.append(info.status)
            if info.source_updated_at:
                observed.append(info.source_updated_at)
            for item in items:
                if item.get("lat") is None or item.get("lon") is None:
                    continue
                row = _common(kind, item, lat, lon, source.name)
                if row["distance_m"] > radius_m:
                    continue
                rows.append(self._decorate(kind, row, item))
            if kind == "pharmacy":
                warnings.append(
                    "Nöbetçi eczane listesi günlüktür; kapanış saatini telefonla teyit edin."
                )
            elif kind == "parking":
                warnings.append("Boş yer sayıları anlık bildirimdir; kesin kapasite garantisi değildir.")
            elif kind == "bus_stop":
                warnings.append(
                    "EShot durak konumları yayımlanmış listedir; canlı varış için "
                    "izmir_bus_arrivals(stop_id=...) kullanın."
                )
            else:
                warnings.append(f"{kind} konumları statik kaynaktır; canlı sefer durumu değildir.")

        if not used_sources:
            return error_envelope(
                summary="Yakındaki hizmet verisi okunamadı.",
                warning="Seçilen tüm İzmir kaynakları yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=GENERAL_LIMITS,
            )

        rows.sort(key=lambda row: (row["distance_m"], row.get("name") or ""))
        rows = rows[:limit]
        freshness_status = "stale" if "stale" in statuses else "fresh"
        reference = reference_label or f"{lat:.5f}, {lon:.5f}"
        return success_envelope(
            summary=f"{len(rows)} sonuç bulundu; {reference} çevresinde {radius_m} m içinde.",
            data=rows,
            sources=used_sources,
            freshness=Freshness(
                status=freshness_status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=max(observed) if observed else None,
            ),
            limits=[
                *GENERAL_LIMITS,
                f"radius_m={radius_m}",
                f"limit={limit}",
                f"types={','.join(selected)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=["Sonuçları haritada görmek için maps_url bağlantılarını kullanın."],
        )

    def _decorate(self, kind: str, row: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        if kind == "parking":
            row.update(
                {
                    "free": item.get("free"),
                    "occupied": item.get("occupied"),
                    "capacity": item.get("capacity"),
                    "status": item.get("status"),
                    "is_paid": item.get("is_paid"),
                    "address": item.get("address"),
                    "opening_hours_today": item.get("opening_hours_today"),
                }
            )
        elif kind == "pharmacy":
            row.update(
                {
                    "phone": item.get("phone"),
                    "address": item.get("address"),
                    "district": item.get("district"),
                    "area_note": item.get("area_note"),
                    "duty_date": item.get("duty_date"),
                }
            )
        elif kind in {"metro_station", "izban_station"}:
            row.update({"active": item.get("active"), "order": item.get("order")})
        elif kind == "ferry_pier":
            row.update({"active": item.get("active"), "car_ferry": item.get("car_ferry")})
        elif kind == "bus_stop":
            row.update({"routes": item.get("routes") or []})
        return row
