from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.connectors.eshot import EshotConnector
from app.connectors.http import SourceRateLimitedError, SourceTimeoutError
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.envelope import (
    Freshness,
    Source,
    error_envelope,
    result_info,
    success_envelope,
)
from app.core.geo import haversine_m, normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_radius
from app.services import sources
from app.storage.gtfs_schedule import GtfsScheduleError, GtfsScheduleStore

ISTANBUL = ZoneInfo("Europe/Istanbul")
_schedule_lock = asyncio.Lock()


class _ScheduleUnavailable(Exception):
    """The local timetable store could not be built or refreshed."""

    def __init__(self, envelope: dict[str, Any]):
        super().__init__(envelope.get("summary") or "timetable unavailable")
        self.envelope = envelope

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

    async def routes(
        self,
        *,
        query: str | None = None,
        detail: bool = False,
        direction: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List EShot GTFS routes, or fully detail one line when ``detail``."""
        if detail:
            return await self._route_detail(query=query, direction=direction, limit=limit)
        if direction is not None:
            raise InputValidationError(
                "direction is only supported with detail=true", field="direction"
            )
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
            "Bu araç hat ve sefer sayılarını özetler; planlı durak kalkışları için izmir_bus_departures kullanın.",
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
                "Planlı kalkış saatleri için izmir_bus_departures(stop_id=...) kullanın.",
            ],
            matched=len(matched),
        )

    async def _route_detail(
        self, *, query: str | None, direction: str | None, limit: int | None
    ) -> dict[str, Any]:
        resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        text = str(query or "").strip()
        if not text:
            raise InputValidationError(
                "detail=true requires query with a line code (for example 304)", field="query"
            )
        wanted_direction = None
        if direction is not None:
            wanted_direction = str(direction).strip()
            if wanted_direction not in {"0", "1"}:
                raise InputValidationError("direction must be 0 or 1", field="direction")

        try:
            store, meta, stale_reason = await self._open_schedule()
        except _ScheduleUnavailable as failure:
            return failure.envelope

        try:
            matches = await asyncio.to_thread(store.find_routes, text)
        except (GtfsScheduleError, OSError) as exc:
            return _source_error(
                "Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS]
            )
        if not matches:
            raise InputValidationError(
                "line is not in the published GTFS route table", field="query"
            )
        if len(matches) > 1:
            route_ids = ", ".join(str(row["route_id"]) for row in matches)
            raise InputValidationError(
                f"line '{text}' matches multiple GTFS routes ({route_ids}); "
                "use the route_id to disambiguate",
                field="query",
            )

        route = matches[0]
        try:
            payload = await asyncio.to_thread(store.route_detail, route["route_id"])
        except (GtfsScheduleError, OSError) as exc:
            return _source_error(
                "Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS]
            )

        directions = payload["directions"]
        if wanted_direction is not None:
            available = [row["direction_id"] for row in directions]
            if wanted_direction not in available:
                labels = [value or "unknown" for value in available]
                raise InputValidationError(
                    f"direction {wanted_direction} is not published for this line"
                    + (f"; available: {', '.join(labels)}" if labels else ""),
                    field="direction",
                )
            directions = [
                row for row in directions if row["direction_id"] == wanted_direction
            ]

        calendar_end = meta.get("calendar_end") or None
        calendar_start = meta.get("calendar_start") or None
        today = datetime.now(ISTANBUL).date().isoformat()
        stale = bool(stale_reason)
        warnings = [
            "Bu, EShot'un yayımlanmış GTFS tarifesidir; canlı kalkış, gecikme veya ETA değildir.",
            "Durak listesi yayımlanmış seferlerin gerçek sırasıdır; aynı yönde birden çok "
            "durak varyantı ayrı tutulur, tek bir güzergâhta birleştirilmez.",
        ]
        if stale_reason:
            warnings.append(stale_reason)
        if calendar_end and today > calendar_end:
            warnings.append(
                f"EShot GTFS servis takvimi {calendar_end} tarihinde bitiyor (bugün {today}); "
                "hat ve durak yapısı yayımlanmış son tarifedir, güncel servis garantisi değildir."
            )
            stale = True
        if calendar_end is None:
            warnings.append("GTFS takvim penceresi okunamadı; güncellik doğrulanamadı.")
        if any(not row["headsigns"] for row in directions):
            warnings.append(
                "Kaynak bu hat için trip_headsign yayımlamıyor; yön adı uydurulmadı, "
                "yalnızca kaynağın direction_id değeri verilir."
            )

        data = [
            {
                **payload,
                "directions": directions,
                "calendar_start": calendar_start,
                "calendar_end": calendar_end,
            }
        ]
        pattern_total = sum(row["pattern_count"] for row in directions)
        shown_trips = sum(row["trip_count"] for row in directions)
        summary = (
            f"{payload['line']}"
            + (f" ({payload['route_long_name']})" if payload.get("route_long_name") else "")
            + f": {len(directions)} yönde {pattern_total} durak varyantı, "
            + f"{shown_trips} yayımlanmış sefer; GTFS takvimi "
            + f"{calendar_end or 'bilinmiyor'}."
        )
        return success_envelope(
            summary=summary,
            data=data,
            sources=[sources.ESHOT_GTFS],
            freshness=Freshness(
                status="stale" if stale else "fresh",
                ttl_seconds=self.settings.eshot_gtfs_cache_ttl_seconds,
                source_updated_at=calendar_end,
            ),
            limits=[
                f"detail=true",
                f"route_id={payload['route_id']}",
                f"direction={wanted_direction or 'all'}",
                f"calendar_start={calendar_start or 'bilinmiyor'}",
                f"calendar_end={calendar_end or 'bilinmiyor'}",
                "realtime=false",
                "limit uygulanmaz; tüm durak varyantları döner.",
            ],
            warnings=warnings,
            next_queries=[
                f"Planlı kalkış saatleri için izmir_bus_departures(stop_id=..., line={payload['line']}) kullanın.",
                "Canlı yaklaşan araçlar için izmir_bus_arrivals(stop_id=...) kullanın.",
            ],
            matched=1,
            result=result_info(
                returned=1,
                matched=1,
                truncated=False,
                scope="route_detail",
            ),
        )

    async def timetable_status(self) -> dict[str, Any]:
        """Report the local GTFS store without touching the network.

        A missing store is reported as unavailable, never as an empty timetable.
        A loaded store still proves nothing about live arrivals: the published
        calendar may have expired, which is surfaced explicitly.
        """
        settings = self.settings
        store = GtfsScheduleStore(Path(settings.database_path))
        meta = await asyncio.to_thread(store.metadata)
        used = [sources.ESHOT_GTFS]
        if meta is None:
            return error_envelope(
                summary="Yerel GTFS tarife deposu henüz kurulmadı.",
                warning=(
                    "Yerel depo yok veya okunamıyor. Bu 'boş tarife' demek değildir; "
                    "ilk izmir_bus_departures çağrısı depoyu yayımlanmış arşivden kurar."
                ),
                code="source_unavailable",
                sources=used,
                limits=[f"database_path={settings.database_path}"],
            )

        calendar_end = str(meta.get("calendar_end") or "") or None
        today = datetime.now(ISTANBUL).date().isoformat()
        expired = bool(calendar_end and today > calendar_end)
        built_at = meta.get("built_at") or None
        age_seconds = _age_seconds(built_at) if built_at else None
        row = {
            "database_path": settings.database_path,
            "built_at": built_at,
            "feed_published_at": meta.get("feed_published_at") or None,
            "source_url": meta.get("source_url") or None,
            "calendar_start": meta.get("calendar_start") or None,
            "calendar_end": calendar_end,
            "checked_on": today,
            "calendar_expired": expired,
            "built_age_seconds": round(age_seconds) if age_seconds not in (None, float("inf")) else None,
            "zip_bytes": meta.get("zip_bytes"),
            "stops_rows": meta.get("stops_rows"),
            "routes_rows": meta.get("routes_rows"),
            "trips_rows": meta.get("trips_rows"),
            "stop_times_rows": meta.get("stop_times_rows"),
            "skipped_stop_times": meta.get("skipped_stop_times"),
        }

        warnings = [
            "Bu araç yayımlanmış GTFS tarifesinin yerel kopyasını raporlar; canlı "
            "kalkış, gecikme veya araç konumu değildir.",
            "Depo yaşı ile feed'in yayım yaşı aynı şey değildir.",
        ]
        if expired:
            warnings.append(
                f"GTFS servis takvimi {calendar_end} tarihinde bitti; bugün {today}. "
                "Kalkış sorguları bu pencere dışında planlı sefer döndürmez."
            )
        if age_seconds is not None and age_seconds > settings.eshot_gtfs_cache_ttl_seconds:
            warnings.append(
                "Yerel depo tazelik eşiğini aştı; sonraki kalkış sorgusu yeniden kurmayı dener."
            )

        return success_envelope(
            summary=(
                f"Yerel GTFS deposu hazır: {row['stop_times_rows'] or '?'} stop_times satırı, "
                f"takvim {row['calendar_start'] or '?'} → {calendar_end or '?'}"
                + (" (süresi geçmiş)." if expired else ".")
            ),
            data=[row],
            sources=used,
            freshness=Freshness(
                status="stale" if expired else "fresh",
                ttl_seconds=settings.eshot_gtfs_cache_ttl_seconds,
                source_updated_at=calendar_end,
            ),
            limits=[
                f"database_path={settings.database_path}",
                f"gtfs_calendar_end={calendar_end or 'unknown'}",
                "Ağa çıkılmaz; depo yeniden kurulmaz.",
            ],
            warnings=warnings,
            next_queries=["Planlı kalkışlar için izmir_bus_departures kullanın."],
        )

    async def _open_schedule(self) -> tuple[GtfsScheduleStore, dict[str, Any], str | None]:
        """Return the timetable store and metadata, rebuilding it when stale."""
        store = GtfsScheduleStore(Path(self.settings.database_path))
        meta = store.metadata()
        age = _age_seconds(meta.get("built_at")) if meta else float("inf")
        stale_reason: str | None = None
        if meta is None or age > self.settings.eshot_gtfs_cache_ttl_seconds:
            async with _schedule_lock:
                meta = store.metadata()
                age = _age_seconds(meta.get("built_at")) if meta else float("inf")
                if meta is None or age > self.settings.eshot_gtfs_cache_ttl_seconds:
                    try:
                        archive = await self.api.gtfs_archive()
                        meta = await asyncio.to_thread(
                            store.rebuild,
                            archive,
                            source_url=self.settings.eshot_gtfs_url,
                            max_rows=self.settings.eshot_gtfs_max_rows,
                            stop_times_max_bytes=self.settings.eshot_gtfs_stop_times_max_bytes,
                        )
                    except Exception as exc:
                        if (
                            meta is not None
                            and age
                            <= self.settings.eshot_gtfs_cache_ttl_seconds
                            + self.settings.eshot_gtfs_stale_if_error_seconds
                        ):
                            stale_reason = (
                                "GTFS arşivi yenilenemedi; yerel tarife önbelleği kullanıldı "
                                f"({meta.get('built_at') or 'bilinmeyen tarih'})."
                            )
                        else:
                            raise _ScheduleUnavailable(
                                _source_error(
                                    "EShot GTFS tarifesi yerel depoya alınamadı.",
                                    exc,
                                    [sources.ESHOT_GTFS],
                                )
                            ) from exc
        if meta is None:
            raise _ScheduleUnavailable(
                _source_error(
                    "EShot GTFS tarifesi yerel depoya alınamadı.",
                    GtfsScheduleError("timetable database is not built"),
                    [sources.ESHOT_GTFS],
                )
            )
        return store, meta, stale_reason

    async def departures(
        self,
        *,
        stop_id: str,
        at: str | None = None,
        line: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return published GTFS departures from one stop from ``at`` onwards."""
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        sid = str(stop_id or "").strip()
        if not sid:
            raise InputValidationError("stop_id is required", field="stop_id")
        when = _parse_departure_at(at)
        wanted_line = None
        if line is not None:
            wanted_line = str(line).strip()
            if not wanted_line:
                raise InputValidationError("line must not be blank", field="line")

        try:
            stop_rows, stop_info = await self.api.stops()
        except Exception as exc:
            return _source_error(
                "EShot durak listesi olmadan kalkışlar doğrulanamıyor.",
                exc,
                [sources.ESHOT_STOPS],
            )
        stop = next((row for row in stop_rows if row["id"] == sid), None)
        if stop is None:
            suggestions = _suggest(stop_rows, sid)
            raise InputValidationError(
                "stop_id is not in the published EShot stop list"
                + (f"; closest known ids: {', '.join(suggestions)}" if suggestions else ""),
                field="stop_id",
            )

        try:
            store, meta, stale_reason = await self._open_schedule()
        except _ScheduleUnavailable as failure:
            return failure.envelope

        try:
            rows = await asyncio.to_thread(
                store.departures,
                stop_id=sid,
                at=when,
                limit=safe_limit,
                line=wanted_line,
            )
        except GtfsScheduleError as exc:
            if "not in the GTFS stop table" in str(exc):
                raise InputValidationError(
                    "stop_id is in the published EShot list but has no stop_times "
                    "in the current GTFS timetable",
                    field="stop_id",
                ) from exc
            return _source_error(
                "Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS]
            )
        except OSError as exc:
            return _source_error(
                "Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS]
            )

        truncated = len(rows) > safe_limit
        data = rows[:safe_limit]
        calendar_end = meta.get("calendar_end") or None
        calendar_start = meta.get("calendar_start") or None
        query_day = when.date().isoformat()
        today = datetime.now(ISTANBUL).date().isoformat()
        stale = bool(stale_reason) or stop_info.status == "stale"
        warnings = [
            "Bu, EShot'un yayımlanmış GTFS tarifesidir; canlı kalkış, gecikme veya ETA değildir.",
        ]
        if stale_reason:
            warnings.append(stale_reason)
        if calendar_end and query_day > calendar_end:
            warnings.append(
                f"EShot GTFS servis takvimi {calendar_end} tarihinde bitiyor; {query_day} "
                "yayımlanmış servis penceresinin dışında. Bu tarih için kalkış üretilmedi."
            )
            stale = True
        elif calendar_end and today > calendar_end:
            warnings.append(
                f"EShot GTFS servis takvimi {calendar_end} tarihinde bitiyor (bugün {today}); "
                "tarife güncel olmayabilir."
            )
            stale = True
        if calendar_start and query_day < calendar_start:
            warnings.append(
                f"{query_day} yayımlanmış GTFS takviminin ({calendar_start}) başlangıcından önce."
            )
            stale = True
        if not data:
            warnings.append(
                "Bu durak ve tarih için planlı kalkış bulunamadı; bu canlı sefer "
                "yokluğunun kanıtı değildir."
            )

        stop_name = stop.get("name") or sid
        if data:
            first = data[0]
            summary = (
                f"{stop_name} durağından {len(data)} planlı kalkış; ilk {first['time']} "
                f"({first['line']}). GTFS takvimi {calendar_end or 'bilinmiyor'}."
            )
        elif calendar_end and query_day > calendar_end:
            summary = (
                f"{stop_name} için {query_day}: GTFS takvimi {calendar_end} tarihinde "
                "bittiği için yayımlanmış kalkış yok."
            )
        else:
            summary = f"{stop_name} için {query_day} tarihinde planlı kalkış bulunamadı."
        matched = None if truncated else len(rows)
        return success_envelope(
            summary=summary,
            data=data,
            sources=[sources.ESHOT_GTFS, sources.ESHOT_STOPS],
            freshness=Freshness(
                status="stale" if stale else "fresh",
                ttl_seconds=self.settings.eshot_gtfs_cache_ttl_seconds,
                source_updated_at=calendar_end,
            ),
            limits=[
                f"stop_id={sid}",
                f"service_date={query_day}",
                f"calendar_start={calendar_start or 'bilinmiyor'}",
                f"calendar_end={calendar_end or 'bilinmiyor'}",
                f"limit={safe_limit}",
                "realtime=false",
                *( [f"line={wanted_line}"] if wanted_line else [] ),
            ],
            warnings=warnings,
            next_queries=[
                f"Canlı yaklaşan araçlar için izmir_bus_arrivals(stop_id={sid}) kullanın.",
                "Durak kimliğini doğrulamak için izmir_bus_stops(query=...) kullanın.",
            ],
            matched=matched,
            result=result_info(
                returned=len(data),
                matched=matched,
                truncated=truncated,
                scope="published_departures",
            ),
        )


def _parse_departure_at(value: str | None, *, now: datetime | None = None) -> datetime:
    current = now.astimezone(ISTANBUL) if now else datetime.now(ISTANBUL)
    if value is None:
        return current
    text = str(value).strip()
    if not text:
        raise InputValidationError("at must not be blank", field="at")
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        hour, minute = (int(part) for part in text.split(":"))
        try:
            return current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError as exc:
            raise InputValidationError("at must be a valid HH:MM time", field="at") from exc
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputValidationError(
            "at must be an ISO-8601 date/time or HH:MM in Europe/Istanbul", field="at"
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ISTANBUL)
    return parsed.astimezone(ISTANBUL)


def _age_seconds(built_at: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(built_at))
    except (TypeError, ValueError):
        return float("inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ISTANBUL)
    return max(0.0, (datetime.now(ISTANBUL) - parsed).total_seconds())


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
    if isinstance(exc, (SourceRateLimitedError, SourceRateLimitExceeded)):
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
