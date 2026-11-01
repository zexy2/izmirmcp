"""Composite A→B public-transport comparison over existing services.

Nothing here talks to a source directly: places come from :class:`PlaceResolver`,
stops from :meth:`NearbyService.mobility`, the İZBAN fare from
:meth:`CityInfoService.izban_fare` and warnings from :class:`DisruptionService`.
Durations are straight-line estimates, never a timetable or live ETA; each
upstream failure degrades to a warning instead of failing the whole answer.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.core.envelope import Freshness, error_envelope, success_envelope
from app.core.settings import Settings
from app.core.validation import InputValidationError
from app.services.city_info import CityInfoService
from app.services.disruptions import DisruptionService
from app.services.nearby import NearbyService
from app.services.places import Place, PlaceResolver

MAX_PLACE_CHARS = 80
SEARCH_RADIUS_M = 1500
WALK_M_PER_MIN = 80.0
# kind -> (mode, operator for disruptions, km/h in-vehicle, assumed wait min)
MODES: dict[str, tuple[str, str, float, int]] = {
    "metro_station": ("metro", "metro", 32.0, 5),
    "izban_station": ("izban", "izban", 40.0, 8),
    "ferry_pier": ("izdeniz", "izdeniz", 20.0, 15),
    "bus_stop": ("bus", "eshot", 16.0, 10),
}
# Road/rail is longer than the crow flies; one factor for all modes.
DETOUR_FACTOR = 1.3
TRIP_LIMITS = [
    "Süreler kuş uçuşu mesafe ve sabit ortalama hızdan türetilmiş yaklaşık değerlerdir; tarife veya canlı ETA değildir.",
    "Aktarmalı (çok bacaklı) rotalar ve tramvay bu karşılaştırmada yoktur.",
    "Ücret yalnızca İZBAN için yayımlanmış tarifeden alınır; diğer modlarda bilinmiyor (null).",
]


def _distance_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def validate_place_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError(f"{field} boş olmayan bir yer adı olmalıdır", field=field)
    text = " ".join(value.split())
    if len(text) > MAX_PLACE_CHARS:
        raise InputValidationError(f"{field} en fazla {MAX_PLACE_CHARS} karakter olabilir", field=field)
    return text


def validate_depart_at(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise InputValidationError("depart_at ISO-8601 tarih-saat olmalıdır", field="depart_at")
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise InputValidationError(
            "depart_at ISO-8601 tarih-saat olmalıdır (örn. 2026-10-31T08:30)", field="depart_at"
        ) from exc


def validate_max_options(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise InputValidationError("max_options 1 ile 5 arasında bir tam sayı olmalıdır", field="max_options")
    return value


class TripPlanner:
    def __init__(
        self,
        *,
        settings: Settings,
        resolver: PlaceResolver | None = None,
        nearby: NearbyService | None = None,
        city_info: CityInfoService | None = None,
        disruptions: DisruptionService | None = None,
    ):
        self.settings = settings
        self.resolver = resolver or PlaceResolver()
        self.nearby = nearby or NearbyService(settings=settings)
        self.city_info = city_info or CityInfoService(settings=settings)
        self.disruptions = disruptions or DisruptionService(settings=settings)

    async def _stops(self, place: Place, label: str, warnings: list[str]) -> dict[str, dict[str, Any]]:
        """Nearest stop per mode, or nothing if the mobility lookup failed."""
        try:
            envelope = await self.nearby.mobility(
                lat=place.lat,
                lon=place.lon,
                radius_m=SEARCH_RADIUS_M,
                limit=self.settings.max_limit,
                reference_label=label,
            )
        except Exception:  # noqa: BLE001 - any upstream crash degrades to a warning
            envelope = {"ok": False}
        if not envelope.get("ok"):
            warnings.append(f"{label} çevresindeki duraklar alınamadı; bu uçtaki seçenekler eksik olabilir.")
            return {}
        warnings.extend(w for w in envelope.get("warnings", []) if w not in warnings)
        nearest: dict[str, dict[str, Any]] = {}
        for row in envelope.get("data", []):
            kind = row.get("kind")
            if kind in MODES and kind not in nearest and row.get("lat") is not None and row.get("lon") is not None:
                nearest[kind] = row
        return nearest

    async def _fare(self, origin: dict[str, Any], dest: dict[str, Any], warnings: list[str]) -> Any:
        try:
            envelope = await self.city_info.izban_fare(from_station=origin["name"], to_station=dest["name"])
        except Exception:  # noqa: BLE001 - validation or upstream errors both mean "fare unknown"
            envelope = {"ok": False}
        if envelope.get("ok") and envelope.get("data"):
            return envelope["data"][0].get("fares")
        warnings.append("İZBAN ücreti alınamadı; ücret null bırakıldı.")
        return None

    async def _disruption_titles(self, operator: str, warnings: list[str]) -> list[str]:
        try:
            envelope = await self.disruptions.list(operator=operator, active_only=True, limit=3)
        except Exception:  # noqa: BLE001
            envelope = {"ok": False}
        if not envelope.get("ok"):
            warnings.append(f"{operator} duyuruları alınamadı; aksaklık olmadığı anlamına gelmez.")
            return []
        return [str(row.get("title")) for row in envelope.get("data", []) if row.get("title")]

    async def plan(
        self, *, origin: str, destination: str, depart_at: str | None = None, max_options: int = 3
    ) -> dict[str, Any]:
        origin = validate_place_text(origin, "origin")
        destination = validate_place_text(destination, "destination")
        depart = validate_depart_at(depart_at)
        max_options = validate_max_options(max_options)
        start = self.resolver.resolve(origin)
        end = self.resolver.resolve(destination)

        warnings = ["Başlangıç ve varış, ilçe/mahalle için yaklaşık referans noktalarıdır; kesin adres değildir."]
        origin_stops = await self._stops(start, start.name, warnings)
        dest_stops = await self._stops(end, end.name, warnings)
        if not origin_stops and not dest_stops and len(warnings) > 1:
            return error_envelope(
                summary=f"{start.name} → {end.name} için durak verisi alınamadı.",
                warning="Her iki uçta da ulaşım katmanları alınamadı; daha sonra yeniden deneyin.",
                code="source_unavailable",
            )

        options: list[dict[str, Any]] = []
        for kind, (mode, operator, speed_kmh, wait_min) in MODES.items():
            a, b = origin_stops.get(kind), dest_stops.get(kind)
            if not a or not b or a.get("id") == b.get("id"):
                continue
            walk_in = _distance_m(start.lat, start.lon, a["lat"], a["lon"])
            walk_out = _distance_m(b["lat"], b["lon"], end.lat, end.lon)
            ride = _distance_m(a["lat"], a["lon"], b["lat"], b["lon"]) * DETOUR_FACTOR
            ride_min = ride / (speed_kmh * 1000 / 60)
            total = (walk_in + walk_out) / WALK_M_PER_MIN + wait_min + ride_min
            options.append(
                {
                    "mode": mode,
                    "operator": operator,
                    "approx_duration_min": round(total),
                    "legs": [
                        {"type": "walk", "to": a.get("name"), "distance_m": round(walk_in)},
                        {
                            "type": "ride",
                            "mode": mode,
                            "from_stop": {"id": a.get("id"), "name": a.get("name")},
                            "to_stop": {"id": b.get("id"), "name": b.get("name")},
                            "approx_distance_m": round(ride),
                        },
                        {"type": "walk", "from": b.get("name"), "distance_m": round(walk_out)},
                    ],
                    "fare": None,
                    "warnings": [],
                }
            )
        options.sort(key=lambda option: option["approx_duration_min"])
        options = options[:max_options]

        for option in options:
            ride_leg = option["legs"][1]
            if option["mode"] == "izban":
                option["fare"] = await self._fare(ride_leg["from_stop"], ride_leg["to_stop"], warnings)
            if option["operator"] == "izban":
                option["warnings"].append("İZBAN duyuru akışı erişilemez; aksaklık bilgisi yok.")
            else:
                option["warnings"].extend(await self._disruption_titles(option["operator"], warnings))
            option["rank"] = options.index(option) + 1

        summary = (
            f"{start.name} → {end.name}: {len(options)} doğrudan toplu ulaşım seçeneği yaklaşık süreye göre sıralandı."
            if options
            else f"{start.name} → {end.name}: iki uçta da ortak modda durak bulunamadı; doğrudan seçenek üretilemedi."
        )
        limits = [*TRIP_LIMITS, f"max_options={max_options}", f"search_radius_m={SEARCH_RADIUS_M}"]
        if depart:
            limits.append(f"depart_at={depart} (yalnızca bilgi; tarife eşleştirmesi yapılmaz)")
        next_queries = [
            f"izmir_transit_schedule(mode='{o['mode']}', ...)" for o in options if o["mode"] in {"izban", "izdeniz"}
        ]
        return success_envelope(
            summary=summary,
            data=options,
            freshness=Freshness(status="unknown"),
            limits=limits,
            warnings=warnings,
            next_queries=next_queries,
        )
