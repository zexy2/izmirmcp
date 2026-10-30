from __future__ import annotations

from datetime import date
from typing import Any

from app.connectors.http import get_json
from app.connectors.schema import SchemaDriftError, expect_type
from app.core.envelope import bounded_id, bounded_text, finite_number
from app.core.geo import valid_lat_lon
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# İZBAN tutarhesaplama fields, verified live on 2026-10-31. Keys are ours; the
# source names are kept next to them so a rename upstream is easy to spot.
FARE_FIELDS = (
    ("full", "TamUcret"),
    ("student", "OgrenciUcret"),
    ("teacher", "OgretmenUcret"),
    ("age_60", "Yas60Ucret"),
    ("free_pass", "SerbestUcret"),
)
REFUND_FIELDS = (
    ("full", "IadeTam"),
    ("student", "IadeOgrenci"),
    ("teacher", "IadeOgretmen"),
    ("age_60", "Iade60Yas"),
    ("free_pass", "IadeSerbest"),
)
MIN_BALANCE_FIELDS = (
    ("full", "MinBakiyeTam"),
    ("student", "MinBakiyeOgrenci"),
    ("teacher", "MinBakiyeOgretmen"),
    ("age_60", "MinBakiye60Yas"),
    ("free_pass", "MinBakiyeSerbest"),
)


def _as_float(value: Any) -> float | None:
    return finite_number(value)


