from __future__ import annotations

from typing import Any

from app.connectors.eshot import EshotConnector
from app.connectors.http import SourceRateLimitedError, SourceTimeoutError
from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.geo import haversine_m, normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_radius
from app.services import sources

ARRIVAL_LIMITS = [
    "Varış verisi dakika/ETA yayımlamaz; yalnızca kalan durak sayısı ve anlık araç konumu vardır.",
    "Kaynak 'yön' alanı için hat güzergâhı doğrulanmadı; değer kaynağın kendi kimliğidir.",
]
STOP_LIMITS = [
    "Durak konumları yayımlanmış listedir; canlı servis durumu değildir.",
    "Yakınlık kuş uçuşu metredir.",
]


def _maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


class BusService:
    def __init__(self, *, settings: Settings, api: EshotConnector | None = None):
        self.settings = settings
        self.api = api or EshotConnector(settings=settings)

    async def stops(
        self,
        *,
        query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        uses_coordinates = lat is not None or lon is not None
        if query is not None and uses_coordinates:
            raise InputValidationError(
                "use either query or lat/lon, not both", field="query"
            )
        if query is None and not uses_coordinates:
            raise InputValidationError(
                "supply query or lat/lon (radius_m only applies to lat/lon)", field="query"
            )
        if uses_coordinates and (lat is None or lon is None):
            raise InputValidationError("lat and lon must be supplied together", field="lat")
        if lat is not None and lon is not None:
            validate_lat_lon(lat, lon)
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

        try:
            rows, info = await self.api.stops()
        except Exception as exc:
            return _source_error(
                "EShot durak listesi kullanılamıyor.", exc, [sources.ESHOT_STOPS]
            )
        limits = [f"limit={safe_limit}"]

        if query is not None:
            needle = normalize_name(query)
            if not needle:
                raise InputValidationError("query must contain a name", field="query")
            matched = [
                {**row, "maps_url": _maps_url(row["lat"], row["lon"])}
                for row in rows
                if needle in normalize_name(f"{row.get('name') or ''} {row.get('id')}")
            ]
            matched.sort(key=lambda row: (row.get("name") or "", row["id"]))
            limits.append(f"query={query.strip()[:80]}")
            summary = f"{len(matched)} durak '{query.strip()[:40]}' ile eşleşti; ilk {min(len(matched), safe_limit)} gösteriliyor."
        else:
            safe_radius = validate_radius(
                1_000 if radius_m is None else radius_m, self.settings.max_radius_m
            )
            matched = []
            for row in rows:
                distance = haversine_m(lat, lon, row["lat"], row["lon"])
                if distance > safe_radius:
                    continue
                matched.append(
                    {**row, "distance_m": distance, "maps_url": _maps_url(row["lat"], row["lon"])}
                )
            matched.sort(key=lambda row: (row["distance_m"], row.get("name") or ""))
            limits.extend([f"radius_m={safe_radius}", f"lat={lat:.5f}", f"lon={lon:.5f}"])
            summary = f"{len(matched)} durak {safe_radius} m içinde bulundu; ilk {min(len(matched), safe_limit)} gösteriliyor."

        data = matched[:safe_limit]
        return success_envelope(
            summary=summary,
            data=data,
            sources=[sources.ESHOT_STOPS],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.eshot_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[*STOP_LIMITS, *limits],
            warnings=[
                "Hat listesi durağın kendi satırındaki duraktan geçen hatlardır; "
                "güncel servis garantisi değildir.",
            ],
            next_queries=["Canlı yaklaşan araçlar için izmir_bus_arrivals(stop_id=...) kullanın."],
            matched=len(matched),
        )

    async def arrivals(self, *, stop_id: str, limit: int | None = None) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        try:
            stop_rows, stop_info = await self.api.stops()
        except Exception as exc:
            return _source_error(
                "EShot durak listesi olmadan varış doğrulanamıyor.", exc, [sources.ESHOT_STOPS]
            )
        known = {row["id"]: row for row in stop_rows}
        stop = known.get(stop_id)
        if stop is None:
            suggestions = _suggest(stop_rows, stop_id)
            raise InputValidationError(
                "stop_id is not in the published EShot stop list"
                + (f"; closest known ids: {', '.join(suggestions)}" if suggestions else ""),
                field="stop_id",
            )

        try:
            rows, info = await self.api.arrivals(stop_id)
        except Exception as exc:
            return _source_error(
                "EShot yaklaşan otobüs servisi kullanılamıyor.",
                exc,
                [sources.ESHOT_ARRIVALS, sources.ESHOT_STOPS],
            )
        ranked = sorted(
            rows,
            key=lambda row: (
                row["stops_remaining"] if isinstance(row["stops_remaining"], int) else 10**6,
                str(row.get("line") or ""),
            ),
        )
        data = []
        for row in ranked[:safe_limit]:
            enriched = {**row, "stop_id": stop_id, "stop_name": stop.get("name")}
            if row.get("lat") is not None and row.get("lon") is not None:
                enriched["maps_url"] = _maps_url(row["lat"], row["lon"])
                enriched["distance_to_stop_m"] = haversine_m(
                    row["lat"], row["lon"], stop["lat"], stop["lon"]
                )
            data.append(enriched)

        warnings = list(ARRIVAL_LIMITS)
        if not rows:
            warnings.append(
                "Kaynak bu durak için yaklaşan otobüs döndürmedi. Bu yanıt 'sefer yok' "
                "kanıtı değildir; kaynak 200 ve boş dizi de dönebilir."
            )
        return success_envelope(
            summary=(
                f"{len(data)} otobüs {stop.get('name') or stop_id} durağına yaklaşıyor."
                if data
                else f"{stop.get('name') or stop_id} durağı için yaklaşan otobüs döndürmedi."
            ),
            data=data,
            sources=[sources.ESHOT_ARRIVALS, sources.ESHOT_STOPS],
            freshness=Freshness(
                status="stale" if "stale" in (info.status, stop_info.status) else "fresh",
                ttl_seconds=self.settings.iztek_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[
                *ARRIVAL_LIMITS,
                f"stop_id={stop_id}",
                f"limit={safe_limit}",
            ],
            warnings=warnings,
            next_queries=["Hat tarifesi için izmir_bus_routes(query=<hat no>) kullanın."],
            matched=len(rows),
        )

    async def routes(self, *, query: str | None = None, limit: int | None = None) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        if query is not None and not str(query).strip():
            raise InputValidationError("query must not be blank", field="query")
        try:
            gtfs, info = await self.api.gtfs()
        except Exception as exc:
            return _source_error(
                "EShot GTFS arşivi okunamadı.", exc, [sources.ESHOT_GTFS]
            )
        routes = gtfs.get("routes", [])
        calendar_end = gtfs.get("calendar_end")

        if query is not None:
            needle = normalize_name(query)
            matched = [
                row
                for row in routes
                if needle in normalize_name(
                    f"{row.get('short_name') or ''} {row.get('long_name') or ''} {row.get('route_id')}"
                )
            ]
        else:
            matched = list(routes)
        matched.sort(key=lambda row: (row.get("short_name") or row.get("route_id") or "",))
        data = [{**row, "calendar_end": calendar_end} for row in matched[:safe_limit]]

        warnings = [
            "Bu, yayımlanmış EShot GTFS tarifesidir; canlı kalkış, gecikme veya ETA değildir.",
            "GTFS dosyası kalkış saatleri (`stop_times.txt`) istek anında okunmaz; hat ve sefer sayıları özetlenir.",
        ]
        today = _today_iso()
        if calendar_end and today and today > calendar_end:
            warnings.append(
                f"EShot GTFS servis takvimi {calendar_end} tarihinde bitiyor; "
                f"doğrulama tarihi {today}. Tarife güncel olmayabilir."
            )
        if calendar_end is None:
            warnings.append("GTFS takvim penceresi okunamadı; güncellik doğrulanamadı.")

        return success_envelope(
            summary=(
                f"{len(data)} hat listelendi; GTFS takvim bitişi {calendar_end or 'bilinmiyor'}."
            ),
            data=data,
            sources=[sources.ESHOT_GTFS],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.eshot_gtfs_cache_ttl_seconds,
                source_updated_at=calendar_end,
            ),
            limits=[
                f"limit={safe_limit}",
                f"gtfs_calendar_end={calendar_end}",
                "Kaynak: yayımlanmış GTFS ZIP (routes/trips/calendar only).",
                *( [f"query={query.strip()[:80]}"] if query is not None else [] ),
            ],
            warnings=warnings,
            next_queries=[
                "Canlı araç konumu için izmir_bus_arrivals(stop_id=...) kullanın.",
                "GTFS kalkış saatleri bu araçta yayımlanmaz; yalnızca hat özeti vardır.",
            ],
            matched=len(matched),
        )


def _today_iso() -> str:
    from datetime import date

    return date.today().isoformat()


def _suggest(rows: list[dict[str, Any]], stop_id: str) -> list[str]:
    digits = "".join(character for character in stop_id if character.isdigit())
    if not digits:
        return [row["id"] for row in rows[:3]]
    prefix = digits[:4]
    return [row["id"] for row in rows if row["id"].startswith(prefix)][:3]


def _source_error(summary: str, exc: Exception, used: list[Source]) -> dict[str, Any]:
    if isinstance(exc, SourceRateLimitedError):
        code = "source_rate_limited"
    elif isinstance(exc, SourceTimeoutError):
        code = "source_timeout"
    else:
        code = "source_unavailable"
    return error_envelope(
        summary=summary,
        warning=f"Kaynak isteği başarısız oldu: {type(exc).__name__}. Veri üretilmedi.",
        code=code,
        sources=used,
    )
