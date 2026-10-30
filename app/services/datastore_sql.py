"""Bounded SQL over a complete CKAN DataStore snapshot.

İzmir's CKAN does not expose ``datastore_search_sql``. The upstream Istanbul
server solves the same problem by copying an allowlisted resource locally and
running a constrained SELECT there; this is the İzmir equivalent. No resource is
downloaded unless its id is configured, and a snapshot that cannot be captured
completely returns a typed error instead of a partial aggregate.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any

from app.connectors.ckan import CkanClient
from app.core.envelope import Freshness, ResultInfo, Source, error_envelope, success_envelope
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import (
    InputValidationError,
    resolve_limit,
    validate_identifier,
)
from app.storage.guarded_sql import (
    QueryRejected,
    SnapshotRejected,
    execute_snapshot_query,
    validate_fields,
    validate_sql,
)

# One query at a time: snapshots can be tens of megabytes and the in-memory
# SQLite engine is deliberately bounded. A second caller waits rather than
# multiplying memory or racing the source.
_query_gate = asyncio.Lock()


@dataclass(frozen=True)
class Snapshot:
    fields: tuple[tuple[str, str], ...]
    records: list[dict]
    wire_bytes: int


def _validate_settings(settings: Settings) -> None:
    bounds = (
        (settings.ckan_sql_max_rows, 1, 50_000),
        (settings.ckan_sql_max_bytes, 1_024, 20 * 1024 * 1024),
        (settings.ckan_sql_page_size, 1, 5_000),
        (settings.ckan_sql_snapshot_ttl_seconds, 1, 3_600),
        (settings.ckan_sql_load_timeout_seconds, 0.01, 60),
        (settings.ckan_sql_query_timeout_seconds, 0.001, 2),
    )
    if any(not low <= value <= high for value, low, high in bounds):
        raise ValueError("CKAN SQL settings exceed the hard safety bounds")
    if len(settings.ckan_sql_allowed_resource_ids) > 100:
        raise ValueError("At most 100 SQL resources may be allowlisted")
    for value in settings.ckan_sql_allowed_resource_ids:
        validate_identifier(value, field="IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS")


class DatastoreSqlService:
    def __init__(self, *, settings: Settings, client: CkanClient | None = None):
        _validate_settings(settings)
        self.settings = settings
        self.client = client or CkanClient(settings)

    def _source(self, resource_id: str) -> Source:
        return Source(
            name="İzmir Açık Veri Portalı — sınırlı yerel kopya",
            publisher="İzmir Büyükşehir Belediyesi",
            url="https://acikveri.bizizmir.com",
            resource_id=resource_id,
            scope="complete_local_snapshot",
        )

    async def query(self, *, resource_id: str, sql: str, limit: int | None = None) -> dict[str, Any]:
        source = Source(
            name="İzmir Açık Veri Portalı — sınırlı yerel kopya",
            publisher="İzmir Büyükşehir Belediyesi",
            url="https://acikveri.bizizmir.com",
            resource_id=str(resource_id or "")[:120] or None,
            scope="complete_local_snapshot",
        )
        try:
            safe_id = validate_identifier(resource_id, field="resource_id")
            if safe_id not in self.settings.ckan_sql_allowed_resource_ids:
                raise InputValidationError(
                    "Kaynak SQL için etkin değil; IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS ayarlayın",
                    field="resource_id",
                )
            validate_sql(sql)
            safe_limit = resolve_limit(
                self.settings.default_limit if limit is None else limit,
                self.settings.default_limit,
                min(self.settings.max_limit, 100),
            )
        except InputValidationError as exc:
            return validation_error_envelope(
                exc,
                sources=[source],
                tool="izmir_datastore_query",
                limits=[
                    f"max_snapshot_rows={self.settings.ckan_sql_max_rows}",
                    f"max_snapshot_wire_bytes={self.settings.ckan_sql_max_bytes}",
                ],
            )

        source = self._source(safe_id)
        limits = [
            "engine=isolated_in_memory_sqlite",
            "table=records",
            "no_upstream_sql",
            "select_only; allowlisted_functions; no_app_database_access",
            f"max_snapshot_rows={self.settings.ckan_sql_max_rows}",
            f"max_snapshot_wire_bytes={self.settings.ckan_sql_max_bytes}",
            f"outer_limit={safe_limit}",
            "result_max_bytes=262144",
            f"query_timeout_seconds={self.settings.ckan_sql_query_timeout_seconds}",
            "max_vm_steps=2000000",
            "no_partial_aggregates",
        ]
        try:
            async with _query_gate:
                key = _cache_key(self.settings, self.client, safe_id)
                snapshot, info = await cached_source_data(
                    key,
                    ttl_seconds=self.settings.ckan_sql_snapshot_ttl_seconds,
                    loader=lambda: asyncio.wait_for(
                        self._load_snapshot(safe_id),
                        timeout=self.settings.ckan_sql_load_timeout_seconds,
                    ),
                )
                data, truncated = await asyncio.to_thread(
                    execute_snapshot_query,
                    snapshot.fields,
                    snapshot.records,
                    sql,
                    limit=safe_limit,
                    timeout_seconds=self.settings.ckan_sql_query_timeout_seconds,
                    max_rows=getattr(self.settings, "ckan_sql_max_rows", 50_000),
                    max_bytes=getattr(self.settings, "ckan_sql_max_bytes", 20 * 1024 * 1024),
                )
        except QueryRejected as exc:
            return validation_error_envelope(
                InputValidationError(str(exc), field="sql"),
                sources=[source],
                tool="izmir_datastore_query",
                limits=limits,
            )
        except SnapshotRejected as exc:
            return error_envelope(
                summary="Tam ve sınırlı veri kopyası alınamadı.",
                warning=(
                    f"{exc}. Kısmi toplam üretilmedi; kaynak toplamı ve yapılandırılmış kopya limitlerini kontrol edin."
                ),
                code="source_unavailable",
                temporary=False,
                sources=[source],
                limits=limits,
                next_step=(
                    "IZMIR_MCP_CKAN_SQL_MAX_ROWS/BYTES değerlerini yalnızca kaynağın "
                    "boyutunu kontrol ettikten sonra artırın; kısmi yakalamayı asla toplamayın."
                ),
            )
        except Exception as exc:  # connector failures are typed, not leaked
            return source_error_envelope(
                exc,
                summary="Tam ve sınırlı veri kopyası alınamadı.",
                sources=[source],
                limits=limits,
            )

        limits.extend(
            [
                f"snapshot_rows={len(snapshot.records)}",
                f"snapshot_wire_bytes={snapshot.wire_bytes}",
            ]
        )
        warnings = [
            "Freshness, satırların yaşı değil kopyanın alınma zamanıdır.",
            "HTTP sayfaları işlemsel olarak dondurulmuş değildir; toplam değişmeden satır güncellemesi olabilir.",
            "Sorgu tam kaynak toplamı üzerinde çalıştı; kısmi sonuç toplanmadı.",
        ]
        if truncated:
            warnings.append("SQL çıktısı uygulanan sonuç limitiyle kesildi; toplam girdiler tamdı.")
        next_step = (
            "Sonucu daraltın veya limiti artırın; bu tam çıktı değildir."
            if truncated
            else "Bu SELECT için sonuç tamdır; kaynak anlık görüntüsü değişebilir."
        )
        return success_envelope(
            summary=(f"{len(data)} SQL satırı, {len(snapshot.records)} satırlık tam yerel kopyadan üretildi."),
            data=data,
            sources=[source],
            freshness=Freshness(
                status="fresh",
                retrieved_at=info.retrieved_at,
                ttl_seconds=self.settings.ckan_sql_snapshot_ttl_seconds,
            ),
            limits=limits,
            warnings=warnings,
            next_queries=[
                "Kolon adlarını izmir_get_resource_schema ile doğrulayın.",
                "Büyük gruplarda önce COUNT(*) ile kaynak toplamını kontrol edin.",
            ],
            result=ResultInfo(
                returned=len(data),
                truncated=truncated,
                scope="sql",
                next_step=next_step,
            ),
        )

    async def _load_snapshot(self, resource_id: str) -> Snapshot:
        state = {"bytes": 0}

        async def page(limit: int, offset: int) -> dict[str, Any]:
            remaining = self.settings.ckan_sql_max_bytes - state["bytes"]
            if remaining <= 0:
                raise SnapshotRejected("Snapshot byte budget exhausted")
            value, received = await self.client.datastore_search_bounded(
                resource_id=resource_id,
                limit=limit,
                offset=offset,
                max_bytes=remaining,
            )
            if type(received) is not int or received <= 0 or received > remaining:
                raise SnapshotRejected("Invalid snapshot byte accounting")
            state["bytes"] += received
            return value

        metadata = await page(0, 0)
        fields = validate_fields(metadata.get("fields"))
        total = metadata.get("total")
        if type(total) is not int or not 0 <= total <= self.settings.ckan_sql_max_rows or metadata.get("records") != []:
            raise SnapshotRejected("Exact source total is required and must fit the snapshot row budget")
        records: list[dict[str, Any]] = []
        column_names = {name for name, _kind in fields}
        last_id: int | None = None
        while len(records) < total:
            requested = min(self.settings.ckan_sql_page_size, total - len(records))
            value = await page(requested, len(records))
            rows = value.get("records")
            if (
                type(value.get("total")) is not int
                or value.get("total") != total
                or validate_fields(value.get("fields")) != fields
                or not isinstance(rows, list)
                or not 0 < len(rows) <= requested
            ):
                raise SnapshotRejected("Incomplete or changing DataStore page")
            for row in rows:
                if not isinstance(row, dict) or not set(row) <= column_names:
                    raise SnapshotRejected("Malformed DataStore record")
                row_id = row.get("_id")
                if type(row_id) is not int or (last_id is not None and row_id <= last_id):
                    raise SnapshotRejected("Duplicate or unstable DataStore _id ordering")
                last_id = row_id
            records.extend(rows)

        final = await page(0, 0)
        if (
            type(final.get("total")) is not int
            or final.get("total") != total
            or final.get("records") != []
            or validate_fields(final.get("fields")) != fields
        ):
            raise SnapshotRejected("DataStore changed while capturing pages")
        return Snapshot(fields=fields, records=records, wire_bytes=state["bytes"])


def _cache_key(settings: Settings, client: CkanClient, resource_id: str) -> str:
    return "ckan.sql.snapshot." + json.dumps(
        [
            getattr(client, "base_url", "izmir"),
            resource_id,
            settings.ckan_sql_max_rows,
            settings.ckan_sql_max_bytes,
            settings.ckan_sql_page_size,
        ],
        separators=(",", ":"),
    )
