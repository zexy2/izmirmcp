"""İZBAN fares, parking tariffs, traffic camera locations and IZSU production.

Each answer is a published table, not a live reading: fares and tariffs can
change before the source is updated, camera rows carry no stream, and the IZSU
production resource has no date column at all.
"""

from __future__ import annotations

from typing import Any

from app.connectors.city_layers import CityLayerConnector
from app.connectors.izmir_api import IzmirOpenApi
from app.core.envelope import Freshness, Source, success_envelope
from app.core.geo import haversine_m, normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_radius, validate_text
from app.services import sources
from app.services.sources import is_source_failure, source_failure_envelope

CAMERA_MAX_RADIUS_M = 50_000
CAMERA_DEFAULT_RADIUS_M = 2_000
MAX_STATION_ID = 9_999
AMBIGUOUS_PREVIEW = 5


def _failure(exc: BaseException, summary: str, source: Source, limits: list[str]) -> dict[str, Any]:
    """Typed envelope for a connector failure; programming bugs re-raise."""
    if not is_source_failure(exc):
        raise exc
    return source_failure_envelope(exc, summary=summary, used=[source], limits=limits)


def _freshness(info: Any, ttl: int) -> Freshness:
    return Freshness(status=info.status, ttl_seconds=ttl, source_updated_at=info.source_updated_at)


