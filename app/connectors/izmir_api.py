from __future__ import annotations

from datetime import date
from typing import Any

from app.connectors.http import get_json
from app.core.envelope import finite_number
from app.core.geo import valid_lat_lon
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _as_float(value: Any) -> float | None:
    return finite_number(value)


def _coordinates(lat_value: Any, lon_value: Any) -> tuple[float, float] | None:
    """Return a valid WGS84 pair, or ``None`` when it is not placeable.

    A source row with latitude 999 is not a location; keeping it would put a
    point off the globe in every downstream distance and rectangle query.
    """
    lat = finite_number(lat_value)
    lon = finite_number(lon_value)
    if not valid_lat_lon(lat, lon):
        return None
    return lat, lon


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


class IzmirOpenApi:
    """Client for the municipality's public openapi.izmir.bel.tr endpoints."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.openapi_base_url.rstrip("/")

    async def _cached(self, path: str, key: str) -> tuple[Any, CacheInfo]:
        async def loader() -> Any:
            payload = await get_json(
                f"{self.base_url}/{path.lstrip('/')}",
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
            )
            if not isinstance(payload, (list, dict)):
                raise ValueError("unexpected API payload")
            return payload

        return await cached_source_data(
            key,
            ttl_seconds=self.settings.openapi_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.openapi_stale_if_error_seconds,
            loader=loader,
        )

    async def parking(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("ibb/izum/otoparklar", "openapi.parking")
        today = WEEKDAYS[date.today().weekday()]
        rows = []
        for item in payload if isinstance(payload, list) else []:
            pair = _coordinates(item.get("lat"), item.get("lng"))
            if pair is None:
                continue
            lat, lon = pair
            occupancy = item.get("occupancy") or {}
            total = occupancy.get("total") or {}
            free = total.get("free")
            occupied = total.get("occupied")
            capacity = None
            if isinstance(free, int) and isinstance(occupied, int):
                capacity = free + occupied
            rows.append(
                {
                    "id": item.get("ufid") or item.get("name"),
                    "name": item.get("name"),
                    "lat": lat,
                    "lon": lon,
                    "free": free,
                    "occupied": occupied,
                    "capacity": capacity,
                    "status": item.get("status"),
                    "is_paid": item.get("isPaid"),
                    "provider": item.get("provider"),
                    "address": item.get("address") or None,
                    "opening_hours_today": (item.get("openingHours") or {}).get(today),
                }
            )
        return rows, info

    async def pharmacies(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("ibb/nobetcieczaneler", "openapi.pharmacies")
        rows = []
        for item in payload if isinstance(payload, list) else []:
            pair = _coordinates(item.get("LokasyonX"), item.get("LokasyonY"))
            if pair is None:
                continue
            lat, lon = pair
            rows.append(
                {
                    "id": item.get("EczaneId") if item.get("EczaneId") not in (None, -1, 0) else None,
                    "name": item.get("Adi"),
                    "lat": lat,
                    "lon": lon,
                    "phone": item.get("Telefon"),
                    "address": (item.get("Adres") or "").strip() or None,
                    "district": item.get("Bolge"),
                    "area_note": item.get("BolgeAciklama"),
                    "duty_date": item.get("Tarih"),
                }
            )
        return rows, info

    async def air_quality(self, day: str) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached(
            f"ibb/cevre/havadegerleri/{day}", f"openapi.air.{day}"
        )
        grouped: dict[str, dict[str, Any]] = {}
        for item in payload if isinstance(payload, list) else []:
            station = str(item.get("BolgeAdi") or "").strip()
            if not station:
                continue
            entry = grouped.setdefault(
                station,
                {
                    "station": station,
                    "station_id": item.get("BolgeId"),
                    "observed_at": None,
                    "readings": [],
                },
            )
            observed = item.get("OlcumTarihi")
            if observed and (entry["observed_at"] is None or observed > entry["observed_at"]):
                entry["observed_at"] = observed
            entry["readings"].append(
                {
                    "pollutant": item.get("GazAdi"),
                    "value": _as_float(item.get("OlcumDegeri")),
                    "unit": None,
                }
            )
        return list(grouped.values()), info

    async def metro_stations(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("metro/istasyonlar", "openapi.metro.stations")
        return _station_rows(payload, order_key="Sira"), info

    async def izban_stations(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("izban/istasyonlar", "openapi.izban.stations")
        return _station_rows(payload, order_key="IstasyonSirasi"), info

    async def ferry_piers(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("izdeniz/iskeleler", "openapi.izdeniz.piers")
        rows = []
        for item in payload if isinstance(payload, list) else []:
            pair = _coordinates(item.get("Enlem"), item.get("Boylam"))
            if pair is None:
                continue
            lat, lon = pair
            rows.append(
                {
                    "id": item.get("IskeleId"),
                    "name": item.get("Adi"),
                    "lat": lat,
                    "lon": lon,
                    "active": _as_bool(item.get("AktifMi")),
                    "car_ferry": _as_bool(item.get("ArabaliVapurIskelesiMi")),
                }
            )
        return rows, info

    async def metro_schedule(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("metro/sefersaatleri", "openapi.metro.schedule")
        rows = [
            {
                "order": item.get("Sira"),
                "start": item.get("BaslangicSaati"),
                "end": item.get("BitisSaati"),
                "interval_minutes": _as_float(item.get("Aralik")),
            }
            for item in payload if isinstance(payload, list)
        ]
        return rows, info

    async def izban_schedule(
        self, from_id: int, to_id: int
    ) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached(
            f"izban/sefersaatleri/{from_id}/{to_id}",
            f"openapi.izban.schedule.{from_id}.{to_id}",
        )
        rows = [
            {
                "from": item.get("HareketIstasyonAdi"),
                "from_id": item.get("HareketIstasyonId"),
                "to": item.get("VarisIstasyonAdi"),
                "to_id": item.get("VarisIstasyonId"),
                "departure": item.get("HareketSaati"),
                "arrival": item.get("VarisSaati"),
            }
            for item in payload if isinstance(payload, list)
        ]
        return rows, info

    async def izdeniz_pier_schedule(
        self, pier_id: int, day: int
    ) -> tuple[dict[str, Any], CacheInfo]:
        payload, info = await self._cached(
            f"izdeniz/iskelesefersaatleri/{pier_id}/{day}",
            f"openapi.izdeniz.pier.{pier_id}.{day}",
        )
        departures = []
        for item in (payload.get("seferler") if isinstance(payload, dict) else None) or []:
            departures.append(
                {
                    "time": item.get("KalkisSaati"),
                    "destinations": [
                        place.get("iskeleAdi")
                        for place in item.get("VarisYerleri") or []
                        if isinstance(place, dict)
                    ],
                    "car_ferry": item.get("arabaliVapurSeferi"),
                    "cancelled": item.get("IptalMi"),
                    "note": (item.get("Aciklama") or "").strip() or None,
                }
            )
        return {"day_id": payload.get("gunId") if isinstance(payload, dict) else day,
                "departures": departures}, info

    async def izdeniz_route_schedule(
        self, from_id: int, to_id: int, day: int
    ) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached(
            f"izdeniz/vapursaatleri/{from_id}/{to_id}/{day}/1",
            f"openapi.izdeniz.route.{from_id}.{to_id}.{day}",
        )
        routes = []
        for item in payload if isinstance(payload, list) else []:
            departures = []
            for row in item.get("seferSatirlari") or []:
                times = row.get("seferSaatleri") or []
                departures.append(
                    {
                        "times": [
                            {"departure": t.get("KalkisSaati"), "arrival": t.get("VarisSaati")}
                            for t in times if isinstance(t, dict)
                        ],
                        "cancelled": row.get("IptalMi"),
                        "note": (row.get("Aciklama") or "").strip() or None,
                    }
                )
            routes.append(
                {
                    "route_name": item.get("hatAdi"),
                    "piers": item.get("iskeleler"),
                    "trips": departures,
                }
            )
        return routes, info


def _station_rows(payload: Any, *, order_key: str) -> list[dict[str, Any]]:
    rows = []
    for item in payload if isinstance(payload, list) else []:
        pair = _coordinates(item.get("Enlem"), item.get("Boylam"))
        if pair is None:
            continue
        lat, lon = pair
        rows.append(
            {
                "id": item.get("IstasyonId"),
                "name": item.get("IstasyonAdi") or item.get("Adi"),
                "lat": lat,
                "lon": lon,
                "active": _as_bool(item.get("AktifMi")),
                "order": item.get(order_key),
            }
        )
    return rows
