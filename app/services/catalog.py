from __future__ import annotations

import json
from typing import Any

from app.connectors.ckan import CkanClient, CkanNotFoundError
from app.core.envelope import Freshness, Source, error_envelope, result_info, success_envelope
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import (
    validate_search,
    validate_sort,
    InputValidationError,
    resolve_limit,
    validate_filters,
    validate_identifier,
    validate_text,
)

CKAN_SOURCE = Source(
    name="İzmir Açık Veri Portalı",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com",
)


class CatalogService:
    def __init__(self, *, settings: Settings, client: CkanClient | None = None):
        self.settings = settings
        self.client = client or CkanClient(settings)

    async def search_datasets(
        self, *, query: str, formats: list[str] | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        try:
            safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
            safe_query = validate_text(query, field="query", max_length=120)
            safe_formats = self._validate_formats(formats)
        except InputValidationError as exc:
            return _validation_error(exc)
        try:
            result = await self._cached_package_search(query=safe_query, rows=safe_limit, formats=safe_formats)
        except Exception as exc:
            return _source_error("İzmir açık veri kataloğu araması kullanılamıyor.", exc)
        datasets = result.get("results", [])
        data = sorted(
            [self._dataset_summary(dataset, query=safe_query) for dataset in datasets],
            key=lambda item: item["relevance"]["score"],
            reverse=True,
        )
        return success_envelope(
            summary=f"'{safe_query}' için {len(data)} veri seti sonucu bulundu.",
            data=data,
            sources=[CKAN_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.ckan_catalog_cache_ttl_seconds),
            limits=[f"limit={safe_limit}", "source=CKAN package_search"],
            matched=result.get("count"),
        )

    async def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        try:
            safe_id = validate_identifier(dataset_id, field="dataset_id")
        except InputValidationError as exc:
            return _validation_error(exc)
        try:
            dataset = await self._cached_package_show(safe_id)
        except CkanNotFoundError:
            return error_envelope(
                summary=f"Veri seti bulunamadı: {safe_id}.",
                warning=f"dataset_id={safe_id} ile eşleşen veri seti yok.",
                code="not_found",
                field="dataset_id",
                sources=[CKAN_SOURCE],
                next_step="Kataloğu izmir_search_datasets ile arayın ve dönen id'yi kullanın.",
            )
        except Exception as exc:
            return _source_error(f"{safe_id} için veri seti üst verisi kullanılamıyor.", exc)
        return success_envelope(
            summary=f"'{dataset.get('title') or safe_id}' veri seti üst verisi alındı.",
            data=[self._dataset_detail(dataset)],
            sources=[CKAN_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.ckan_catalog_cache_ttl_seconds),
            limits=["source=CKAN package_show"],
        )

    async def get_resource_schema(self, resource_id: str) -> dict[str, Any]:
        try:
            safe_id = validate_identifier(resource_id, field="resource_id")
        except InputValidationError as exc:
            return _validation_error(exc)
        try:
            result = await self._cached_datastore_search(resource_id=safe_id, limit=0)
        except CkanNotFoundError:
            return error_envelope(
                summary=f"Kaynak bulunamadı: {safe_id}.",
                warning=f"resource_id={safe_id} ile eşleşen DataStore kaynağı yok.",
                code="not_found",
                field="resource_id",
                sources=[CKAN_SOURCE],
                next_step="Önce veri setinin kaynaklarını izmir_get_dataset ile inceleyin.",
            )
        except Exception as exc:
            return _source_error(f"{safe_id} için kaynak şeması kullanılamıyor.", exc)
        fields = result.get("fields", [])
        return success_envelope(
            summary=f"'{safe_id}' kaynağının şemasında {len(fields)} alan var.",
            data=[{"resource_id": safe_id, "fields": fields}],
            sources=[CKAN_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.ckan_resource_cache_ttl_seconds),
            limits=["source=CKAN datastore_search", "limit=0"],
        )

    async def query_resource(
        self,
        *,
        resource_id: str,
        filters: dict | None = None,
        search: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
            safe_id = validate_identifier(resource_id, field="resource_id")
            safe_filters = validate_filters(filters)
            safe_search = validate_search(search)
            safe_sort = validate_sort(sort)
        except InputValidationError as exc:
            return _validation_error(exc)
        try:
            if safe_filters or safe_sort:
                schema = await self._cached_datastore_search(resource_id=safe_id, limit=0)
                known = [field.get("id") for field in schema.get("fields", []) if isinstance(field, dict)]
                unknown = sorted(set(safe_filters or {}) - set(known))
                if known and unknown:
                    return error_envelope(
                        summary="Bilinmeyen filtre alanı.",
                        warning=f"Bilinmeyen filtre alanı: {', '.join(unknown)}. Geçerli alanlar: {', '.join(map(str, known))}",
                        code="validation_error",
                        field="filters",
                        sources=[CKAN_SOURCE],
                        next_step="Kaynak şemasını inceleyin ve duyurulan sütunları kullanın.",
                    )
                if safe_sort and known:
                    column = safe_sort.split(" ", 1)[0]
                    if column not in known:
                        return error_envelope(
                            summary="Bilinmeyen sıralama sütunu.",
                            warning=(
                                f"Bilinmeyen sıralama sütunu '{column}'. Geçerli alanlar: {', '.join(map(str, known))}"
                            ),
                            code="validation_error",
                            field="sort",
                            sources=[CKAN_SOURCE],
                            next_step="Kaynak şemasını inceleyin ve duyurulan bir sütuna göre sıralayın.",
                        )
            result = await self._cached_datastore_search(
                resource_id=safe_id,
                filters=safe_filters,
                query=safe_search,
                sort=safe_sort,
                limit=safe_limit,
            )
        except CkanNotFoundError:
            return error_envelope(
                summary=f"Kaynak bulunamadı: {safe_id}.",
                warning=f"resource_id={safe_id} ile eşleşen DataStore kaynağı yok.",
                code="not_found",
                field="resource_id",
                sources=[CKAN_SOURCE],
            )
        except Exception as exc:
            return _source_error(f"{safe_id} için kaynak sorgusu kullanılamıyor.", exc)
        records = result.get("records", [])
        return success_envelope(
            summary=f"'{safe_id}' kaynağından {len(records)} kayıt döndürüldü.",
            data=records,
            sources=[CKAN_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.ckan_resource_cache_ttl_seconds),
            limits=[
                f"limit={safe_limit}",
                "source=CKAN datastore_search",
                *([f"q={safe_search[:60]}"] if safe_search else []),
                *([f"sort={safe_sort}"] if safe_sort else []),
                "Sunucu tarafı SQL desteklenmez; yalnızca filtre, q ve sort.",
            ],
            matched=result.get("total"),
        )

    async def _cached_package_search(self, *, query: str, rows: int, formats: list[str] | None) -> dict[str, Any]:
        key = _cache_key(
            "ckan.package_search",
            {"query": query.strip(), "rows": rows, "formats": sorted({f.upper() for f in formats or []})},
        )
        value, _info = await cached_source_data(
            key,
            ttl_seconds=self.settings.ckan_catalog_cache_ttl_seconds,
            loader=lambda: self.client.package_search(query=query, rows=rows, formats=formats),
        )
        return value

    async def _cached_package_show(self, dataset_id: str) -> dict[str, Any]:
        key = _cache_key("ckan.package_show", {"dataset_id": dataset_id.strip()})
        value, _info = await cached_source_data(
            key,
            ttl_seconds=self.settings.ckan_catalog_cache_ttl_seconds,
            loader=lambda: self.client.package_show(dataset_id),
        )
        return value

    async def _cached_datastore_search(
        self,
        *,
        resource_id: str,
        limit: int,
        filters: dict | None = None,
        offset: int = 0,
        query: str | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        key = _cache_key(
            "ckan.datastore_search",
            {
                "resource_id": resource_id,
                "limit": limit,
                "filters": filters or {},
                "offset": offset,
                "query": query,
                "sort": sort,
            },
        )
        value, _info = await cached_source_data(
            key,
            ttl_seconds=self.settings.ckan_resource_cache_ttl_seconds,
            loader=lambda: self.client.datastore_search(
                resource_id=resource_id,
                limit=limit,
                filters=filters,
                offset=offset,
                query=query,
                sort=sort,
            ),
        )
        return value

    def _dataset_summary(self, dataset: dict[str, Any], *, query: str | None = None) -> dict[str, Any]:
        resources = dataset.get("resources") or []
        datastore_resources = [r for r in resources if r.get("datastore_active")]
        return {
            "id": dataset.get("id"),
            "slug": dataset.get("name"),
            "title": dataset.get("title"),
            "notes": dataset.get("notes"),
            "license": dataset.get("license_title") or dataset.get("license_id"),
            "metadata_modified": dataset.get("metadata_modified"),
            "formats": sorted({(r.get("format") or "").upper() for r in resources if r.get("format")}),
            "resource_count": len(resources),
            "datastore_active_count": len(datastore_resources),
            "preferred_resources": [
                {
                    "id": r.get("id"),
                    "name": r.get("name") or r.get("description"),
                    "format": (r.get("format") or "").upper(),
                    "datastore_active": bool(r.get("datastore_active")),
                }
                for r in datastore_resources[:3]
            ],
            "relevance": self._relevance(dataset, query),
        }

    def _dataset_detail(self, dataset: dict[str, Any]) -> dict[str, Any]:
        detail = self._dataset_summary(dataset)
        detail["resources"] = [
            {
                "id": r.get("id"),
                "name": r.get("name") or r.get("description"),
                "format": (r.get("format") or "").upper(),
                "url": r.get("url"),
                "datastore_active": bool(r.get("datastore_active")),
            }
            for r in dataset.get("resources", [])
        ]
        return detail

    def _relevance(self, dataset: dict[str, Any], query: str | None) -> dict[str, Any]:
        terms = [term.casefold() for term in (query or "").split() if term.strip()]
        haystack = " ".join(
            [
                dataset.get("title") or "",
                dataset.get("name") or "",
                dataset.get("notes") or "",
                " ".join(tag.get("name", "") for tag in dataset.get("tags", []) if isinstance(tag, dict)),
            ]
        ).casefold()
        matched = [term for term in terms if term in haystack]
        has_datastore = any(r.get("datastore_active") for r in dataset.get("resources", []))
        return {
            "score": len(matched) + (2 if has_datastore else 0),
            "matched_query_terms": matched,
            "has_datastore": has_datastore,
        }

    def _validate_formats(self, formats: list[str] | None) -> list[str] | None:
        if formats is None:
            return None
        if len(formats) > 10:
            raise InputValidationError("formats en fazla 10 öğe içerebilir", field="formats")
        return [validate_identifier(fmt, field="formats", max_length=20).upper() for fmt in formats]


def _validation_error(exc: InputValidationError) -> dict[str, Any]:
    return error_envelope(
        summary="Geçersiz istek girdisi.",
        warning=str(exc),
        code="validation_error",
        field=exc.field,
        sources=[CKAN_SOURCE],
    )


def _source_error(summary: str, exc: Exception) -> dict[str, Any]:
    """Typed source failure: 429 is temporary rate limiting, not an outage."""
    from app.services.sources import source_failure_envelope

    return source_failure_envelope(exc, summary=summary, used=[CKAN_SOURCE])


def _cache_key(prefix: str, payload: dict[str, Any]) -> str:
    return f"{prefix}.{json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
