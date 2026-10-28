from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.city_layers import CityLayerConnector
from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.envelope import result_info
from app.core.geo import has_name_token, haversine_m, in_bbox, normalize_name
from app.core.settings import Settings
from app.core.validation import (
    InputValidationError,
    resolve_limit,
    validate_bbox,
    validate_lat_lon,
    validate_radius,
)
from app.services import sources
from app.services.places import PlaceResolver

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
BBOX_LIMITS = [
    "Dikdörtgen min_lon,min_lat,max_lon,max_lat biçimindedir; dört kenar da dahildir.",
    "bbox modunda referans nokta yoktur; distance_m null döner ve sonuçlar mesafeye göre sıralanmaz.",
    "Kütüphane katmanı koordinat yayımlamaz; dikdörtgen sorgusuna hiçbir zaman giremez.",
]
DISTRICT_LIMITS = [
    "İlçe modu ilçe geneli liste verir; yarıçap filtresi uygulanmaz ve distance_m null döner.",
    "İlçe eşleşmesi kaynağın kendi ilçe alanına ya da adres metnine dayanır; idari sınır doğrulaması değildir.",
    "Kütüphane kayıtları koordinatsız olduğu için ilçe modunda ilçe alanıyla, diğer katmanlar adres/ilçe metniyle eşleşir.",
]
DISTRICT_TEXT_FIELDS = {
    "wifi": ("district", "address"),
    "izmirim_card": ("district", "address"),
    "library": ("district",),
}


def _maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