def _records(payload: Any) -> list[dict[str, Any]]:
    """Return only dict rows from a source payload.

    A hijacked or corrupted source can answer with ``[null, 1, "x"]``; indexing
    such an item raised ``AttributeError`` and became an HTTP 500. Dropping the
    unusable rows keeps the failure a typed source error, not a crash.
    """
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _coordinates(lat_value: Any, lon_value: Any) -> tuple[float, float] | None:
    """Return a valid WGS84 pair, or ``None`` when it is not placeable.

    A source row with latitude 999 is not a location; keeping it would put a
    point off the globe in every downstream distance and rectangle query.
    """
    lat = finite_number(lat_value)
    lon = finite_number(lon_value)
    if lat is None or lon is None or not valid_lat_lon(lat, lon):
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
                strict=True,
            )
            return expect_type(payload, (list, dict), what=f"openapi {path}")

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
        for item in _records(payload):
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
                    "id": bounded_id(item.get("ufid") or item.get("name")),
                    "name": bounded_text(item.get("name")),
                    "lat": lat,
                    "lon": lon,
                    "free": free,
                    "occupied": occupied,
                    "capacity": capacity,
                    "status": item.get("status"),
                    "is_paid": item.get("isPaid"),
                    "provider": item.get("provider"),
                    "address": bounded_text(item.get("address")),
                    "opening_hours_today": (item.get("openingHours") or {}).get(today),
                }
            )
        return rows, info

    async def pharmacies(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("ibb/nobetcieczaneler", "openapi.pharmacies")
        rows = []
        for item in _records(payload):
            pair = _coordinates(item.get("LokasyonX"), item.get("LokasyonY"))
            if pair is None:
                continue
            lat, lon = pair
            rows.append(
                {
                    "id": bounded_id(item.get("EczaneId")) if item.get("EczaneId") not in (None, -1, 0) else None,
                    "name": bounded_text(item.get("Adi")),
                    "lat": lat,
                    "lon": lon,
                    "phone": bounded_text(item.get("Telefon"), 64),
                    "address": bounded_text(item.get("Adres")),
                    "district": bounded_text(item.get("Bolge"), 128),
                    "area_note": bounded_text(item.get("BolgeAciklama")),
                    "duty_date": bounded_text(item.get("Tarih"), 40),
                }
            )
        return rows, info

    async def air_quality(self, day: str) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached(f"ibb/cevre/havadegerleri/{day}", f"openapi.air.{day}")
        grouped: dict[str, dict[str, Any]] = {}
        for item in _records(payload):
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

    async def izban_fare(
        self, from_id: int, to_id: int, *, transfer: bool, htt: bool
    ) -> tuple[dict[str, Any], CacheInfo]:
        """Fare between two İZBAN stations.

        Callers pass validated positive ints and real bools only; the path is
        built from those, never from caller text. The fourth segment must be the
        literal ``true``/``false`` (``0``/``1`` is a 400), the third is ``0``/``1``.
        """
        transfer_part = "1" if transfer else "0"
        htt_part = "true" if htt else "false"
        payload, info = await self._cached(
            f"izban/tutarhesaplama/{from_id}/{to_id}/{transfer_part}/{htt_part}",
            f"openapi.izban.fare.{from_id}.{to_id}.{transfer_part}.{htt_part}",
        )
        payload = expect_type(payload, dict, what="openapi izban fare")
        if not isinstance(finite_number(payload.get("TamUcret")), float):
            raise SchemaDriftError("openapi izban fare: TamUcret missing")
        return {
            "from_station": bounded_text(payload.get("BinisIstasyonu"), 128),
            "to_station": bounded_text(payload.get("InisIstasyonu"), 128),
            "distance_km": _as_float(payload.get("ToplamKm")),
            "fares": {key: _as_float(payload.get(source)) for key, source in FARE_FIELDS},
            "refunds": {key: _as_float(payload.get(source)) for key, source in REFUND_FIELDS},
            "min_balance": {key: _as_float(payload.get(source)) for key, source in MIN_BALANCE_FIELDS},
        }, info

    async def ferry_piers(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("izdeniz/iskeleler", "openapi.izdeniz.piers")
        rows = []
        for item in _records(payload):
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
            for item in _records(payload)
        ]
        return rows, info

    async def izban_schedule(self, from_id: int, to_id: int) -> tuple[list[dict[str, Any]], CacheInfo]:
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
            for item in _records(payload)
        ]
        return rows, info

    async def izdeniz_pier_schedule(self, pier_id: int, day: int) -> tuple[dict[str, Any], CacheInfo]:
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
                        place.get("iskeleAdi") for place in item.get("VarisYerleri") or [] if isinstance(place, dict)
                    ],
                    "car_ferry": item.get("arabaliVapurSeferi"),
                    "cancelled": item.get("IptalMi"),
                    "note": (item.get("Aciklama") or "").strip() or None,
                }
            )
        return {"day_id": payload.get("gunId") if isinstance(payload, dict) else day, "departures": departures}, info

    async def izdeniz_route_schedule(
        self, from_id: int, to_id: int, day: int
    ) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached(
            f"izdeniz/vapursaatleri/{from_id}/{to_id}/{day}/1",
            f"openapi.izdeniz.route.{from_id}.{to_id}.{day}",
        )
        routes = []
        for item in _records(payload):
            departures = []
            for row in item.get("seferSatirlari") or []:
                times = row.get("seferSaatleri") or []
                departures.append(
                    {
                        "times": [
                            {"departure": t.get("KalkisSaati"), "arrival": t.get("VarisSaati")}
                            for t in times
                            if isinstance(t, dict)
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

    async def tram_lines(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached("tramvay/hatlar", "openapi.tram.lines")
        rows = [
            {
                "line_id": item.get("HatId"),
                "name": bounded_text(item.get("Adi")),
                "side": bounded_text(item.get("Aciklama"), 128),
                "start": bounded_text(item.get("HatBaslangic"), 128),
                "end": bounded_text(item.get("HatBitis"), 128),
            }
            for item in _records(payload)
        ]
        return rows, info

    async def tram_stations(self, line_id: int) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached(f"tramvay/istasyonlar/{line_id}", f"openapi.tram.stations.{line_id}")
        rows = []
        for item in _records(payload):
            pair = _coordinates(item.get("Enlem"), item.get("Boylam"))
            if pair is None:
                continue
            rows.append(
                {
                    "id": item.get("IstasyonId"),
                    "name": bounded_text(item.get("Adi")),
                    "lat": pair[0],
                    "lon": pair[1],
                }
            )
        return rows, info

    async def tram_schedule(self, line_id: int) -> tuple[list[dict[str, Any]], CacheInfo]:
        payload, info = await self._cached(f"tramvay/seferler/{line_id}", f"openapi.tram.schedule.{line_id}")
        rows = [
            {
                "order": item.get("Sira"),
                "start": item.get("BaslangicSaati"),
                "end": item.get("BitisSaati"),
                "interval_minutes": _as_float(item.get("Aralik")),
            }
            for item in _records(payload)
        ]
        return rows, info


def _station_rows(payload: Any, *, order_key: str) -> list[dict[str, Any]]:
    rows = []
    for item in _records(payload):
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
