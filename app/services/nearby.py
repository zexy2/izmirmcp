from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from app.connectors.city_layers import CityLayerConnector
from app.connectors.eshot import EshotConnector
from app.connectors.izmir_api import IzmirOpenApi
from app.core.envelope import Freshness, Source, error_envelope, result_info, success_envelope
from app.core.geo import (
    has_name_token,
    haversine_m,
    maps_url,
    normalize_name,
    outside_izmir,
)
from app.core.settings import Settings
from app.core.validation import InputValidationError, validate_bbox
from app.services import sources
from app.services.places import PlaceResolver
from app.storage.geo import GeoIndex, GeoStore, GeoStoreError

SUPPORTED_TYPES = (
    "parking",
    "pharmacy",
    "metro_station",
    "izban_station",
    "ferry_pier",
    "bus_stop",
    "taxi_stand",
    "charging_station",
)

# Only these layers publish text that can honestly identify a district. The
# pharmacy source's Bolge/BolgeAciklama values are duty-region labels (for
# example "KARŞIYAKA 4"), not boundary polygons. Parking and transit sources
# publish no district attribute at all, so district mode must not invent one.
DISTRICT_TEXT_FIELDS = {
    "pharmacy": ("district", "area_note"),
}

GENERAL_LIMITS = [
    "Mesafeler, verilen veya çözümlenen referans noktasından kuş uçuşu metredir.",
    "Statik istasyon ve iskele konumları canlı hizmet veya erişilebilirlik kanıtı değildir.",
]
BBOX_LIMITS = [
    "Dikdörtgen min_lon,min_lat,max_lon,max_lat sırasındadır; dört kenar da kapsayıcıdır.",
    "bbox modunda referans nokta yoktur; distance_m null döner ve sonuçlar mesafeye göre sıralanmaz.",
    "Kaynağında koordinat olmayan satırlar dikdörtgen sorgusuna alınamaz.",
]
DISTRICT_LIMITS = [
    "İlçe modu ilçe geneli bir liste gösterir; sonuçlar yarıçapla filtrelenmez ve distance_m null döner.",
    "İlçe eşleştirmesi kaynağın kendi yayımladığı bölge/alan-notu metnini kullanır; idari sınır değildir.",
    "Şu an yalnızca eczane kullanılabilir bir ilçe/bölge etiketi yayımlıyor; diğer türler uyarıyla atlanır.",
]


# Transport layers only. Pharmacy, WiFi, card and library points answer a
# different question and would blur a "how do I get around here" summary.
MOBILITY_TYPES = (
    "parking",
    "metro_station",
    "izban_station",
    "ferry_pier",
    "bus_stop",
    "taxi_stand",
    "charging_station",
)
MODE_LABELS = {
    "parking": "otopark",
    "metro_station": "metro istasyonu",
    "izban_station": "İZBAN istasyonu",
    "ferry_pier": "vapur iskelesi",
    "bus_stop": "otobüs durağı",
    "taxi_stand": "taksi durağı",
    "charging_station": "şarj istasyonu",
}
MOBILITY_LIMITS = [
    "Ulaşım özeti yalnızca koordinat yayımlayan katmanları içerir; canlı sefer, doluluk veya ETA değildir.",
    "Hava kalitesi istasyonları bu özette yoktur: İzmir kaynağı istasyon koordinatı yayımlamıyor.",
    "Canlı trafik yoğunluğu bu özette yoktur: İzmir'de canlı trafik indeksi "
    "yayımlanmıyor (/api/ibb/trafikyogunluk 404).",
]


def _common(
    kind: str,
    item: dict[str, Any],
    lat: float | None,
    lon: float | None,
    source_name: str,
) -> dict[str, Any]:
    distance = haversine_m(lat, lon, item["lat"], item["lon"]) if lat is not None and lon is not None else None
    return {
        "kind": kind,
        "id": item.get("id"),
        "name": item.get("name"),
        "lat": item["lat"],
        "lon": item["lon"],
        "distance_m": distance,
        "maps_url": maps_url(item["lat"], item["lon"]),
        "source": source_name,
    }


def _matches_district(kind: str, item: dict[str, Any], district_name: str) -> bool:
    return any(has_name_token(item.get(field), district_name) for field in DISTRICT_TEXT_FIELDS.get(kind, ()))


