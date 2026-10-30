from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from app.connectors.izsu import IzsuClient, turkish_fold
from app.core.envelope import Freshness, error_envelope, success_envelope
from app.core.settings import Settings
from app.core.validation import (
    InputValidationError,
    resolve_limit,
    validate_date,
    validate_text,
)
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
            raise InputValidationError("kind 'dams' veya 'faults' olmalıdır", field="kind")

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

    async def dam_status(
        self,
        *,
        date: str | None = None,
        dam_name: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Dam levels for a given day from the İZSU JSON API, optionally one dam."""
        day = validate_date(date)
        if day > date_cls.today().isoformat():
            raise InputValidationError("date gelecekte olamaz", field="date")
        wanted = None
        if dam_name is not None and str(dam_name).strip():
            wanted = turkish_fold(validate_text(dam_name, field="dam_name", max_length=80))
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        limits = [f"date={day}", f"limit={safe_limit}", "source=izsu.gov.tr DamWaterStatus JSON"]
        if wanted:
            limits.append(f"dam_name={dam_name.strip()}")
        fallback = False
        try:
            rows, info = await self.client.dam_status(day)
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            if not is_source_failure(exc):
                raise
            # TLS/connection failures on the JSON host fall back to the
            # published CSV (certificate verification stays enabled).
            csv_loader = getattr(self.client, "dams_csv", None)
            csv_result = None
            if csv_loader is not None:
                try:
                    csv_result = await csv_loader()
                except Exception as csv_exc:  # noqa: BLE001 - report the original failure
                    if not is_source_failure(csv_exc):
                        raise
            if csv_result is None:
                return source_failure_envelope(
                    exc,
                    summary="İZSU baraj durumu (JSON) okunamadı.",
                    used=[sources.WATER],
                    limits=limits,
                )
            rows, info = csv_result
            fallback = True
            limits = [item if not item.startswith("source=") else "source=published İZSU dam CSV" for item in limits]
            limits.append("source: csv_fallback")
            limits.append("CSV kaynağında gerçek su seviyesi yok; water_level alanı boş (null) bırakıldı.")
        if wanted:
            rows = [row for row in rows if wanted in turkish_fold(row["name"])]
        ranked = sorted(
            rows,
            key=lambda row: (row.get("occupancy_percent") is None, -(row.get("occupancy_percent") or 0)),
        )
        data = ranked[:safe_limit]
        warnings = ["Baraj doluluğu anlık tüketim veya kesinti tahmini değildir."]
        if fallback:
            warnings.insert(
                0,
                "İZSU JSON servisine bağlanılamadı (TLS/bağlantı hatası); veriler yayımlanan "
                "CSV dosyasından okundu. CSV yalnızca en son yayımlanan durumu içerir ve "
                "tarih seçimini desteklemez.",
            )
            if date is not None and day != date_cls.today().isoformat():
                warnings.insert(
                    0,
                    f"İstenen tarih ({day}) CSV yedeğinde desteklenmiyor; dönen veriler "
                    "o güne ait DEĞİLDİR, en son yayımlanan durumdur.",
                )
        if not data:
            summary = f"{day} için baraj verisi bulunamadı."
            warnings.insert(
                0,
                "İZSU bu tarih/baraj için kayıt döndürmedi; veri henüz yayımlanmamış "
                "veya baraj adı eşleşmemiş olabilir.",
            )
        else:
            label = "Son yayımlanan CSV (yedek kaynak)" if fallback else day
            summary = f"{label}: {len(data)} baraj listelendi."
            if data[0].get("occupancy_percent") is not None:
                summary = (
                    f"{label}: {len(data)} baraj listelendi; en yüksek doluluk "
                    f"%{data[0]['occupancy_percent']:.2f} ({data[0]['name']})."
                )
        return success_envelope(
            summary=summary,
            data=data,
            sources=[sources.WATER],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.client._ttl_for(day)
                if hasattr(self.client, "_ttl_for") and not fallback
                else self.settings.izsu_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=limits,
            warnings=warnings,
            next_queries=["Başka bir gün için date=YYYY-MM-DD verin."],
        )
