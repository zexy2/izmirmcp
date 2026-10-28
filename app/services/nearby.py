from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.eshot import EshotConnector
from app.connectors.izmir_api import IzmirOpenApi
from app.core.envelope import Freshness, Source, error_envelope, result_info, success_envelope
from app.core.geo import has_name_token, haversine_m, in_bbox, normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, validate_bbox
from app.services import sources
from app.services.places import PlaceResolver

SUPPORTED_TYPES = (
    "parking",
    "pharmacy",
    "metro_station",
    "izban_station",
    "ferry_pier",
    "bus_stop",
)

# Only these layers publish text that can honestly identify a district. The
# pharmacy source's Bolge/BolgeAciklama values are duty-region labels (for
# example "KARŞIYAKA 4"), not boundary polygons. Parking and transit sources
# publish no district attribute at all, so district mode must not invent one.
DISTRICT_TEXT_FIELDS = {
    "pharmacy": ("district", "area_note"),
}

GENERAL_LIMITS = [
    "Distances are straight-line metres from the supplied or resolved reference point.",
    "Static station and pier locations do not prove live service or accessibility.",
]
BBOX_LIMITS = [
    "The rectangle is min_lon,min_lat,max_lon,max_lat; all four edges are inclusive.",
    "There is no reference point in bbox mode, so distance_m is null and results are not distance-ranked.",
    "Rows the source publishes without coordinates cannot appear in a rectangle query.",
]
DISTRICT_LIMITS = [
    "District mode shows a district-wide list; results are not radius-filtered and distance_m is null.",
    "District matching uses the source's own published region/area-note text, not an administrative boundary.",
    "Only pharmacy currently publishes a usable district/region label; other types are skipped with a warning.",
]


def _maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


def _common(
    kind: str,
    item: dict[str, Any],
    lat: float | None,
    lon: float | None,
    source_name: str,
) -> dict[str, Any]:
    distance = (
        haversine_m(lat, lon, item["lat"], item["lon"])
        if lat is not None and lon is not None
        else None
    )
    return {
        "kind": kind,
        "id": item.get("id"),
        "name": item.get("name"),
        "lat": item["lat"],
        "lon": item["lon"],
        "distance_m": distance,
        "maps_url": _maps_url(item["lat"], item["lon"]),
        "source": source_name,
    }


def _matches_district(kind: str, item: dict[str, Any], district_name: str) -> bool:
    return any(
        has_name_token(item.get(field), district_name)
        for field in DISTRICT_TEXT_FIELDS.get(kind, ())
    )


