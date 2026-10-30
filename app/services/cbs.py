from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.connectors.ibb_cbs import CBS_LAYERS, MARKET_KINDS, IbbCbsConnector
from app.core.envelope import Freshness, Source, success_envelope
from app.core.geo import haversine_m, maps_url, normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_radius
from app.services import sources
from app.services.sources import is_source_failure, source_failure_envelope

ISTANBUL = ZoneInfo("Europe/Istanbul")
HAL_LOOKBACK_DAYS = 7
GEO_LIMITS = [
    "Konumlar yayımlanmış CBS katmanıdır; açık/kapalı durumu değildir.",
    "Yakınlık kuş uçuşu metredir.",
]


def _today() -> date:
    return datetime.now(ISTANBUL).date()


def _failure(exc: BaseException, summary: str, source: Source, limits: list[str]):
    if not is_source_failure(exc):
        raise exc
    return source_failure_envelope(exc, summary=summary, used=[source], limits=limits)


def _fold(text: Any) -> str:
    return normalize_name(str(text or ""))


class CbsService:
    def __init__(self, *, settings: Settings, api: IbbCbsConnector | None = None):
        self.settings = settings
        self.api = api or IbbCbsConnector(settings)

    def _freshness(self, info, ttl: int) -> Freshness:
        return Freshness(status=info.status, ttl_seconds=ttl, source_updated_at=info.source_updated_at)

    def _near(self, rows: list[dict[str, Any]], near_lat, near_lon, radius_m) -> tuple[list[dict[str, Any]], list[str]]:
        if near_lat is None and near_lon is None:
            if radius_m is not None:
                raise InputValidationError("radius_m için near_lat ve near_lon gerekir", field="radius_m")
            return rows, []
        if near_lat is None or near_lon is None:
            raise InputValidationError("near_lat ve near_lon birlikte verilmelidir", field="near_lat")
        validate_lat_lon(near_lat, near_lon)
        radius = validate_radius(radius_m if radius_m is not None else 2_000, self.settings.max_radius_m)
        ranked = []
        for row in rows:
            distance = haversine_m(near_lat, near_lon, row["lat"], row["lon"])
            if distance <= radius:
                ranked.append({**row, "distance_m": distance})
        ranked.sort(key=lambda row: row["distance_m"])
        return ranked, [f"near={near_lat},{near_lon}", f"radius_m={radius}"]

    async def layer(
        self,
        *,
        layer: str,
        near_lat: float | None = None,
        near_lon: float | None = None,
        radius_m: int | None = None,
        district: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        if layer not in CBS_LAYERS:
            raise InputValidationError(
                "layer izin verilen CBS katmanlarından biri olmalıdır (ör. muzeler, hastaneler, plajlar)",
                field="layer",
            )
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        limits = [f"layer={layer}", f"limit={safe_limit}"]
        try:
            rows, info = await self.api.layer(layer)
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, f"CBS katmanı {layer} okunamadı.", sources.CBS_LAYERS, limits)
        if district is not None:
            wanted = _fold(district)
            if not wanted:
                raise InputValidationError("district boş olamaz", field="district")
            rows = [row for row in rows if _fold(row.get("district")) == wanted]
            limits.append(f"district={district}")
        rows, near_limits = self._near(rows, near_lat, near_lon, radius_m)
        limits.extend(near_limits)
        data = [{**row, "maps_url": maps_url(row["lat"], row["lon"])} for row in rows[:safe_limit]]
        return success_envelope(
            summary=f"{layer} katmanından {len(data)} kayıt (toplam eşleşme {len(rows)}).",
            data=data,
            sources=[sources.CBS_LAYERS],
            freshness=self._freshness(info, int(getattr(self.settings, "cbs_cache_ttl_seconds", 86_400))),
            limits=[*limits, *GEO_LIMITS],
            warnings=[] if rows else ["Bu filtrelerle kayıt bulunamadı."],
            matched=len(rows),
        )

    async def events(
        self, *, query: str | None = None, free_only: bool = False, limit: int | None = None
    ) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        limits = [f"limit={safe_limit}"]
        try:
            rows, info = await self.api.events()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "Kültür sanat etkinlikleri okunamadı.", sources.EVENTS, limits)
        if query is not None:
            needle = _fold(query)
            if not needle:
                raise InputValidationError("query boş olamaz", field="query")
            rows = [
                row
                for row in rows
                if needle in _fold(row.get("name"))
                or needle in _fold(row.get("venue"))
                or needle in _fold(row.get("type"))
            ]
            limits.append(f"query={query}")
        if free_only:
            rows = [row for row in rows if row.get("free") is True]
            limits.append("free_only=true")
        rows = sorted(rows, key=lambda row: str(row.get("starts_at") or ""))
        data = rows[:safe_limit]
        return success_envelope(
            summary=f"{len(data)} etkinlik listelendi (toplam eşleşme {len(rows)}).",
            data=data,
            sources=[sources.EVENTS],
            freshness=self._freshness(info, int(getattr(self.settings, "events_cache_ttl_seconds", 3_600))),
            limits=limits,
            warnings=[
                "Etkinlik bilgisi belediyenin yayımladığı listedir; iptal/değişiklik için bağlantıyı kontrol edin."
            ],
            matched=len(rows),
        )

    async def market_prices(
        self,
        *,
        kind: str = "sebzemeyve",
        day: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        if kind not in MARKET_KINDS:
            raise InputValidationError("kind sebzemeyve veya balik olmalıdır", field="kind")
        today = _today()
        if day is None:
            start = today
        else:
            try:
                start = date.fromisoformat(str(day))
            except ValueError as exc:
                raise InputValidationError("day YYYY-AA-GG biçiminde olmalıdır", field="day") from exc
            if start > today:
                raise InputValidationError("day gelecekte olamaz", field="day")
        safe_limit = resolve_limit(limit, self.settings.max_limit, self.settings.max_limit)
        limits = [f"kind={kind}", f"day={start.isoformat()}"]
        bulletin = info = None
        tried = []
        try:
            for offset in range(HAL_LOOKBACK_DAYS):
                candidate = start - timedelta(days=offset)
                tried.append(candidate.isoformat())
                bulletin, info = await self.api.market_prices(kind, candidate.isoformat(), today=candidate == today)
                if bulletin is not None:
                    break
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "Hal fiyatları okunamadı.", sources.HAL_PRICES, limits)
        if bulletin is None:
            return success_envelope(
                summary=f"{tried[-1]} – {tried[0]} arasında yayımlanmış hal bülteni yok.",
                data=[],
                sources=[sources.HAL_PRICES],
                freshness=self._freshness(info, 1_800),
                limits=[*limits, f"lookback_days={HAL_LOOKBACK_DAYS}"],
                warnings=["Kaynak bu günler için 204 (içerik yok) döndürdü; tatil veya hafta sonu olabilir."],
                matched=0,
            )
        rows = bulletin["rows"]
        if query is not None:
            needle = _fold(query)
            if not needle:
                raise InputValidationError("query boş olamaz", field="query")
            rows = [row for row in rows if needle in _fold(row.get("product"))]
            limits.append(f"query={query}")
        warnings = ["Hal (toptan) fiyatlarıdır; perakende fiyatı değildir. Para birimi TL."]
        if bulletin["bulletin_date"] != start.isoformat():
            warnings.append(
                f"{start.isoformat()} için bülten yok; en yakın önceki bülten {bulletin['bulletin_date']} gösteriliyor."
            )
        data = rows[:safe_limit]
        return success_envelope(
            summary=f"{bulletin['bulletin_date']} {kind} hal bülteninden {len(data)} ürün.",
            data=data,
            sources=[sources.HAL_PRICES],
            freshness=self._freshness(info, 1_800),
            limits=[*limits, f"bulletin_date={bulletin['bulletin_date']}"],
            warnings=warnings,
            matched=len(rows),
        )

    async def pharmacies_all(
        self,
        *,
        area: str | None = None,
        query: str | None = None,
        near_lat: float | None = None,
        near_lon: float | None = None,
        radius_m: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        limits = [f"limit={safe_limit}"]
        try:
            rows, info = await self.api.all_pharmacies()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "Eczane listesi okunamadı.", sources.PHARMACY_ALL, limits)
        if area is not None:
            # Bolge is the duty area (e.g. "KARŞIYAKA 4", "ALSANCAK"), not the ilçe.
            wanted = _fold(area)
            if not wanted:
                raise InputValidationError("area boş olamaz", field="area")
            rows = [row for row in rows if wanted in _fold(row.get("area"))]
            limits.append(f"area={area}")
        if query is not None:
            needle = _fold(query)
            if not needle:
                raise InputValidationError("query boş olamaz", field="query")
            rows = [row for row in rows if needle in _fold(row.get("name"))]
            limits.append(f"query={query}")
        rows, near_limits = self._near(rows, near_lat, near_lon, radius_m)
        limits.extend(near_limits)
        data = [{**row, "maps_url": maps_url(row["lat"], row["lon"])} for row in rows[:safe_limit]]
        return success_envelope(
            summary=f"{len(data)} eczane listelendi (toplam eşleşme {len(rows)}).",
            data=data,
            sources=[sources.PHARMACY_ALL],
            freshness=self._freshness(info, int(getattr(self.settings, "pharmacies_all_cache_ttl_seconds", 86_400))),
            limits=[*limits, *GEO_LIMITS],
            warnings=[
                "Bu tam eczane listesidir; bugün nöbetçi olanlar için izmir_nearby(types=['pharmacy']) kullanın."
            ],
            next_queries=["Nöbetçi eczaneler için izmir_nearby(lat, lon, types=['pharmacy']) kullanın."],
            matched=len(rows),
        )