def _name_filter(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return normalize_name(validate_text(value, field=field, max_length=80))


def _station_id(value: Any, *, field: str) -> int | str:
    """Return a positive int id, or the caller's text for name resolution."""
    if isinstance(value, bool):
        raise InputValidationError(f"{field} istasyon kimliği veya adı olmalıdır", field=field)
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    elif isinstance(value, str):
        return validate_text(value, field=field, max_length=80)
    else:
        raise InputValidationError(f"{field} istasyon kimliği veya adı olmalıdır", field=field)
    if not 1 <= number <= MAX_STATION_ID:
        raise InputValidationError(f"{field} pozitif bir istasyon kimliği olmalıdır", field=field)
    return number


def _resolve_station(value: int | str, stations: list[dict[str, Any]], *, field: str) -> dict[str, Any]:
    known = [row for row in stations if isinstance(row.get("id"), int) and not isinstance(row.get("id"), bool)]
    if isinstance(value, int):
        match = next((row for row in known if row["id"] == value), None)
        if match is None:
            raise InputValidationError(
                f"{field}={value} yayımlanmış İZBAN istasyon listesinde yok; "
                "izmir_transit_stations(mode='izban') ile kimlikleri görün",
                field=field,
            )
        return match
    needle = normalize_name(value)
    exact = [row for row in known if normalize_name(str(row.get("name") or "")) == needle]
    candidates = exact or [row for row in known if needle in normalize_name(str(row.get("name") or ""))]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise InputValidationError(
            f"{field} '{value[:40]}' bir İZBAN istasyonuyla eşleşmedi; "
            "izmir_transit_stations(mode='izban') ile adları görün",
            field=field,
        )
    preview = ", ".join(f"{row.get('name')} ({row['id']})" for row in candidates[:AMBIGUOUS_PREVIEW])
    raise InputValidationError(
        f"{field} '{value[:40]}' birden fazla istasyonla eşleşti: {preview}; kimlik veya tam ad verin",
        field=field,
    )


class CityInfoService:
    def __init__(
        self,
        *,
        settings: Settings,
        api: IzmirOpenApi | None = None,
        layers: CityLayerConnector | None = None,
    ):
        self.settings = settings
        self.api = api or IzmirOpenApi(settings)
        self.layers = layers or CityLayerConnector(settings=settings)

    async def izban_fare(
        self,
        *,
        from_station: int | str,
        to_station: int | str,
        transfer: bool = False,
        htt: bool = False,
    ) -> dict[str, Any]:
        for flag, field in ((transfer, "transfer"), (htt, "htt")):
            if not isinstance(flag, bool):
                raise InputValidationError(f"{field} true veya false olmalıdır", field=field)
        wanted_from = _station_id(from_station, field="from_station")
        wanted_to = _station_id(to_station, field="to_station")
        if isinstance(wanted_from, int) and wanted_from == wanted_to:
            raise InputValidationError("from_station ve to_station farklı istasyonlar olmalıdır", field="to_station")
        try:
            stations, station_info = await self.api.izban_stations()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "İZBAN istasyon listesi okunamadı; ücret doğrulanamıyor.", sources.IZBAN, [])
        start = _resolve_station(wanted_from, stations, field="from_station")
        end = _resolve_station(wanted_to, stations, field="to_station")
        if start["id"] == end["id"]:
            raise InputValidationError("from_station ve to_station farklı istasyonlar olmalıdır", field="to_station")
        limits = [
            f"from_id={start['id']}",
            f"to_id={end['id']}",
            f"transfer={'true' if transfer else 'false'}",
            f"htt={'true' if htt else 'false'}",
        ]
        try:
            fare, info = await self.api.izban_fare(start["id"], end["id"], transfer=transfer, htt=htt)
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "İZBAN ücret hesaplama servisi okunamadı.", sources.IZBAN_FARE, limits)
        row = {"from_id": start["id"], "to_id": end["id"], "transfer": transfer, "htt": htt, **fare}
        full = fare["fares"].get("full")
        return success_envelope(
            summary=(
                f"İZBAN {start.get('name')} → {end.get('name')}: tam {full} TL"
                + (f", {fare['distance_km']} km." if fare.get("distance_km") is not None else ".")
            ),
            data=[row],
            sources=[sources.IZBAN_FARE, sources.IZBAN],
            freshness=Freshness(
                status="stale" if "stale" in (info.status, station_info.status) else info.status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[*limits, "Tutarlar TL; kaynak servisinin hesapladığı değerlerdir."],
            warnings=[
                "Ücretler İZBAN servisinin yanıtıdır; gişe veya kart okuyucudaki tutar farklı olabilir.",
                "htt kaynağın tarife bayrağıdır; anlamı API'de belgelenmemiştir.",
            ],
        )

    async def parking_fees(self, *, query: str | None = None, limit: int | None = None) -> dict[str, Any]:
        needle = _name_filter(query, field="query")
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        limits = [f"limit={safe_limit}"]
        if needle:
            limits.append(f"query={needle}")
        try:
            rows, info = await self.layers.parking_fee_rows()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "Otopark ücret tarifesi okunamadı.", sources.PARKING_FEES, limits)
        matched = [row for row in rows if needle is None or needle in normalize_name(str(row.get("name") or ""))]
        data = matched[:safe_limit]
        warnings = [
            "Yayımlanmış tarifedir; güncel ücreti otopark işletmesinden doğrulayın.",
            "Canlı doluluk için izmir_nearby(types=['parking']) kullanın.",
        ]
        if not matched:
            warnings.append("Eşleşen otopark yok; ad parçasını kısaltmayı deneyin.")
        return success_envelope(
            summary=f"{len(data)} otopark tarifesi listelendi (toplam {len(matched)} eşleşme).",
            data=data,
            sources=[sources.PARKING_FEES],
            freshness=_freshness(info, self.settings.city_layer_cache_ttl_seconds),
            limits=[*limits, "fees_try değerleri TL; boş veya null kolonlar None döner."],
            warnings=warnings,
            matched=len(matched),
        )

    async def traffic_cameras(
        self,
        *,
        query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        needle = _name_filter(query, field="query")
        if (lat is None) != (lon is None):
            raise InputValidationError("lat ve lon birlikte verilmelidir", field="lat")
        if lat is None and radius_m is not None:
            raise InputValidationError("radius_m yalnızca lat/lon ile geçerlidir", field="radius_m")
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        limits = [f"limit={safe_limit}"]
        radius = None
        if lat is not None and lon is not None:
            validate_lat_lon(lat, lon)
            radius = validate_radius(CAMERA_DEFAULT_RADIUS_M if radius_m is None else radius_m, CAMERA_MAX_RADIUS_M)
            limits += [f"near={lat},{lon}", f"radius_m={radius}"]
        if needle:
            limits.append(f"query={needle}")
        try:
            rows, info = await self.layers.traffic_camera_rows()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "Trafik kamerası listesi okunamadı.", sources.TRAFFIC_CAMERAS, limits)
        matched = [row for row in rows if needle is None or needle in normalize_name(str(row.get("name") or ""))]
        if radius is not None and lat is not None and lon is not None:
            ranked = []
            for row in matched:
                if row.get("lat") is None or row.get("lon") is None:
                    continue
                distance = haversine_m(lat, lon, row["lat"], row["lon"])
                if distance <= radius:
                    ranked.append({**row, "distance_m": round(distance)})
            ranked.sort(key=lambda row: row["distance_m"])
            matched = ranked
        data = matched[:safe_limit]
        return success_envelope(
            summary=f"{len(data)} trafik kamerası konumu listelendi (toplam {len(matched)} eşleşme).",
            data=data,
            sources=[sources.TRAFFIC_CAMERAS],
            freshness=_freshness(info, self.settings.city_layer_cache_ttl_seconds),
            limits=[*limits, "Yakınlık kuş uçuşu metredir."],
            warnings=[
                "Yalnızca kamera konumu yayımlanır; görüntü veya yayın bağlantısı yoktur.",
                "Kameranın çalışır durumda olduğu kanıtı değildir.",
            ],
            matched=len(matched),
        )

    async def water_production(self, *, name: str | None = None, limit: int | None = None) -> dict[str, Any]:
        needle = _name_filter(name, field="name")
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        limits = [f"limit={safe_limit}"]
        if needle:
            limits.append(f"name={needle}")
        try:
            rows, info = await self.layers.water_production_rows()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return _failure(exc, "İZSU su üretimi verisi okunamadı.", sources.WATER_PRODUCTION, limits)
        matched = [row for row in rows if needle is None or needle in normalize_name(str(row.get("name") or ""))]
        data = matched[:safe_limit]
        total = sum(row["production"] for row in matched if isinstance(row.get("production"), float))
        return success_envelope(
            summary=f"{len(data)} İZSU üretim kaydı (son yayımlanan anlık görüntü); eşleşen toplam {total:g}.",
            data=data,
            sources=[sources.WATER_PRODUCTION],
            freshness=_freshness(info, self.settings.city_layer_cache_ttl_seconds),
            limits=[*limits, "Kaynakta tarih kolonu yoktur; ölçüm günü bilinmez."],
            warnings=[
                "Son yayımlanan anlık görüntüdür; 'bugünkü' üretim olduğu varsayılmamalıdır.",
                "Birim kaynakta belirtilmemiştir (İZSU günlük üretim olarak yayımlar).",
                "Baraj doluluğu için izmir_dam_status kullanın.",
            ],
            matched=len(matched),
        )