class NearbyService:
    def __init__(
        self,
        *,
        settings: Settings,
        api: IzmirOpenApi | None = None,
        eshot: EshotConnector | None = None,
    ):
        self.settings = settings
        self.api = api or IzmirOpenApi(settings)
        self.eshot = eshot or EshotConnector(settings=settings)

    def _loaders(self) -> dict[str, tuple[Any, Source]]:
        return {
            "parking": (self.api.parking, sources.PARKING),
            "pharmacy": (self.api.pharmacies, sources.PHARMACY),
            "metro_station": (self.api.metro_stations, sources.METRO),
            "izban_station": (self.api.izban_stations, sources.IZBAN),
            "ferry_pier": (self.api.ferry_piers, sources.FERRY),
            "bus_stop": (self.eshot.stops, sources.ESHOT_STOPS),
        }

    @staticmethod
    def _selected(types: list[str]) -> list[str]:
        return [kind for kind in SUPPORTED_TYPES if kind in set(types)]

    @staticmethod
    def _kind_warning(kind: str) -> str:
        if kind == "pharmacy":
            return "Nöbetçi eczane listesi günlüktür; kapanış saatini telefonla teyit edin."
        if kind == "parking":
            return "Boş yer sayıları anlık bildirimdir; kesin kapasite garantisi değildir."
        if kind == "bus_stop":
            return (
                "EShot durak konumları yayımlanmış listedir; canlı varış için "
                "izmir_bus_arrivals(stop_id=...) kullanın."
            )
        return f"{kind} konumları statik kaynaktır; canlı sefer durumu değildir."

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
        results = await asyncio.gather(
            *(loaders[kind][0]() for kind in selected), return_exceptions=True
        )
        by_kind: dict[str, tuple[Source, list[dict[str, Any]]]] = {}
        used_sources: list[Source] = []
        warnings: list[str] = []
        statuses: list[str] = []
        observed: list[str] = []

        for kind, outcome in zip(selected, results):
            _loader, source = loaders[kind]
            if isinstance(outcome, BaseException):
                warnings.append(f"{kind} verisi okunamadı ({type(outcome).__name__}); sonuç kısmi.")
                continue
            items, info = outcome
            by_kind[kind] = (source, items)
            used_sources.append(source)
            statuses.append(info.status)
            if info.source_updated_at:
                observed.append(info.source_updated_at)
            warnings.append(self._kind_warning(kind))

        return by_kind, used_sources, warnings, statuses, observed

    async def nearby(
        self,
        *,
        lat: float,
        lon: float,
        types: list[str],
        radius_m: int,
        limit: int,
        reference_label: str | None = None,
    ) -> dict[str, Any]:
        selected = self._selected(types)
        by_kind, used_sources, warnings, statuses, observed = await self._collect(selected)

        rows: list[dict[str, Any]] = []
        for kind, (source, items) in by_kind.items():
            for item in items:
                if item.get("lat") is None or item.get("lon") is None:
                    continue
                row = _common(kind, item, lat, lon, source.name)
                if row["distance_m"] > radius_m:
                    continue
                rows.append(self._decorate(kind, row, item))

        if not used_sources:
            return error_envelope(
                summary="Yakındaki hizmet verisi okunamadı.",
                warning="Seçilen tüm İzmir kaynakları yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=GENERAL_LIMITS,
            )

        rows.sort(key=lambda row: (row["distance_m"], row.get("name") or ""))
        rows = rows[:limit]
        freshness_status = "stale" if "stale" in statuses else "fresh"
        reference = reference_label or f"{lat:.5f}, {lon:.5f}"
        return success_envelope(
            summary=f"{len(rows)} sonuç bulundu; {reference} çevresinde {radius_m} m içinde.",
            data=rows,
            sources=used_sources,
            freshness=Freshness(
                status=freshness_status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=max(observed) if observed else None,
            ),
            limits=[
                *GENERAL_LIMITS,
                f"radius_m={radius_m}",
                f"limit={limit}",
                f"types={','.join(selected)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=["Sonuçları haritada görmek için maps_url bağlantılarını kullanın."],
        )

    async def bbox(
        self, *, bbox: list[float] | tuple[float, ...], types: list[str], limit: int
    ) -> dict[str, Any]:
        min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
        selected = self._selected(types)
        if not selected:
            raise InputValidationError(
                f"types must be a non-empty subset of: {', '.join(SUPPORTED_TYPES)}",
                field="types",
            )
        by_kind, used_sources, warnings, statuses, observed = await self._collect(selected)

        rows: list[dict[str, Any]] = []
        for kind, (source, items) in by_kind.items():
            for item in items:
                item_lat, item_lon = item.get("lat"), item.get("lon")
                if item_lat is None or item_lon is None:
                    continue
                if not in_bbox(
                    item_lat, item_lon,
                    min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
                ):
                    continue
                row = _common(kind, item, None, None, source.name)
                rows.append(self._decorate(kind, row, item))

        if not used_sources:
            return error_envelope(
                summary="bbox içindeki hizmet verisi okunamadı.",
                warning="Seçilen tüm İzmir kaynakları yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=BBOX_LIMITS,
            )

        rows.sort(
            key=lambda row: (
                SUPPORTED_TYPES.index(row["kind"]),
                normalize_name(row.get("name") or ""),
                str(row.get("id") or ""),
            )
        )
        matched = len(rows)
        data = rows[:limit]
        truncated = matched > len(data)
        warnings.extend(
            [
                "bbox modunda referans nokta yoktur; distance_m null döner ve sonuçlar mesafeye göre sıralanmaz.",
                "Kaynağında koordinat olmayan satırlar dikdörtgen sorgusuna alınamaz.",
            ]
        )
        if not data:
            warnings.append(
                "Bu bbox içinde seçilen türlerde kayıt bulunamadı; bu 'hiç yok' kanıtı değildir."
            )
        rectangle = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        summary = (
            f"{len(data)} sonuç bbox içinde bulundu; toplam {matched} eşleşme."
            + (" İlk sonuçlar gösteriliyor." if truncated else "")
        )
        freshness_status = "stale" if "stale" in statuses else "fresh"
        return success_envelope(
            summary=summary,
            data=data,
            sources=used_sources,
            freshness=Freshness(
                status=freshness_status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=max(observed) if observed else None,
            ),
            limits=[
                *BBOX_LIMITS,
                f"bbox={rectangle}",
                f"limit={limit}",
                f"types={','.join(selected)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=[
                "Yakınlık sorgusu için lat/lon ve radius_m kullanın.",
                "İlçe geneli eczane listesi için district kullanın (yalnızca eczane).",
            ],
            result=result_info(
                returned=len(data),
                matched=matched,
                truncated=truncated,
                scope="bbox",
            ),
        )

    async def district(
        self, *, district: str, types: list[str], limit: int
    ) -> dict[str, Any]:
        place = PlaceResolver().resolve_district(district)
        selected = self._selected(types)
        if not selected:
            raise InputValidationError(
                f"types must be a non-empty subset of: {', '.join(SUPPORTED_TYPES)}",
                field="types",
            )
        capable = [kind for kind in selected if kind in DISTRICT_TEXT_FIELDS]
        skipped = [kind for kind in selected if kind not in DISTRICT_TEXT_FIELDS]
        if not capable:
            raise InputValidationError(
                "district mode currently supports only pharmacy: İzmir parking and "
                "transit sources publish no district attribute. Use bbox or place/radius "
                "for those types.",
                field="types",
            )

        by_kind, used_sources, warnings, statuses, observed = await self._collect(capable)
        rows: list[dict[str, Any]] = []
        for kind, (source, items) in by_kind.items():
            for item in items:
                if item.get("lat") is None or item.get("lon") is None:
                    continue
                if not _matches_district(kind, item, place.name):
                    continue
                row = _common(kind, item, None, None, source.name)
                row["district_match"] = "published_region_text"
                rows.append(self._decorate(kind, row, item))

        if not used_sources:
            return error_envelope(
                summary=f"{place.name} ilçesindeki hizmet verisi okunamadı.",
                warning="Seçilen İzmir kaynağı yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=DISTRICT_LIMITS,
            )

        rows.sort(
            key=lambda row: (
                normalize_name(row.get("name") or ""),
                str(row.get("id") or ""),
            )
        )
        matched = len(rows)
        data = rows[:limit]
        truncated = matched > len(data)
        warnings.extend(
            [
                f"İlçe eşleşmesi {place.name} için kaynağın kendi bölge/bölge açıklaması "
                "metnine dayanır; idari sınır doğrulaması değildir.",
                "Yalnızca kaynak bölge metninde ilçe adı geçen satırlar eşleşir; bu tam "
                "ilçe envanteri değildir.",
                "distance_m null: ilçe modunda referans nokta yoktur, mesafe hesaplanmaz.",
            ]
        )
        if skipped:
            warnings.append(
                f"{', '.join(skipped)} için kaynak ilçe alanı yayımlamıyor; ilçe modunda "
                "atlandı. Bu türler için bbox veya place/radius kullanın."
            )
        if not data:
            warnings.append(
                f"{place.name} için kaynak bölge metninde eşleşen eczane bulunamadı; "
                "bu ilçede eczane olmadığının kanıtı değildir."
            )
        summary = (
            f"{place.name} ilçesiyle {len(data)} eczane eşleşti; toplam {matched} kayıt."
            + (" İlk sonuçlar gösteriliyor." if truncated else "")
        )
        freshness_status = "stale" if "stale" in statuses else "fresh"
        return success_envelope(
            summary=summary,
            data=data,
            sources=used_sources,
            freshness=Freshness(
                status=freshness_status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=max(observed) if observed else None,
            ),
            limits=[
                *DISTRICT_LIMITS,
                f"district={place.name}",
                f"limit={limit}",
                f"types={','.join(capable)}",
            ],
            warnings=sorted(set(warnings)),
            next_queries=[
                "Mesafe veya harita sıralaması için place veya lat/lon + radius_m kullanın.",
                "Dikdörtgen sorgu için bbox kullanın; tüm koordinatlı türler desteklenir.",
            ],
            result=result_info(
                returned=len(data),
                matched=matched,
                truncated=truncated,
                scope="district",
            ),
        )

    def _decorate(self, kind: str, row: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        if kind == "parking":
            row.update(
                {
                    "free": item.get("free"),
                    "occupied": item.get("occupied"),
                    "capacity": item.get("capacity"),
                    "status": item.get("status"),
                    "is_paid": item.get("is_paid"),
                    "address": item.get("address"),
                    "opening_hours_today": item.get("opening_hours_today"),
                }
            )
        elif kind == "pharmacy":
            row.update(
                {
                    "phone": item.get("phone"),
                    "address": item.get("address"),
                    "district": item.get("district"),
                    "area_note": item.get("area_note"),
                    "duty_date": item.get("duty_date"),
                }
            )
        elif kind in {"metro_station", "izban_station"}:
            row.update({"active": item.get("active"), "order": item.get("order")})
        elif kind == "ferry_pier":
            row.update({"active": item.get("active"), "car_ferry": item.get("car_ferry")})
        elif kind == "bus_stop":
            row.update({"routes": item.get("routes") or []})
        return row