class CityServicesService:
    def __init__(self, *, settings: Settings, api: CityLayerConnector | None = None):
        self.settings = settings
        self.api = api or CityLayerConnector(settings=settings)

    def _loaders(self) -> dict[str, tuple[Any, Source]]:
        return {
            "wifi": (self.api.wifi_points, sources.WIFI),
            "izmirim_card": (self.api.izmirim_card_points, sources.IZMIRIM_CARD),
            "library": (self.api.libraries, sources.LIBRARY),
        }

    @staticmethod
    def _selected(kinds: list[str]) -> list[str]:
        if not kinds:
            raise InputValidationError(
                f"kinds must be a non-empty subset of: {', '.join(KINDS)}", field="kinds"
            )
        unknown = [kind for kind in kinds if kind not in KINDS]
        if unknown:
            raise InputValidationError(
                f"unknown kinds: {', '.join(unknown)}; allowed: {', '.join(KINDS)}",
                field="kinds",
            )
        return [kind for kind in KINDS if kind in set(kinds)]

    @staticmethod
    def _kind_warning(kind: str) -> str:
        if kind == "library":
            return (
                "Kütüphane katmanı koordinat yayımlamaz; kayıtlar ilçe ve adresle listelenir, "
                "mesafe hesaplanamaz."
            )
        if kind == "izmirim_card":
            return "İzmirim Kart dolum noktaları 2023 tarihli statik yayımdır; nokta kapanmış olabilir."
        return "WizmirNET noktaları statik listedir; güncel hizmet durumu doğrulanmadı."

    async def _collect(
        self, selected: list[str]
    ) -> tuple[
        dict[str, tuple[Source, list[dict[str, Any]]]],
        list[Source],
        list[str],
        list[str],
        list[str],
    ]:
        """Load each selected layer once, preserving partial failures."""
        loaders = self._loaders()
        outcomes = await asyncio.gather(
            *(loaders[kind][0]() for kind in selected), return_exceptions=True
        )
        by_kind: dict[str, tuple[Source, list[dict[str, Any]]]] = {}
        used: list[Source] = []
        warnings: list[str] = []
        statuses: list[str] = []
        observed: list[str] = []
        for kind, outcome in zip(selected, outcomes):
            _loader, source = loaders[kind]
            if isinstance(outcome, BaseException):
                warnings.append(
                    f"{kind} katmanı okunamadı ({type(outcome).__name__}); sonuç kısmi."
                )
                continue
            items, info = outcome
            by_kind[kind] = (source, items)
            used.append(source)
            statuses.append(info.status)
            if info.source_updated_at:
                observed.append(info.source_updated_at)
            warnings.append(self._kind_warning(kind))
        return by_kind, used, warnings, statuses, observed

    @staticmethod
    def _row(kind: str, item: dict[str, Any], source: Source) -> dict[str, Any]:
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
        if kind == "library":
            row["hours"] = item.get("hours")
            row["open_days"] = item.get("open_days")
            row["opened_year"] = item.get("opened_year")
        if kind == "izmirim_card":
            row["name"] = item.get("address") or row["name"]
        return row

    @staticmethod
    def _dedupe(rows: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
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
        if collapsed:
            warnings.append(
                f"Kaynakta {total_before} satırın {collapsed} tanesi yinelenen kayıttı; "
                f"aynı konum/adres altında birleştirildi."
            )
        return list(deduped.values())

    def _freshness(self, statuses: list[str], observed: list[str]) -> Freshness:
        return Freshness(
            status="stale" if "stale" in statuses else "fresh",
            ttl_seconds=self.settings.city_layer_cache_ttl_seconds,
            source_updated_at=max(observed) if observed else None,
        )

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
        selected = self._selected(kinds)
        validate_lat_lon(lat, lon)
        safe_radius = validate_radius(radius_m, self.settings.max_radius_m)
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

        by_kind, used, warnings, statuses, observed = await self._collect(selected)
        if not used:
            return error_envelope(
                summary="Şehir hizmeti katmanları okunamadı.",
                warning="Seçilen tüm katmanlar yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=LIMITS,
            )

        rows: list[dict[str, Any]] = []
        for kind, (source, items) in by_kind.items():
            for item in items:
                row = self._row(kind, item, source)
                if item.get("lat") is not None and item.get("lon") is not None:
                    distance = haversine_m(lat, lon, item["lat"], item["lon"])
                    if distance > safe_radius:
                        continue
                    row["distance_m"] = distance
                    row["maps_url"] = _maps_url(item["lat"], item["lon"])
                elif kind != "library":
                    continue
                rows.append(row)

        rows = self._dedupe(rows, warnings)
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
            freshness=self._freshness(statuses, observed),
            limits=[
                *LIMITS,
                f"radius_m={safe_radius}",
                f"limit={safe_limit}",
                f"kinds={','.join(selected)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=["Haritada görmek için maps_url kullanın; koordinatsız kayıtlar için adresi kullanın."],
            result=result_info(returned=len(data), matched=len(rows), scope="radius"),
        )

    async def bbox(
        self, *, bbox: list[float] | tuple[float, ...], kinds: list[str], limit: int
    ) -> dict[str, Any]:
        min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
        selected = self._selected(kinds)
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

        by_kind, used, warnings, statuses, observed = await self._collect(selected)
        if not used:
            return error_envelope(
                summary="bbox içindeki şehir hizmeti verisi okunamadı.",
                warning="Seçilen tüm katmanlar yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=BBOX_LIMITS,
            )

        rows: list[dict[str, Any]] = []
        for kind, (source, items) in by_kind.items():
            if kind == "library":
                continue
            for item in items:
                item_lat, item_lon = item.get("lat"), item.get("lon")
                if item_lat is None or item_lon is None:
                    continue
                if not in_bbox(
                    item_lat, item_lon,
                    min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
                ):
                    continue
                row = self._row(kind, item, source)
                row["maps_url"] = _maps_url(item_lat, item_lon)
                rows.append(row)

        rows = self._dedupe(rows, warnings)
        rows.sort(
            key=lambda row: (
                KINDS.index(row["kind"]),
                normalize_name(row.get("name") or ""),
                str(row.get("id") or ""),
            )
        )
        matched = len(rows)
        data = rows[:safe_limit]
        truncated = matched > len(data)
        if any(kind == "library" for kind in selected):
            warnings = [w for w in warnings if "mesafe hesaplanamaz" not in w]
            warnings.append(
                "Kütüphane katmanı bbox modunda listelenemez: koordinat yayımlamadığı için "
                "dikdörtgen sonucuna hiçbir zaman girmez; district veya place/radius kullanın."
            )
        if not data:
            warnings.append(
                "Bu bbox içinde seçilen türlerde kayıt bulunamadı; bu 'hiç yok' kanıtı değildir."
            )
        rectangle = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        summary = (
            f"{len(data)} şehir hizmeti noktası bbox içinde bulundu; toplam {matched} eşleşme."
            + (" İlk sonuçlar gösteriliyor." if truncated else "")
        )
        return success_envelope(
            summary=summary,
            data=data,
            sources=used,
            freshness=self._freshness(statuses, observed),
            limits=[
                *BBOX_LIMITS,
                f"bbox={rectangle}",
                f"limit={safe_limit}",
                f"kinds={','.join(selected)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=[
                "Yakınlık için lat/lon ve radius_m, ilçe geneli için district kullanın.",
            ],
            result=result_info(
                returned=len(data), matched=matched, truncated=truncated, scope="bbox"
            ),
        )

    async def district(
        self, *, district: str, kinds: list[str], limit: int
    ) -> dict[str, Any]:
        place = PlaceResolver().resolve_district(district)
        selected = self._selected(kinds)
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

        by_kind, used, warnings, statuses, observed = await self._collect(selected)
        if not used:
            return error_envelope(
                summary=f"{place.name} ilçesindeki şehir hizmeti verisi okunamadı.",
                warning="Seçilen tüm katmanlar yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=DISTRICT_LIMITS,
            )

        rows: list[dict[str, Any]] = []
        for kind, (source, items) in by_kind.items():
            fields = DISTRICT_TEXT_FIELDS.get(kind, ())
            for item in items:
                if not any(has_name_token(item.get(field), place.name) for field in fields):
                    continue
                row = self._row(kind, item, source)
                row["district_match"] = "published_district_field"
                if item.get("lat") is not None and item.get("lon") is not None:
                    row["maps_url"] = _maps_url(item["lat"], item["lon"])
                rows.append(row)

        rows = self._dedupe(rows, warnings)
        rows.sort(
            key=lambda row: (
                KINDS.index(row["kind"]),
                normalize_name(row.get("name") or ""),
                str(row.get("id") or ""),
            )
        )
        matched = len(rows)
        data = rows[:safe_limit]
        truncated = matched > len(data)
        warnings = [
            w for w in warnings
            if "mesafe hesaplanamaz" not in w
        ]
        warnings.extend(
            [
                f"İlçe eşleşmesi {place.name} için kaynağın kendi ilçe alanı/adres metnine dayanır; "
                "idari sınır doğrulaması değildir.",
                "Yalnızca yayımlanan metinde ilçe adı geçen satırlar eşleşir; bu tam ilçe envanteri değildir.",
                "distance_m null: ilçe modunda referans nokta yoktur, mesafe hesaplanmaz.",
            ]
        )
        if not data:
            warnings.append(
                f"{place.name} için kaynak metninde eşleşen kayıt bulunamadı; "
                "bu ilçede hizmet olmadığının kanıtı değildir."
            )
        summary = (
            f"{place.name} ilçesiyle {len(data)} şehir hizmeti noktası eşleşti; toplam {matched} kayıt."
            + (" İlk sonuçlar gösteriliyor." if truncated else "")
        )
        return success_envelope(
            summary=summary,
            data=data,
            sources=used,
            freshness=self._freshness(statuses, observed),
            limits=[
                *DISTRICT_LIMITS,
                f"district={place.name}",
                f"limit={safe_limit}",
                f"kinds={','.join(selected)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=[
                "Mesafe veya harita sıralaması için place veya lat/lon + radius_m kullanın.",
                "Dikdörtgen sorgu için bbox kullanın.",
            ],
            result=result_info(
                returned=len(data), matched=matched, truncated=truncated, scope="district"
            ),
        )
