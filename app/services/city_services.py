from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.city_layers import CityLayerConnector
from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.geo import haversine_m
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_radius
from app.services import sources

KINDS = ("wifi", "izmirim_card", "library")

KIND_LABELS = {
    "wifi": "WizmirNET kablosuz internet noktası",
    "izmirim_card": "İzmirim Kart dolum noktası",
    "library": "İZBAN kütüphanesi",
}

LIMITS = [
    "Tüm katmanlar yayımlanmış statik snapshot'lardır; açık/kapalı, çalışır/bozuk veya doluluk durumu değildir.",
    "Yakınlık kuş uçuşu metredir.",
]


def _maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


class CityServicesService:
    def __init__(self, *, settings: Settings, api: CityLayerConnector | None = None):
        self.settings = settings
        self.api = api or CityLayerConnector(settings=settings)

    async def nearby(
        self,
        *,
        kinds: list[str],
        lat: float,
        lon: float,
        radius_m: int,
        limit: int,
        reference_label: str | None = None,
    ) -> dict[str, Any]:
        if not kinds:
            raise InputValidationError(
                f"kinds must be a non-empty subset of: {', '.join(KINDS)}", field="kinds"
            )
        unknown = [kind for kind in kinds if kind not in KINDS]
        if unknown:
            raise InputValidationError(
                f"unknown kinds: {', '.join(unknown)}; allowed: {', '.join(KINDS)}", field="kinds"
            )
        validate_lat_lon(lat, lon)
        safe_radius = validate_radius(radius_m, self.settings.max_radius_m)
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

        loaders = {
            "wifi": (self.api.wifi_points, sources.WIFI),
            "izmirim_card": (self.api.izmirim_card_points, sources.IZMIRIM_CARD),
            "library": (self.api.libraries, sources.LIBRARY),
        }
        selected = [kind for kind in KINDS if kind in set(kinds)]
        outcomes = await asyncio.gather(
            *(loaders[kind][0]() for kind in selected), return_exceptions=True
        )

        rows: list[dict[str, Any]] = []
        used: list[Source] = []
        warnings: list[str] = []
        statuses: list[str] = []
        observed: list[str] = []

        for kind, outcome in zip(selected, outcomes):
            _loader, source = loaders[kind]
            if isinstance(outcome, BaseException):
                warnings.append(f"{kind} katmanı okunamadı ({type(outcome).__name__}); sonuç kısmi.")
                continue
            items, info = outcome
            used.append(source)
            statuses.append(info.status)
            if info.source_updated_at:
                observed.append(info.source_updated_at)
            for item in items:
                row = {
                    "kind": kind,
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                    "distance_m": None,
                    "maps_url": None,
                    "source": source.name,
                    "district": item.get("district"),
                    "neighborhood": item.get("neighborhood"),
                    "address": item.get("address"),
                }
                if item.get("lat") is not None and item.get("lon") is not None:
                    distance = haversine_m(lat, lon, item["lat"], item["lon"])
                    if distance > safe_radius:
                        continue
                    row["distance_m"] = distance
                    row["maps_url"] = _maps_url(item["lat"], item["lon"])
                elif kind != "library":
                    continue
                if kind == "library":
                    row["hours"] = item.get("hours")
                    row["open_days"] = item.get("open_days")
                    row["opened_year"] = item.get("opened_year")
                if kind == "izmirim_card":
                    row["name"] = item.get("address") or row["name"]
                rows.append(row)

            if kind == "library":
                warnings.append(
                    "Kütüphane katmanı koordinat yayımlamaz; kayıtlar ilçe ve adresle listelenir, "
                    "mesafe hesaplanamaz ve yarıçap filtresi uygulanamaz."
                )
            elif kind == "izmirim_card":
                warnings.append(
                    "İzmirim Kart dolum noktaları 2023 tarihli statik yayımdır; nokta kapanmış olabilir."
                )
            else:
                warnings.append(
                    "WizmirNET noktaları statik listedir; güncel hizmet durumu doğrulanmadı."
                )

        deduped: dict[tuple, dict[str, Any]] = {}
        total_before = len(rows)
        collapsed = 0
        for row in rows:
            key = (
                row["kind"], row.get("name"), row.get("address"),
                row.get("district"), row.get("lat"), row.get("lon"),
            )
            if key in deduped:
                collapsed += 1
                continue
            deduped[key] = row
        rows = list(deduped.values())
        if collapsed:
            warnings.append(
                f"Kaynakta {total_before} satırın {collapsed} tanesi yinelenen kayıttı; "
                f"aynı konum/adres altında birleştirildi."
            )

        if not used:
            return error_envelope(
                summary="Şehir hizmeti katmanları okunamadı.",
                warning="Seçilen tüm katmanlar yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=LIMITS,
            )

        with_distance = [row for row in rows if row["distance_m"] is not None]
        without_distance = [row for row in rows if row["distance_m"] is None]
        with_distance.sort(key=lambda row: (row["distance_m"], row.get("name") or ""))
        without_distance.sort(key=lambda row: (row.get("district") or "", row.get("name") or ""))
        data = (with_distance + without_distance)[:safe_limit]

        reference = reference_label or f"{lat:.5f}, {lon:.5f}"
        return success_envelope(
            summary=f"{len(data)} şehir hizmeti noktası listelendi; {reference} çevresinde {safe_radius} m.",
            data=data,
            sources=used,
            freshness=Freshness(
                status="stale" if "stale" in statuses else "fresh",
                ttl_seconds=self.settings.city_layer_cache_ttl_seconds,
                source_updated_at=max(observed) if observed else None,
            ),
            limits=[
                *LIMITS,
                f"radius_m={safe_radius}",
                f"limit={safe_limit}",
                f"kinds={','.join(selected)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=["Haritada görmek için maps_url kullanın; koordinatsız kayıtlar için adresi kullanın."],
            matched=len(rows),
        )
