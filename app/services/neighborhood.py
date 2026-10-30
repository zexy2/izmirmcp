from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.city_layers import CityLayerConnector
from app.core.envelope import Freshness, Source, error_envelope, result_info, success_envelope
from app.core.geo import normalize_name, turkish_title
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services import sources
from app.services.places import PlaceResolver

LIMITS = [
    "Mahalle profili yayımlanmış nüfus ve bina sayısı katmanlarından birleştirilir; "
    "hane, gelir, yaş dağılımı veya hizmet erişimi bilgisi yoktur.",
    "Nüfus ve bina katmanları farklı tarihlerde yayımlanır; aynı yılın verisi "
    "oldukları varsayılmaz. `population_year` / `building_year` null ise kaynak "
    "yıl yayımlamıyor demektir.",
    "Kişi/bina oranı ham bölmedir; nüfus sayımı ile bina stokunun aynı anda "
    "ölçüldüğü anlamına gelmez.",
]


class NeighborhoodService:
    def __init__(self, *, settings: Settings, api: CityLayerConnector | None = None):
        self.settings = settings
        self.api = api or CityLayerConnector(settings=settings)

    async def profile(
        self,
        *,
        neighborhood: str | None = None,
        district: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        if neighborhood is None and district is None:
            raise InputValidationError(
                "neighborhood (isteğe bağlı district ile) ya da yalnızca district verin",
                field="neighborhood",
            )
        resolved_district: str | None = None
        if neighborhood is not None:
            try:
                place = PlaceResolver().resolve_neighborhood(neighborhood, district=district)
            except InputValidationError as exc:
                # The resolver names the generic `place` field; this tool's
                # caller supplied `neighborhood`, so report that instead.
                raise InputValidationError(str(exc), field="neighborhood") from exc
            resolved_district = place.district
        else:
            resolved_district = PlaceResolver().resolve_district(district).name

        outcomes = await asyncio.gather(
            self.api.population_rows(), self.api.building_rows(), return_exceptions=True
        )
        population, population_info = self._split(outcomes[0])
        buildings, building_info = self._split(outcomes[1])

        used: list[Source] = []
        warnings = list(LIMITS)
        statuses: list[str] = []
        observed: list[str] = []
        if population is None:
            warnings.append("Nüfus katmanı okunamadı (unavailable); nüfus alanları null döner.")
        else:
            used.append(sources.NEIGHBORHOOD_POPULATION)
            statuses.append(population_info.status)
            if population_info.source_updated_at:
                observed.append(population_info.source_updated_at)
        if buildings is None:
            warnings.append("Bina katmanı okunamadı (unavailable); bina alanları null döner.")
        else:
            used.append(sources.NEIGHBORHOOD_BUILDINGS)
            statuses.append(building_info.status)
            if building_info.source_updated_at:
                observed.append(building_info.source_updated_at)

        if not used:
            return error_envelope(
                summary="Mahalle profili kaynakları okunamadı.",
                warning="Nüfus ve bina katmanlarının ikisi de yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=LIMITS,
            )

        keys: set[tuple[str, str]] = set()
        for rows in (population, buildings):
            if rows is None:
                continue
            for row in rows:
                if row.get("district") and row.get("name"):
                    keys.add((row["district"], row["name"]))

        if neighborhood is None:
            target = normalize_name(resolved_district or "")
            selected = sorted(
                key for key in keys if normalize_name(key[0]) == target
            )
            if not selected:
                raise InputValidationError(
                    f"'{resolved_district}' için yayımlanmış mahalle profili bulunamadı.",
                    field="district",
                )
            matched = [self._row(population, buildings, district, name) for district, name in selected]
            matched.sort(key=lambda row: row["neighborhood_label"] or row["neighborhood"] or "")
            data = matched[:safe_limit]
            scope = "district"
            summary = (
                f"{resolved_district} için {len(matched)} mahalle profili bulundu"
                + (f"; ilk {len(data)} gösteriliyor." if len(matched) > len(data) else ".")
            )
        else:
            try:
                target_place = PlaceResolver().resolve_neighborhood(
                    neighborhood, district=district
                )
            except InputValidationError as exc:
                raise InputValidationError(str(exc), field="neighborhood") from exc
            target_name = normalize_name(target_place.name)
            target_district = normalize_name(resolved_district or "")
            match = next(
                (
                    key
                    for key in keys
                    if normalize_name(key[0]) == target_district
                    and normalize_name(key[1]) == target_name
                ),
                None,
            )
            if match is None:
                raise InputValidationError(
                    "neighborhood yayımlanmış nüfus veya bina katmanında yok",
                    field="neighborhood",
                )
            matched = [self._row(population, buildings, match[0], match[1])]
            data = matched
            scope = "neighborhood"
            summary = (
                f"{turkish_title(match[1]) or match[1]} "
                f"({turkish_title(match[0]) or match[0]}) profili: "
                f"nüfus {matched[0]['population_total'] or 'bilinmiyor'}, "
                f"bina {matched[0]['buildings'] or 'bilinmiyor'}."
            )

        return success_envelope(
            summary=summary,
            data=data,
            sources=used,
            freshness=Freshness(
                status="stale" if "stale" in statuses else "fresh",
                ttl_seconds=self.settings.city_layer_cache_ttl_seconds,
                source_updated_at=max(observed) if observed else None,
            ),
            limits=[
                *LIMITS,
                f"limit={safe_limit}",
                f"district={resolved_district}",
                *( [f"neighborhood={neighborhood}"] if neighborhood else [] ),
            ],
            warnings=warnings,
            next_queries=[
                "Yakındaki hizmetler için izmir_nearby kullanın.",
                "İlçedeki tüm mahalleler için district ile çağırın.",
            ],
            result=result_info(
                returned=len(data),
                matched=len(matched),
                truncated=len(matched) > len(data),
                scope=scope,
            ),
        )

    @staticmethod
    def _split(outcome: Any) -> tuple[list[dict[str, Any]] | None, Any]:
        if isinstance(outcome, BaseException):
            return None, None
        rows, info = outcome
        return rows, info

    @staticmethod
    def _row(
        population: list[dict[str, Any]] | None,
        buildings: list[dict[str, Any]] | None,
        district: str | None,
        name: str | None,
    ) -> dict[str, Any]:
        def find(rows):
            if not rows:
                return None
            wanted_d, wanted_n = normalize_name(district or ""), normalize_name(name or "")
            for row in rows:
                if (
                    normalize_name(row.get("district") or "") == wanted_d
                    and normalize_name(row.get("name") or "") == wanted_n
                ):
                    return row
            return None

        pop = find(population)
        bld = find(buildings)
        def as_count(value):
            return int(value) if isinstance(value, (int, float)) else None

        male = as_count(pop.get("male")) if pop else None
        female = as_count(pop.get("female")) if pop else None
        total = (
            (male or 0) + (female or 0) if male is not None or female is not None else None
        )
        count = as_count(bld.get("buildings")) if bld else None
        ratio = round(total / count, 2) if total and count else None
        return {
            "district": district,
            "district_label": turkish_title(district),
            "neighborhood": name,
            "neighborhood_label": turkish_title(name),
            "population_total": total,
            "population_male": male,
            "population_female": female,
            "population_year": None,
            "buildings": count,
            "other_buildings": as_count(bld.get("other_buildings")) if bld else None,
            "building_year": None,
            "persons_per_building": ratio,
        }