class NearbyService:
    def __init__(
        self,
        *,
        settings: Settings,
        api: IzmirOpenApi | None = None,
        eshot: EshotConnector | None = None,
        taxis: CityLayerConnector | None = None,
        charging: CityLayerConnector | None = None,
    ):
        self.settings = settings
        self.api = api or IzmirOpenApi(settings)
        self.eshot = eshot or EshotConnector(settings=settings)
        self.taxis = taxis or CityLayerConnector(settings=settings)
        self.charging = charging or CityLayerConnector(settings=settings)
        self.index = GeoIndex(GeoStore(settings.database_path))

    def _loaders(self) -> dict[str, tuple[Any, Source]]:
        return {
            "parking": (self.api.parking, sources.PARKING),
            "pharmacy": (self.api.pharmacies, sources.PHARMACY),
            "metro_station": (self.api.metro_stations, sources.METRO),
            "izban_station": (self.api.izban_stations, sources.IZBAN),
            "ferry_pier": (self.api.ferry_piers, sources.FERRY),
            "bus_stop": (self.eshot.stops, sources.ESHOT_STOPS),
            "taxi_stand": (self.taxis.taxi_stands, sources.TAXI_STANDS),
            "charging_station": (self.charging.charging_points, sources.CHARGING),
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
                "EShot durak konumları yayımlanmış listedir; canlı varış için izmir_bus_arrivals(stop_id=...) kullanın."
            )
        if kind == "taxi_stand":
            return "Taksi durağı konumları yayımlanmış statik listedir; orada taksi bulunması garanti değildir."
        if kind == "charging_station":
            return (
                "Şarj istasyonu konumları yayımlanmış statik listedir; istasyonun "
                "çalışır durumda veya boş olması garanti değildir."
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
        results = await asyncio.gather(*(loaders[kind][0]() for kind in selected), return_exceptions=True)
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

    async def _layers(
        self, selected: list[str]
    ) -> tuple[
        dict[str, Source],
        list[Source],
        list[str],
        list[str],
        list[str],
    ]:
        """Resolve the layers needed for a spatial query.

        The index owns warmth, age and rebuilds; this method only translates
        its outcome into source objects and user-facing warnings. A warm, fresh
        index is authoritative: the source is not contacted again just to
        decorate rows, because the index already stores the payload.
        """
        loaders = self._loaders()
        outcome = await self.index.ensure(
            selected,
            {kind: loader for kind, (loader, _source) in loaders.items()},
            ttl_seconds=self.settings.eshot_cache_ttl_seconds,
        )

        if outcome.warm:
            return (
                {kind: loaders[kind][1] for kind in selected},
                [loaders[kind][1] for kind in selected],
                [self._kind_warning(kind) for kind in selected],
                ["fresh"],
                [outcome.state.built_at] if outcome.state.built_at else [],
            )

        warnings = [self._kind_warning(kind) for kind in outcome.answered]
        for kind, error in outcome.failed.items():
            warnings.append(f"{kind} verisi okunamadı ({error}); sonuç kısmi.")
        for kind, error in outcome.unindexed.items():
            warnings.append(f"{kind} mekânsal indekse yazılamadı ({error}); sonuç kısmi.")
        by_kind = {kind: loaders[kind][1] for kind in outcome.answered}
        used = list(by_kind.values())
        statuses: list[str] = [outcome.reports[kind].status for kind in outcome.answered]
        observed: list[str] = []
        for kind in outcome.answered:
            updated_at = outcome.reports[kind].source_updated_at
            if updated_at:
                observed.append(updated_at)
        if not outcome.answered:
            return {}, [], warnings, statuses, observed
        if not outcome.refreshed:
            # Every layer answered but none yielded indexable rows. That is an
            # empty result, not a source outage, so the caller still gets a
            # successful envelope with an explicit warning.
            warnings.append("Kaynaklar yanıt verdi ancak indekslenecek koordinatlı kayıt yok; sonuç boş olabilir.")
            return by_kind, used, warnings, statuses, observed
        return (
            {kind: by_kind[kind] for kind in outcome.refreshed if kind in by_kind},
            used,
            warnings,
            statuses,
            observed,
        )

    def _freshness(self, statuses: list[str], observed: list[str]) -> Freshness:
        return Freshness(
            status="stale" if "stale" in statuses else "fresh",
            ttl_seconds=self.settings.openapi_cache_ttl_seconds,
            source_updated_at=max(observed) if observed else None,
        )

    @staticmethod
    def _source_failure(*, summary: str, warning: str, limits: list[str]) -> dict[str, Any]:
        return error_envelope(
            summary=summary,
            warning=warning,
            code="source_unavailable",
            sources=[],
            limits=limits,
        )

    @staticmethod
    def _cut(
        rows: list[dict[str, Any]],
        *,
        limit: int,
        sort_key: Callable[[dict[str, Any]], Any],
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """Sort, report the full match count and cut once."""
        rows.sort(key=sort_key)
        matched = len(rows)
        data = rows[:limit]
        return data, matched, matched > len(data)

    def _envelope(
        self,
        *,
        summary: str,
        data: list[dict[str, Any]],
        sources: list[Source],
        statuses: list[str],
        observed: list[str],
        limits: list[str],
        warnings: list[str],
        next_queries: list[str],
        matched: int,
        truncated: bool,
        scope: str,
    ) -> dict[str, Any]:
        """The single success-envelope path shared by every nearby mode."""
        return success_envelope(
            summary=summary,
            data=data,
            sources=sources,
            freshness=self._freshness(statuses, observed),
            limits=limits,
            warnings=sorted(set(warnings)),
            next_queries=next_queries,
            result=result_info(
                returned=len(data),
                matched=matched,
                truncated=truncated,
                scope=scope,
            ),
        )

    async def _rows_from_index(
        self,
        query: Callable[[], list[dict[str, Any]]],
        *,
        by_kind: dict[str, Source],
        lat: float | None,
        lon: float | None,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        """Run one spatial query and decorate every hit identically."""
        try:
            hits = await asyncio.to_thread(query)
        except GeoStoreError as exc:
            warnings.append(f"mekânsal sorgu başarısız ({type(exc).__name__}).")
            return []
        rows: list[dict[str, Any]] = []
        for hit in hits:
            kind = hit["kind"]
            item = self._indexed_row(hit)
            row = _common(kind, item, lat, lon, by_kind[kind].name)
            rows.append(self._decorate(kind, row, item))
        return rows

    @staticmethod
    def _indexed_row(item: dict[str, Any]) -> dict[str, Any]:
        """Flatten an indexed row back into the source-item shape."""
        payload = item.get("payload") or {}
        return {
            **payload,
            "id": item.get("id"),
            "name": item.get("name"),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
        }

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
        if outside_izmir(lat, lon):
            # Nothing published for İzmir can match. Do not contact a source just
            # to prove that, and never turn this into a source-outage answer.
            return success_envelope(
                summary="0 sonuç; koordinat İzmir il sınırları dışında.",
                data=[],
                sources=[],
                freshness=Freshness(status="unknown"),
                limits=[
                    *GENERAL_LIMITS,
                    f"radius_m={radius_m}",
                    f"limit={limit}",
                    f"types={','.join(selected)}",
                    "outside_coverage",
                ],
                warnings=[
                    "Verilen koordinat İzmir il sınırları dışında görünüyor; boş sonuç "
                    "'İzmir'de hizmet yok' kanıtı değildir."
                ],
                result=result_info(returned=0, matched=0, truncated=False, scope="outside_coverage"),
            )
        by_kind, used_sources, warnings, statuses, observed = await self._layers(selected)
        if not used_sources:
            return self._source_failure(
                summary="Yakındaki hizmet verisi okunamadı.",
                warning="Seçilen tüm İzmir kaynakları yanıt vermedi.",
                limits=GENERAL_LIMITS,
            )

        rows: list[dict[str, Any]] = []
        if by_kind:
            rows = await self._rows_from_index(
                lambda: self.index.store.radius(
                    lat,
                    lon,
                    radius_m=radius_m,
                    kinds=[kind for kind in selected if kind in by_kind],
                ),
                by_kind=by_kind,
                lat=lat,
                lon=lon,
                warnings=warnings,
            )

        data, matched, truncated = self._cut(
            rows,
            limit=limit,
            sort_key=lambda row: (row["distance_m"], row.get("name") or ""),
        )
        reference = reference_label or f"{lat:.5f}, {lon:.5f}"
        summary = f"{len(data)} sonuç bulundu; {reference} çevresinde {radius_m} m içinde." + (
            " İlk sonuçlar gösteriliyor." if truncated else ""
        )
        return self._envelope(
            summary=summary,
            data=data,
            sources=used_sources,
            statuses=statuses,
            observed=observed,
            limits=[
                *GENERAL_LIMITS,
                "Sorgu yerel mekânsal indeksten yanıtlandı (SQLite RTree).",
                f"radius_m={radius_m}",
                f"limit={limit}",
                f"types={','.join(selected)}",
            ],
            warnings=warnings,
            next_queries=["Sonuçları haritada görmek için maps_url bağlantılarını kullanın."],
            matched=matched,
            truncated=truncated,
            scope="radius",
        )

    async def mobility(
        self,
        *,
        lat: float,
        lon: float,
        radius_m: int,
        limit: int,
        reference_label: str | None = None,
    ) -> dict[str, Any]:
        """Answer "what transport is near me" in one envelope.

        A preset over :meth:`nearby`: same spatial index, same row shapes, same
        error taxonomy. It adds only what the composite question needs — a
        per-mode count and an explicit statement of the upstream components
        İzmir cannot supply (air-quality stations have no coordinates, live
        traffic is 404).
        """
        envelope = await self.nearby(
            lat=lat,
            lon=lon,
            types=list(MOBILITY_TYPES),
            radius_m=radius_m,
            limit=limit,
            reference_label=reference_label,
        )
        if not envelope.get("ok"):
            return envelope
        if (envelope.get("result_info") or {}).get("scope") == "outside_coverage":
            return envelope

        counts: dict[str, int] = {}
        for row in envelope["data"]:
            kind = row["kind"]
            counts[kind] = counts.get(kind, 0) + 1
        breakdown = ", ".join(f"{counts[kind]} {MODE_LABELS[kind]}" for kind in MOBILITY_TYPES if counts.get(kind))
        reference = reference_label or f"{lat:.5f}, {lon:.5f}"
        shown = len(envelope["data"])
        matched = (envelope.get("result_info") or {}).get("matched")
        truncated = bool((envelope.get("result_info") or {}).get("truncated"))
        if breakdown:
            envelope["summary"] = (
                f"{reference} çevresinde {radius_m} m içinde {shown} ulaşım noktası gösteriliyor: {breakdown}."
            )
            if truncated and matched is not None:
                envelope["summary"] += f" Toplam {matched} eşleşmeden ilk {shown} gösteriliyor."
        else:
            envelope["summary"] = f"{reference} çevresinde {radius_m} m içinde yayımlanmış ulaşım noktası bulunamadı."

        envelope["limits"] = [
            *envelope["limits"],
            f"modes={','.join(MOBILITY_TYPES)}",
            "counts_scope=shown",
        ]
        envelope["warnings"] = sorted(set([*envelope["warnings"], *MOBILITY_LIMITS]))

        bus_stops = [row for row in envelope["data"] if row["kind"] == "bus_stop"]
        next_queries: list[str] = []
        if bus_stops:
            nearest = bus_stops[0]["id"]
            next_queries.extend(
                [
                    f"En yakın duraktan planlı kalkışlar için izmir_bus_departures(stop_id={nearest}) kullanın.",
                    f"Canlı yaklaşan otobüsler için izmir_bus_arrivals(stop_id={nearest}) kullanın.",
                ]
            )
        next_queries.append("Yalnızca tek tür için izmir_nearby(types=[...]) kullanın.")
        envelope["next_queries"] = next_queries
        envelope["result_info"]["scope"] = "mobility_nearby"
        return envelope

    async def bbox(self, *, bbox: list[float] | tuple[float, ...], types: list[str], limit: int) -> dict[str, Any]:
        min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
        selected = self._selected(types)
        if not selected:
            raise InputValidationError(
                f"types boş olamaz; şunlardan bir alt küme olmalıdır: {', '.join(SUPPORTED_TYPES)}",
                field="types",
            )
        by_kind, used_sources, warnings, statuses, observed = await self._layers(selected)
        if not used_sources:
            return self._source_failure(
                summary="bbox içindeki hizmet verisi okunamadı.",
                warning="Seçilen tüm İzmir kaynakları yanıt vermedi.",
                limits=BBOX_LIMITS,
            )

        rows: list[dict[str, Any]] = []
        if by_kind:
            rows = await self._rows_from_index(
                lambda: self.index.store.bbox(
                    min_lon=min_lon,
                    min_lat=min_lat,
                    max_lon=max_lon,
                    max_lat=max_lat,
                    kinds=[kind for kind in selected if kind in by_kind],
                ),
                by_kind=by_kind,
                lat=None,
                lon=None,
                warnings=warnings,
            )

        data, matched, truncated = self._cut(
            rows,
            limit=limit,
            sort_key=lambda row: (
                SUPPORTED_TYPES.index(row["kind"]),
                normalize_name(row.get("name") or ""),
                str(row.get("id") or ""),
            ),
        )
        warnings.extend(
            [
                "bbox modunda referans nokta yoktur; distance_m null döner ve sonuçlar mesafeye göre sıralanmaz.",
                "Kaynağında koordinat olmayan satırlar dikdörtgen sorgusuna alınamaz.",
            ]
        )
        if not data:
            warnings.append("Bu bbox içinde seçilen türlerde kayıt bulunamadı; bu 'hiç yok' kanıtı değildir.")
        rectangle = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        summary = f"{len(data)} sonuç bbox içinde bulundu; toplam {matched} eşleşme." + (
            " İlk sonuçlar gösteriliyor." if truncated else ""
        )
        return self._envelope(
            summary=summary,
            data=data,
            sources=used_sources,
            statuses=statuses,
            observed=observed,
            limits=[
                *BBOX_LIMITS,
                "Sorgu yerel mekânsal indeksten yanıtlandı (SQLite RTree).",
                f"bbox={rectangle}",
                f"limit={limit}",
                f"types={','.join(selected)}",
            ],
            warnings=warnings,
            next_queries=[
                "Yakınlık sorgusu için lat/lon ve radius_m kullanın.",
                "İlçe geneli eczane listesi için district kullanın (yalnızca eczane).",
            ],
            matched=matched,
            truncated=truncated,
            scope="bbox",
        )

    async def district(self, *, district: str, types: list[str], limit: int) -> dict[str, Any]:
        place = PlaceResolver().resolve_district(district)
        selected = self._selected(types)
        if not selected:
            raise InputValidationError(
                f"types boş olamaz; şunlardan bir alt küme olmalıdır: {', '.join(SUPPORTED_TYPES)}",
                field="types",
            )
        capable = [kind for kind in selected if kind in DISTRICT_TEXT_FIELDS]
        skipped = [kind for kind in selected if kind not in DISTRICT_TEXT_FIELDS]
        if not capable:
            raise InputValidationError(
                "district modu şu an yalnızca eczane destekler: İzmir otopark ve toplu "
                "taşıma kaynakları ilçe özniteliği yayımlamaz. Bu türler için bbox ya da "
                "place/radius kullanın.",
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
            return self._source_failure(
                summary=f"{place.name} ilçesindeki hizmet verisi okunamadı.",
                warning="Seçilen İzmir kaynağı yanıt vermedi.",
                limits=DISTRICT_LIMITS,
            )

        data, matched, truncated = self._cut(
            rows,
            limit=limit,
            sort_key=lambda row: (
                normalize_name(row.get("name") or ""),
                str(row.get("id") or ""),
            ),
        )
        warnings.extend(
            [
                f"İlçe eşleşmesi {place.name} için kaynağın kendi bölge/bölge açıklaması "
                "metnine dayanır; idari sınır doğrulaması değildir.",
                "Yalnızca kaynak bölge metninde ilçe adı geçen satırlar eşleşir; bu tam ilçe envanteri değildir.",
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
        summary = f"{place.name} ilçesiyle {len(data)} eczane eşleşti; toplam {matched} kayıt." + (
            " İlk sonuçlar gösteriliyor." if truncated else ""
        )
        return self._envelope(
            summary=summary,
            data=data,
            sources=used_sources,
            statuses=statuses,
            observed=observed,
            limits=[
                *DISTRICT_LIMITS,
                f"district={place.name}",
                f"limit={limit}",
                f"types={','.join(capable)}",
            ],
            warnings=warnings,
            next_queries=[
                "Mesafe veya harita sıralaması için place veya lat/lon + radius_m kullanın.",
                "Dikdörtgen sorgu için bbox kullanın; tüm koordinatlı türler desteklenir.",
            ],
            matched=matched,
            truncated=truncated,
            scope="district",
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
        elif kind == "taxi_stand":
            row.update(
                {
                    "district": item.get("district"),
                    "neighborhood": item.get("neighborhood"),
                    "street": item.get("street"),
                    "kapino": item.get("kapino"),
                }
            )
        elif kind == "charging_station":
            row.update(
                {
                    "district": item.get("district"),
                    "neighborhood": item.get("neighborhood"),
                    "address": item.get("address"),
                }
            )
        return row
