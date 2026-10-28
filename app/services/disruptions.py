from __future__ import annotations

from datetime import date
from typing import Any

from app.connectors.city_layers import BusNoticeConnector
from app.core.envelope import Freshness, error_envelope, success_envelope
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services import sources

LIMITS = [
    "Kaynak, ESHOT hat duyurularıdır (planlı güzergâh değişikliği gibi); canlı gecikme veya araç durumu değildir.",
    "Duyuru metni kaynağın kendi ifadesidir; etki alanı ve süresi bağımsız doğrulanmadı.",
    "Bitiş tarihi geçmiş duyurular sedece active=false ile listelenir.",
]


def _parse_timestamp(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


class DisruptionService:
    def __init__(self, *, settings: Settings, api: BusNoticeConnector | None = None):
        self.settings = settings
        self.api = api or BusNoticeConnector(settings)

    async def list(
        self,
        *,
        line: str | None = None,
        active_only: bool = False,
        today: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        if line is not None and not str(line).strip():
            raise InputValidationError("line must not be blank", field="line")
        try:
            reference = date.fromisoformat(today) if today else date.today()
        except ValueError as exc:
            raise InputValidationError("today must use YYYY-MM-DD", field="today") from exc

        try:
            rows, info = await self.api.bus_notices()
        except Exception as exc:
            return error_envelope(
                summary="EShot hat duyuruları kullanılamıyor.",
                warning=f"Kaynak isteği başarısız oldu: {type(exc).__name__}. Veri üretilmedi.",
                code="source_unavailable",
                sources=[sources.ESHOT_NOTICES],
            )

        limits = [f"limit={safe_limit}", f"reference_date={reference.isoformat()}"]
        enriched = []
        for row in rows:
            starts = _parse_timestamp(row.get("starts_at"))
            ends = _parse_timestamp(row.get("ends_at"))
            enriched.append(
                {
                    **row,
                    "active": bool(
                        (starts is None or starts <= reference)
                        and (ends is None or ends >= reference)
                    ),
                }
            )

        if line is not None:
            wanted = str(line).strip()
            enriched = [row for row in enriched if row.get("line") == wanted]
            limits.append(f"line={wanted[:20]}")
        if active_only:
            enriched = [row for row in enriched if row["active"]]

        enriched.sort(key=lambda row: (not row["active"], row.get("ends_at") or "", row.get("line") or ""))
        data = enriched[:safe_limit]

        warnings = list(LIMITS)
        if not data:
            warnings.append(
                "Eşleşen duyuru yok. Bu, aksaklık olmadığının kanıtı değildir."
            )
        return success_envelope(
            summary=f"{len(data)} ESHOT hat duyurusu listelendi.",
            data=data,
            sources=[sources.ESHOT_NOTICES],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.eshot_notices_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=limits,
            warnings=warnings,
            next_queries=["Belirli bir hat için line parametresi kullanın."],
            matched=len(enriched),
        )
