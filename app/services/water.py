from __future__ import annotations

from typing import Any

from app.connectors.izsu import IzsuClient
from app.core.envelope import Freshness, error_envelope, success_envelope
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services import sources
from app.services.sources import is_source_failure, source_failure_envelope


class WaterService:
    def __init__(self, *, settings: Settings, client: IzsuClient | None = None):
        self.settings = settings
        self.client = client or IzsuClient(settings)

    async def status(self, *, kind: str = "dams", limit: int | None = None) -> dict[str, Any]:
        if kind == "faults":
            return error_envelope(
                summary="İZSU arıza/su kesintisi akışı kullanılamıyor.",
                warning=(
                    "İZSU'nun açık arıza API'si doğrulama sırasında HTTP 500 döndürdü "
                    "(2026-10-28). Uydurma kesinti verisi üretilmemektedir."
                ),
                code="source_unavailable",
                sources=[sources.WATER],
                limits=["kind=faults", "source=openapi.izmir.bel.tr/api/izsu/arizakaynaklisukesintileri"],
                next_step="İZSU duyurularını resmî kanallardan kontrol edin veya daha sonra yeniden deneyin.",
            )
        if kind != "dams":
            raise InputValidationError("kind must be 'dams' or 'faults'", field="kind")

        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        try:
            rows, info = await self.client.dams()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            if not is_source_failure(exc):
                raise
            return source_failure_envelope(
                exc,
                summary="İZSU baraj doluluk verisi okunamadı.",
                used=[sources.WATER],
                limits=[f"limit={safe_limit}", "source=published İZSU dam CSV"],
            )
        ranked = sorted(
            (row for row in rows if row.get("occupancy_percent") is not None),
            key=lambda row: row["occupancy_percent"],
            reverse=True,
        )
        data = ranked[:safe_limit]
        summary = f"{len(data)} baraj listelendi."
        if data:
            summary = (
                f"{len(data)} baraj listelendi; en yüksek doluluk "
                f"%{data[0]['occupancy_percent']:.2f} ({data[0]['name']})."
            )
        return success_envelope(
            summary=summary,
            data=data,
            sources=[sources.WATER],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.izsu_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[f"limit={safe_limit}", "source=published İZSU dam CSV"],
            warnings=[
                "Veriler yayımlanan CSV dosyasından okunur; gecikme olabilir.",
                "Baraj doluluğu anlık tüketim veya kesinti tahmini değildir.",
            ],
            next_queries=["Belirli bir barajın ayrıntısı için adıyla arama yapın."],
        )
