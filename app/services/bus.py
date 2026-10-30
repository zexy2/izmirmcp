from __future__ import annotations

import asyncio
import logging
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
from app.core.geo import haversine_m, maps_url, normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_radius
from app.services import sources
from app.storage.gtfs_schedule import GtfsScheduleError, GtfsScheduleStore

ISTANBUL = ZoneInfo("Europe/Istanbul")
_schedule_lock = asyncio.Lock()
logger = logging.getLogger("izmir_mcp.gtfs")


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


FUZZY_THRESHOLD = 0.82
FUZZY_MAX_CANDIDATES = 5000
# Radius departures query the nearest stops only: a 5 km search across Konak
# would otherwise fan one answer out into hundreds of timetable queries.
DEPARTURE_RADIUS_DEFAULT_M = 500
DEPARTURE_RADIUS_STOP_CAP = 25


def _fuzzy_stops(rows: list[dict[str, Any]], needle: str) -> list[dict[str, Any]]:
    """Close-name fallback for a mistyped stop search.

    Weighted towards prefixes so "konakk" finds "Konak" rather than an unrelated
    long name. Results above the threshold only; an empty list is a valid answer.
    """
    from difflib import SequenceMatcher

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows[:FUZZY_MAX_CANDIDATES]:
        name = normalize_name(row.get("name") or "")
        if not name:
            continue
        ratio = SequenceMatcher(None, needle, name).ratio()
        if name.startswith(needle[: max(3, len(needle) - 1)]):
            ratio = max(ratio, ratio * 0.5 + 0.4)
        if ratio >= FUZZY_THRESHOLD:
            scored.append(
                (
                    ratio,
                    {**row, "match": "fuzzy", "_score": round(ratio, 3), "maps_url": maps_url(row["lat"], row["lon"])},
                )
            )
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("name") or ""))
    return [row for _score, row in scored]


def _name_rank(name: str | None, needle: str) -> int:
    """0 for an identical name, 1 for a prefix, 2 for an inner substring.

    Without this an exact name ("Konak") is buried under longer stops that
    merely contain it ("Güzel Konak"), which makes a name search look wrong
    even though every row is a real match.
    """
    normalized = normalize_name(name or "")
    if normalized == needle:
        return 0
    if normalized.startswith(needle):
        return 1
    return 2


