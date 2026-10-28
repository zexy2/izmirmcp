from __future__ import annotations

from typing import Any

from app.connectors.city_layers import CityLayerConnector, parse_market_days
from app.core.envelope import Freshness, error_envelope, success_envelope
from app.core.geo import haversine_m, normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_radius
from app.services import sources

DAY_ALIASES = {
    "pazartesi": "monday",
    "sali": "tuesday",
    "çarşamba": "wednesday",
    "carsamba": "wednesday",
    "persembe": "thursday",
    "cuma": "friday",
    "cumartesi": "saturday",
    "pazar": "sunday",
}
DAY_LABELS = {
    "monday": "Pazartesi", "tuesday": "Salı", "wednesday": "Çarşamba",
    "thursday": "Perşembe", "friday": "Cuma", "saturday": "Cumartesi",
    "sunday": "Pazar",
}

LIMITS = [
    "Pazar yeri konumları yayımlanmış listedir; kurulum saati veya açık/kapalı durumu değildir.",
    "Kurulma günü yalnızca kaynağın serbest metnindeki açık gün adından çıkarılır.",
    "Yakınlık kuş uçuşu metredir.",
]


def _maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


def resolve_day(value: str | None) -> str | None:
    if value is None:
        return None
    text = normalize_name(str(value))
    if text in {"bugun", "today"}:
        return "today"
    if text in {"yarin", "tomorrow"}:
        return "tomorrow"
    day = DAY_ALIASES.get(text) or DAY_ALIASES.get(str(value).strip().casefold())
    if day is None:
        raise InputValidationError(
            "day must be a Turkish weekday name (pazartesi..pazar), bugun or yarin", field="day"
        )
    return day


class MarketService:
    def __init__(self, *, settings: Settings, api: CityLayerConnector | None = None):
        self.settings = settings
        self.api = api or CityLayerConnector(settings=settings)

    async def schedule(
        self,
        *,
        day: str | None = None,
        district: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        day_key = resolve_day(day)
        uses_coordinates = lat is not None or lon is not None
        if uses_coordinates and (lat is None or lon is None):
            raise InputValidationError("lat and lon must be supplied together", field="lat")
        if lat is not None and lon is not None:
            validate_lat_lon(lat, lon)
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

        try:
            rows, info = await self.api.market_rows()
        except Exception as exc:
            return error_envelope(
                summary="Semt pazarı verisi kullanılamıyor.",
                warning=f"Kaynak isteği başarısız oldu: {type(exc).__name__}. Veri üretilmedi.",
                code="source_unavailable",
                sources=[sources.MARKET],
            )

        limits = [f"limit={safe_limit}"]
        selected = []
        unknown_days = 0
        for row in rows:
            days = parse_market_days(row.get("note"))
            confidence = "parsed" if days else "unknown"
            if not days:
                unknown_days += 1
            selected.append({**row, "days": days, "day_confidence": confidence})

        warnings = ["Kurulma günü kaynağın serbest metninden türetilir; listede olmayan pazar yeri "
                    "günü bilinmiyor demektir, 'her gün kurulmuyor' kanıtı değildir."]

        if day_key is not None:
            if day_key in {"today", "tomorrow"}:
                from datetime import date, timedelta

                target = date.today() + (timedelta(days=1) if day_key == "tomorrow" else timedelta(days=0))
                day_key = ("monday", "tuesday", "wednesday", "thursday", "friday",
                           "saturday", "sunday")[target.weekday()]
                limits.append(f"day={day_key} (system date {target.isoformat()})")
            else:
                limits.append(f"day={day_key}")
            selected = [row for row in selected if day_key in row["days"]]
            summary_day = DAY_LABELS.get(day_key, day_key)
            summary_prefix = f"{summary_day} günü kurulan"
        else:
            summary_prefix = "Kayıtlı"

        if district is not None:
            needle = normalize_name(district)
            selected = [
                row for row in selected
                if needle in normalize_name(row.get("district") or "")
            ]
            limits.append(f"district={district.strip()[:60]}")

        if lat is not None and lon is not None:
            safe_radius = validate_radius(
                1_500 if radius_m is None else radius_m, self.settings.max_radius_m
            )
            with_distance = []
            for row in selected:
                if row.get("lat") is None or row.get("lon") is None:
                    continue
                distance = haversine_m(lat, lon, row["lat"], row["lon"])
                if distance > safe_radius:
                    continue
                with_distance.append({**row, "distance_m": distance})
            selected = with_distance
            limits.extend([f"radius_m={safe_radius}", f"lat={lat:.5f}", f"lon={lon:.5f}"])
        elif radius_m is not None:
            raise InputValidationError("radius_m requires lat and lon", field="radius_m")

        for row in selected:
            if row.get("lat") is not None and row.get("lon") is not None:
                row["maps_url"] = _maps_url(row["lat"], row["lon"])

        selected.sort(
            key=lambda row: (
                row.get("distance_m", 0.0),
                normalize_name(row.get("district") or ""),
                normalize_name(row.get("name") or ""),
            )
        )
        data = selected[:safe_limit]
        if unknown_days:
            warnings.append(
                f"{unknown_days} pazar yeri için kurulma günü metinden çıkarılamadı; "
                "bunlar yalnızca day_confidence='unknown' ile listelenir."
            )
        if day_key is not None and not data:
            warnings.append(
                "Bu gün için eşleşme yok. Bu, o gün hiç pazar kurulmadığının kanıtı değildir; "
                "kaynakta günü bilinmeyen kayıtlar olabilir."
            )

        return success_envelope(
            summary=f"{summary_prefix} {len(selected)} pazar yeri bulundu; ilk {len(data)} gösteriliyor.",
            data=data,
            sources=[sources.MARKET],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.city_layer_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[*LIMITS, *limits],
            warnings=warnings,
            next_queries=["Belirli bir ilçe için district parametresi kullanın."],
            matched=len(selected),
        )