def _match_stop_query(rows: list[dict[str, Any]], needle: str) -> list[dict[str, Any]]:
    """Exact substring hits first, then labelled fuzzy suggestions.

    Shared by ``izmir_bus_stops(query=...)`` and the departures name-discovery
    mode so both surfaces label an exact hit and a typo guess identically.
    """
    matched = [
        {**row, "match": "exact", "maps_url": maps_url(row["lat"], row["lon"])}
        for row in rows
        if needle in normalize_name(f"{row.get('name') or ''} {row.get('id')}")
    ]
    if not matched:
        matched = _fuzzy_stops(rows, needle)
    matched.sort(
        key=lambda row: (
            row.get("match") != "exact",
            _name_rank(row.get("name"), needle) if row.get("match") == "exact" else 0,
            -row.get("_score", 0.0),
            row.get("name") or "",
        )
    )
    for row in matched:
        row.pop("_score", None)
    return matched


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
            raise InputValidationError("query ile lat/lon'dan yalnızca birini kullanın", field="query")
        if query is None and not uses_coordinates:
            raise InputValidationError(
                "query veya lat/lon verin (radius_m yalnızca lat/lon ile geçerlidir)", field="query"
            )
        if uses_coordinates and (lat is None or lon is None):
            raise InputValidationError("lat ve lon birlikte verilmelidir", field="lat")
        if lat is not None and lon is not None:
            validate_lat_lon(lat, lon)
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

        try:
            rows, info = await self.api.stops()
        except Exception as exc:
            return _source_error("EShot durak listesi kullanılamıyor.", exc, [sources.ESHOT_STOPS])
        limits = [f"limit={safe_limit}"]

        if query is not None:
            needle = normalize_name(query)
            if not needle:
                raise InputValidationError("query bir ad içermelidir", field="query")
            # A single-letter typo ("Konakk") must not return nothing; fuzzy
            # suggestions are labelled so an exact hit is distinguishable.
            matched = _match_stop_query(rows, needle)
            limits.append(f"query={query.strip()[:80]}")
            if matched and matched[0].get("match") == "fuzzy":
                limits.append(f"query={query.strip()[:60]} (fuzzy)")
            summary = f"{len(matched)} durak '{query.strip()[:40]}' ile eşleşti; ilk {min(len(matched), safe_limit)} gösteriliyor."
        else:
            # Both are set here: the guards above reject a lone lat or lon.
            assert lat is not None and lon is not None
            safe_radius = validate_radius(1_000 if radius_m is None else radius_m, self.settings.max_radius_m)
            matched = []
            for row in rows:
                distance = haversine_m(lat, lon, row["lat"], row["lon"])
                if distance > safe_radius:
                    continue
                matched.append({**row, "distance_m": distance, "maps_url": maps_url(row["lat"], row["lon"])})
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
                "Hat listesi durağın kendi satırındaki duraktan geçen hatlardır; güncel servis garantisi değildir.",
            ],
            next_queries=["Canlı yaklaşan araçlar için izmir_bus_arrivals(stop_id=...) kullanın."],
            matched=len(matched),
        )

    async def arrivals(self, *, stop_id: str, limit: int | None = None) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        try:
            stop_rows, stop_info = await self.api.stops()
        except Exception as exc:
            return _source_error("EShot durak listesi olmadan varış doğrulanamıyor.", exc, [sources.ESHOT_STOPS])
        known = {row["id"]: row for row in stop_rows}
        stop = known.get(stop_id)
        if stop is None:
            suggestions = _suggest(stop_rows, stop_id)
            raise InputValidationError(
                "stop_id yayımlanmış EShot durak listesinde yok"
                + (f"; en yakın bilinen id'ler: {', '.join(suggestions)}" if suggestions else ""),
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
                enriched["maps_url"] = maps_url(row["lat"], row["lon"])
                enriched["distance_to_stop_m"] = haversine_m(row["lat"], row["lon"], stop["lat"], stop["lon"])
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

    async def line_live_positions(self, *, line: str, limit: int | None = None) -> dict[str, Any]:
        safe_line = _validate_line(line)
        safe_limit = resolve_limit(limit, self.settings.max_limit, self.settings.max_limit)
        try:
            rows, info = await self.api.line_positions(safe_line)
        except Exception as exc:
            return _source_error(
                "EShot hat otobüs konumu servisi kullanılamıyor.",
                exc,
                [sources.ESHOT_LINE_POSITIONS],
            )
        data = [{**row, "maps_url": maps_url(row["lat"], row["lon"])} for row in rows[:safe_limit]]
        warnings = ["Konumlar anlık araç konumudur; birkaç saniye içinde değişir."]
        if not rows:
            warnings.append("Kaynak bu hat için araç konumu döndürmedi; bu 'hat çalışmıyor' kanıtı değildir.")
        return success_envelope(
            summary=(
                f"{safe_line} hattında {len(data)} otobüsün anlık konumu."
                if data
                else f"{safe_line} hattı için anlık otobüs konumu döndürülmedi."
            ),
            data=data,
            sources=[sources.ESHOT_LINE_POSITIONS],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=15,
                source_updated_at=info.source_updated_at,
            ),
            limits=[
                f"line={safe_line}",
                f"limit={safe_limit}",
                "direction kaynağın Yon alanıdır (0/1); güzergâh yönü doğrulanmadı.",
            ],
            warnings=warnings,
            next_queries=[
                f"Bir duraktaki yaklaşanlar için izmir_bus_line_arrivals(line={safe_line}, stop_id=<durak>) kullanın."
            ],
            matched=len(rows),
        )

    async def line_arrivals(self, *, line: str, stop_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
        """Approaching buses filtered to one line.

        With ``stop_id`` this filters the stop's live arrivals by line. The
        per-line-and-stop İZTEK path returned 404 when probed, so it is not used.
        Without ``stop_id`` there is no stop to approach; the live line
        positions are returned instead.
        """
        safe_line = _validate_line(line)
        if stop_id is None:
            return await self.line_live_positions(line=safe_line, limit=limit)
        envelope = await self.arrivals(stop_id=stop_id, limit=self.settings.max_limit)
        if not envelope.get("ok"):
            return envelope
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        wanted = safe_line.casefold()
        filtered = [row for row in envelope["data"] if str(row.get("line") or "").casefold() == wanted]
        envelope["data"] = filtered[:safe_limit]
        envelope["summary"] = (
            f"{safe_line} hattından {len(envelope['data'])} otobüs {stop_id} durağına yaklaşıyor."
            if envelope["data"]
            else f"{safe_line} hattından {stop_id} durağına yaklaşan otobüs döndürülmedi."
        )
        envelope["limits"] = [*envelope["limits"], f"line={safe_line}"]
        envelope["warnings"] = [
            *envelope["warnings"],
            "Filtre durak yanıtındaki tüm otobüsler üzerinde uygulanır.",
        ]
        envelope["result_info"] = result_info(returned=len(envelope["data"]), matched=len(filtered)).model_dump(
            mode="json"
        )
        return envelope

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
            raise InputValidationError("direction yalnızca detail=true ile desteklenir", field="direction")
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        if query is not None and not str(query).strip():
            raise InputValidationError("query boş olamaz", field="query")
        try:
            gtfs, info = await self.api.gtfs()
        except Exception as exc:
            return _source_error("EShot GTFS arşivi okunamadı.", exc, [sources.ESHOT_GTFS])
        routes = gtfs.get("routes", [])
        calendar_end = gtfs.get("calendar_end")

        if query is not None:
            needle = normalize_name(query)
            matched = [
                row
                for row in routes
                if needle
                in normalize_name(f"{row.get('short_name') or ''} {row.get('long_name') or ''} {row.get('route_id')}")
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
            summary=(f"{len(data)} hat listelendi; GTFS takvim bitişi {calendar_end or 'bilinmiyor'}."),
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
                "Kaynak: yayımlanmış GTFS ZIP (yalnızca routes/trips/calendar).",
                *([f"query={query.strip()[:80]}"] if query is not None else []),
            ],
            warnings=warnings,
            next_queries=[
                "Canlı araç konumu için izmir_bus_arrivals(stop_id=...) kullanın.",
                "Planlı kalkış saatleri için izmir_bus_departures(stop_id=...) kullanın.",
            ],
            matched=len(matched),
        )

    async def _route_detail(self, *, query: str | None, direction: str | None, limit: int | None) -> dict[str, Any]:
        resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        text = str(query or "").strip()
        if not text:
            raise InputValidationError("detail=true için hat kodu içeren query gerekir (örn. 304)", field="query")
        wanted_direction = None
        if direction is not None:
            wanted_direction = str(direction).strip()
            if wanted_direction not in {"0", "1"}:
                raise InputValidationError("direction 0 veya 1 olmalıdır", field="direction")

        try:
            store, meta, stale_reason = await self._open_schedule()
        except _ScheduleUnavailable as failure:
            return failure.envelope

        try:
            matches = await asyncio.to_thread(store.find_routes, text)
        except (GtfsScheduleError, OSError) as exc:
            return _source_error("Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS])
        if not matches:
            raise InputValidationError("line yayımlanmış GTFS hat tablosunda yok", field="query")
        if len(matches) > 1:
            route_ids = ", ".join(str(row["route_id"]) for row in matches)
            raise InputValidationError(
                f"line '{text}' birden çok GTFS hattıyla eşleşiyor ({route_ids}); ayırmak için route_id kullanın",
                field="query",
            )

        route = matches[0]
        try:
            payload = await asyncio.to_thread(store.route_detail, route["route_id"])
        except (GtfsScheduleError, OSError) as exc:
            return _source_error("Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS])

        directions = payload["directions"]
        if wanted_direction is not None:
            available = [row["direction_id"] for row in directions]
            if wanted_direction not in available:
                labels = [value or "unknown" for value in available]
                raise InputValidationError(
                    f"direction {wanted_direction} bu hat için yayımlanmamış"
                    + (f"; mevcut: {', '.join(labels)}" if labels else ""),
                    field="direction",
                )
            directions = [row for row in directions if row["direction_id"] == wanted_direction]

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
        store = GtfsScheduleStore(Path(settings.gtfs_database_path))
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
                limits=[f"gtfs_database_path={settings.gtfs_database_path}"],
            )

        calendar_end = str(meta.get("calendar_end") or "") or None
        today = datetime.now(ISTANBUL).date().isoformat()
        expired = bool(calendar_end and today > calendar_end)
        built_at = meta.get("built_at") or None
        age_seconds = _age_seconds(built_at) if built_at else None
        row = {
            "gtfs_database_path": settings.gtfs_database_path,
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
            warnings.append("Yerel depo tazelik eşiğini aştı; sonraki kalkış sorgusu yeniden kurmayı dener.")

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
                f"gtfs_database_path={settings.gtfs_database_path}",
                f"gtfs_calendar_end={calendar_end or 'unknown'}",
                "Ağa çıkılmaz; depo yeniden kurulmaz.",
            ],
            warnings=warnings,
            next_queries=["Planlı kalkışlar için izmir_bus_departures kullanın."],
        )

    async def _open_schedule(self) -> tuple[GtfsScheduleStore, dict[str, Any], str | None]:
        """Return the timetable store and metadata, rebuilding it when stale."""
        store = GtfsScheduleStore(Path(self.settings.gtfs_database_path))
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
                        # Keep the type and message in server logs; the public
                        # envelope stays generic and never leaks a path.
                        logger.warning("GTFS rebuild failed: %s: %s", type(exc).__name__, exc)
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
        stop_id: str | None = None,
        stop_query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int | None = None,
        at: str | None = None,
        line: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return departures for one stop, or for every published stop near a point.

        Exactly one target mode is accepted: ``stop_id``, ``stop_query`` (name
        discovery that returns stops, never departures) or ``lat``/``lon`` with
        an optional ``radius_m`` (default 500 m, nearest 25 stops).
        """
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        sid = str(stop_id).strip() if stop_id is not None else None
        if sid == "":
            raise InputValidationError("stop_id boş olamaz", field="stop_id")
        needle = str(stop_query).strip() if stop_query is not None else None
        uses_coordinates = lat is not None or lon is not None

        if needle is not None and (sid is not None or uses_coordinates):
            raise InputValidationError(
                "stop_id, stop_query veya lat/lon'dan tam olarak birini kullanın", field="stop_query"
            )
        if sid is not None and uses_coordinates:
            raise InputValidationError(
                "stop_id, stop_query veya lat/lon'dan tam olarak birini kullanın", field="stop_id"
            )
        if needle is None and sid is None and not uses_coordinates:
            raise InputValidationError("stop_id, stop_query veya lat/lon verin", field="stop_id")
        if radius_m is not None and not uses_coordinates:
            raise InputValidationError("radius_m yalnızca lat/lon ile geçerlidir", field="radius_m")
        if uses_coordinates and (lat is None or lon is None):
            raise InputValidationError("lat ve lon birlikte verilmelidir", field="lat")

        wanted_line = None
        if line is not None:
            wanted_line = str(line).strip()
            if not wanted_line:
                raise InputValidationError("line boş olamaz", field="line")
            if needle is not None:
                raise InputValidationError("line, durak adı aramasını filtreleyemez", field="line")
        if needle is not None:
            if at is not None:
                raise InputValidationError(
                    "at, durak adı aramasını filtreleyemez; bu mod kalkışları değil durakları döndürür",
                    field="at",
                )
            return await self._departure_stop_candidates(needle, safe_limit)

        when = _parse_departure_at(at)

        try:
            stop_rows, stop_info = await self.api.stops()
        except Exception as exc:
            return _source_error(
                "EShot durak listesi olmadan kalkışlar doğrulanamıyor.",
                exc,
                [sources.ESHOT_STOPS],
            )

        distances: dict[str, float] = {}
        stop_count: int | None = None
        extra_limits: list[str] = []
        extra_warnings: list[str] = []
        if sid is not None:
            stop = next((row for row in stop_rows if row["id"] == sid), None)
            if stop is None:
                suggestions = _suggest(stop_rows, sid)
                raise InputValidationError(
                    "stop_id yayımlanmış EShot durak listesinde yok"
                    + (f"; en yakın bilinen id'ler: {', '.join(suggestions)}" if suggestions else ""),
                    field="stop_id",
                )
            query_stops = [stop]
        else:
            # Both are set here: the guards above reject a lone lat or lon.
            assert lat is not None and lon is not None
            validate_lat_lon(lat, lon)
            safe_radius = validate_radius(
                DEPARTURE_RADIUS_DEFAULT_M if radius_m is None else radius_m,
                self.settings.max_radius_m,
            )
            candidates = []
            for row in stop_rows:
                distance = haversine_m(lat, lon, row["lat"], row["lon"])
                if distance <= safe_radius:
                    candidates.append((distance, row))
            candidates.sort(key=lambda pair: (pair[0], pair[1].get("name") or ""))
            extra_limits.extend(
                [
                    "mode=radius",
                    f"radius_m={safe_radius}",
                    f"lat={lat:.5f}",
                    f"lon={lon:.5f}",
                ]
            )
            if not candidates:
                return success_envelope(
                    summary=(f"{safe_radius} m içinde yayımlanmış EShot durağı yok; kalkış sorgusu yapılmadı."),
                    data=[],
                    sources=[sources.ESHOT_STOPS],
                    freshness=Freshness(
                        status=stop_info.status,
                        ttl_seconds=self.settings.eshot_cache_ttl_seconds,
                        source_updated_at=stop_info.source_updated_at,
                    ),
                    limits=[*extra_limits, f"limit={safe_limit}"],
                    warnings=[
                        "Yarıçap içinde yayımlanmış durak bulunamadı; bu 'sefer yok' "
                        "kanıtı değildir ve tarife deposu açılmadı.",
                        *extra_warnings,
                    ],
                    next_queries=[
                        "Yarıçapı büyütün veya izmir_bus_stops ile durak listesini kontrol edin.",
                    ],
                    result=result_info(
                        returned=0,
                        matched=0,
                        truncated=False,
                        scope="published_departures_near",
                    ),
                )
            selected = candidates[:DEPARTURE_RADIUS_STOP_CAP]
            if len(candidates) > DEPARTURE_RADIUS_STOP_CAP:
                extra_warnings.append(
                    f"Yarıçapta {len(candidates)} durak var; en yakın {DEPARTURE_RADIUS_STOP_CAP} durak sorgulandı."
                )
            distances = {row["id"]: distance for distance, row in selected}
            query_stops = [row for _distance, row in selected]
            stop_count = len(query_stops)
            extra_limits.append(f"stop_count={stop_count}")

        try:
            store, meta, stale_reason = await self._open_schedule()
        except _ScheduleUnavailable as failure:
            return failure.envelope

        try:
            rows = await asyncio.to_thread(
                store.departures_at_stops,
                stop_ids=[row["id"] for row in query_stops],
                at=when,
                limit=safe_limit,
                line=wanted_line,
            )
        except GtfsScheduleError as exc:
            if "not in the GTFS stop table" in str(exc):
                raise InputValidationError(
                    "stop_id yayımlanmış EShot listesinde var ancak geçerli GTFS tarifesinde stop_times kaydı yok",
                    field="stop_id",
                ) from exc
            return _source_error("Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS])
        except OSError as exc:
            return _source_error("Yerel GTFS tarife deposu okunamadı.", exc, [sources.ESHOT_GTFS])

        if distances:
            rows = [{**row, "distance_m": distances.get(row["stop_id"])} for row in rows]
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
            warnings.append(f"{query_day} yayımlanmış GTFS takviminin ({calendar_start}) başlangıcından önce.")
            stale = True
        if not data:
            warnings.append(
                "Bu durak ve tarih için planlı kalkış bulunamadı; bu canlı sefer yokluğunun kanıtı değildir."
            )

        stop_name = query_stops[0].get("name") or query_stops[0]["id"]
        if data:
            first = data[0]
            if stop_count is None:
                summary = (
                    f"{stop_name} durağından {len(data)} planlı kalkış; ilk {first['time']} "
                    f"({first['line']}). GTFS takvimi {calendar_end or 'bilinmiyor'}."
                )
            else:
                summary = (
                    f"Yakındaki {stop_count} duraktan {len(data)} planlı kalkış; ilk "
                    f"{first['time']} ({first['line']}). GTFS takvimi "
                    f"{calendar_end or 'bilinmiyor'}."
                )
        elif calendar_end and query_day > calendar_end:
            scope_label = stop_name if stop_count is None else f"Yakındaki {stop_count} durak"
            summary = (
                f"{scope_label} için {query_day}: GTFS takvimi {calendar_end} tarihinde "
                "bittiği için yayımlanmış kalkış yok."
            )
        elif stop_count is None:
            summary = f"{stop_name} için {query_day} tarihinde planlı kalkış bulunamadı."
        else:
            summary = f"Yakındaki {stop_count} durak için {query_day} tarihinde planlı kalkış bulunamadı."
        matched = None if truncated else len(rows)
        warnings = [*warnings, *extra_warnings]
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
                *([f"stop_id={sid}"] if sid is not None else []),
                f"service_date={query_day}",
                f"calendar_start={calendar_start or 'bilinmiyor'}",
                f"calendar_end={calendar_end or 'bilinmiyor'}",
                f"limit={safe_limit}",
                "realtime=false",
                *([f"line={wanted_line}"] if wanted_line else []),
                *extra_limits,
            ],
            warnings=warnings,
            next_queries=[
                *(
                    [f"Canlı yaklaşan araçlar için izmir_bus_arrivals(stop_id={sid}) kullanın."]
                    if sid is not None
                    else ["Canlı yaklaşan araçlar için izmir_bus_arrivals(stop_id=...) kullanın."]
                ),
                "Durak kimliğini doğrulamak için izmir_bus_stops(query=...) kullanın.",
            ],
            matched=matched,
            result=result_info(
                returned=len(data),
                matched=matched,
                truncated=truncated,
                scope="published_departures" if stop_count is None else "published_departures_near",
            ),
        )

    async def _departure_stop_candidates(self, needle: str, safe_limit: int) -> dict[str, Any]:
        """Name discovery for departures: candidate stops, never a timetable."""
        normalized = normalize_name(needle)
        if not normalized:
            raise InputValidationError("stop_query bir ad içermelidir", field="stop_query")
        try:
            rows, info = await self.api.stops()
        except Exception as exc:
            return _source_error("EShot durak listesi kullanılamıyor.", exc, [sources.ESHOT_STOPS])
        matched = _match_stop_query(rows, normalized)
        data = matched[:safe_limit]
        truncated = len(matched) > len(data)
        warnings = [
            "Bu mod yalnızca durak adayları döndürür; kalkış listesi değildir. "
            "Seçilen stop_id ile izmir_bus_departures çağırın.",
            "Aynı adlı duraklar ayrı satırlardır; ilkini otomatik seçmeyin.",
        ]
        if any(row.get("match") == "fuzzy" for row in data):
            warnings.append("Yakın yazım önerileri 'fuzzy' olarak etiketlendi; eşleşme garantisi değildir.")
        return success_envelope(
            summary=(f"'{needle[:40]}' için {len(data)} durak adayı bulundu; bu mod kalkış döndürmez."),
            data=data,
            sources=[sources.ESHOT_STOPS],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.eshot_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[
                "mode=stop_query",
                f"query={needle[:80]}",
                f"limit={safe_limit}",
            ],
            warnings=warnings,
            next_queries=[
                "Seçilen durak için izmir_bus_departures(stop_id=...) kullanın.",
            ],
            matched=len(matched),
            result=result_info(
                returned=len(data),
                matched=len(matched),
                truncated=truncated,
                scope="stop_candidates",
            ),
        )


def _parse_departure_at(value: str | None, *, now: datetime | None = None) -> datetime:
    current = now.astimezone(ISTANBUL) if now else datetime.now(ISTANBUL)
    if value is None:
        return current
    text = str(value).strip()
    if not text:
        raise InputValidationError("at boş olamaz", field="at")
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        hour, minute = (int(part) for part in text.split(":"))
        try:
            return current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError as exc:
            raise InputValidationError("at geçerli bir HH:MM saati olmalıdır", field="at") from exc
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputValidationError(
            "at ISO-8601 tarih/saat ya da Europe/Istanbul'da HH:MM olmalıdır", field="at"
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


_LINE_PATTERN = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü-]{1,8}")


def _validate_line(line: Any) -> str:
    text = str(line).strip() if isinstance(line, (str, int)) and not isinstance(line, bool) else ""
    if not _LINE_PATTERN.fullmatch(text):
        raise InputValidationError("line 1-8 karakterlik bir EShot hat numarası olmalıdır", field="line")
    return text


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
