from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from app.connectors.city_layers import CityLayerConnector
from app.core.envelope import Freshness, error_envelope, result_info, success_envelope
from app.core.geo import normalize_name
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services import sources

LIMITS = [
    "Bu veri GEÇMİŞ trafik ölçümleridir; canlı trafik yoğunluğu, gecikme veya "
    "ETA değildir. İzmir'de canlı trafik indeksi yayımlanmıyor "
    "(/api/ibb/trafikyogunluk 404).",
    "Segmentler sabit nokta çiftleridir (ör. 'Marina Kavşağı → Konak Pier'); "
    "serbest adres veya koordinat çözümlemesi yapılmaz.",
    "Hız ve süre kaynağın kendi ölçümüdür; birimleri (km/s, dakika) yayımdan doğrulanmıştır, hesaplanmamıştır.",
]


ISTANBUL = ZoneInfo("Europe/Istanbul")


def _age_hours(newest: str | None, now: datetime) -> float | None:
    """Hours since the newest published observation; ``None`` when unparsable.

    Source timestamps carry no offset and are İzmir local time, so a naive
    value is attached to Europe/Istanbul rather than treated as UTC.
    """
    if not newest:
        return None
    try:
        stamp = datetime.fromisoformat(str(newest))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ISTANBUL)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - stamp).total_seconds() / 3600


def _freshness_status(
    cache_status: str, age_hours: float | None, threshold: int
) -> Literal["fresh", "stale", "unknown"]:
    if cache_status == "stale":
        return "stale"
    if age_hours is None:
        return "unknown"
    return "stale" if age_hours > threshold else "fresh"


def _freshness_limits(newest: str | None, age_hours: float | None, threshold: int) -> list[str]:
    lines: list[str] = []
    if newest:
        lines.append(f"en_yeni_olcum={newest}")
        lines.append("tazelik_kaynagi=en_yeni_yayimlanan_olcum")
    if age_hours is not None:
        lines.append(f"veri_yasi_saat={age_hours:.1f}")
    lines.append(f"stale_after_hours={threshold}")
    return lines


def _parse_day(value: str | None, *, field: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise InputValidationError(f"{field} YYYY-MM-DD biçiminde olmalıdır", field=field) from exc


class TrafficService:
    def __init__(
        self,
        *,
        settings: Settings,
        api: CityLayerConnector | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.settings = settings
        self.api = api or CityLayerConnector(settings=settings)
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def list(
        self,
        *,
        segment: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        start = _parse_day(since, field="since")
        end = _parse_day(until, field="until")
        if start and end and start > end:
            raise InputValidationError("since, until'den önce ya da aynı gün olmalıdır", field="until")

        filtered = segment is not None or start is not None or end is not None
        try:
            if filtered:
                rows, info = await self.api.traffic_rows()
                total = len(rows)
            else:
                # One newest-first page: the volume follows the caller's limit
                # instead of paging all ~18k rows before cutting.
                rows, info, total = await self.api.traffic_recent(safe_limit)
        except Exception as exc:
            from app.services.sources import source_failure_envelope

            return source_failure_envelope(
                exc, summary="Ana arter trafik verisi kullanılamıyor.", used=[sources.TRAFFIC]
            )

        newest = max(
            (str(row.get("observed_at")) for row in rows if row.get("observed_at")),
            default=None,
        )
        age_hours = _age_hours(newest, self._now())
        stale_after = self.settings.traffic_stale_after_hours
        limits = [f"limit={safe_limit}"]
        limits.extend(_freshness_limits(newest, age_hours, stale_after))
        if not filtered:
            # ``matched`` is CKAN's total, which may include rows the mapper
            # cannot present; say so instead of implying a full local count.
            limits.append("matched_kaynagi=kaynak_toplam")
        if segment is not None:
            needle = normalize_name(segment)
            if not needle:
                raise InputValidationError("segment boş olamaz", field="segment")
            rows = [
                row
                for row in rows
                if needle in normalize_name(f"{row.get('segment_from') or ''} {row.get('segment_to') or ''}")
            ]
            limits.append(f"segment={segment.strip()[:60]}")
        if start or end:
            kept = []
            for row in rows:
                observed = str(row.get("observed_at") or "")[:10]
                try:
                    day = date.fromisoformat(observed)
                except ValueError:
                    continue
                if start and day < start:
                    continue
                if end and day > end:
                    continue
                kept.append(row)
            rows = kept
            if since:
                limits.append(f"since={since}")
            if until:
                limits.append(f"until={until}")

        rows.sort(key=lambda row: str(row.get("observed_at") or ""), reverse=True)
        matched = len(rows) if filtered else max(total, len(rows))
        data = rows[:safe_limit]
        truncated = matched > len(data)

        status = _freshness_status(info.status, age_hours, stale_after)
        warnings = list(LIMITS)
        if status == "stale" and age_hours is not None:
            warnings.append(
                f"Kaynağın yayımladığı en yeni ölçüm {newest} ({age_hours:.0f} saat önce); bu yüzden tazelik 'stale'."
            )
        elif status == "stale":
            warnings.append(
                "Kaynak yanıtı önbellekten 'stale' geldi ve en yeni ölçüm zamanı çözümlenemedi; tazelik 'stale'."
            )
        elif status == "unknown":
            warnings.append("Kaynak satırlarında çözümlenebilir ölçüm zamanı yok; tazelik bilinmiyor.")
        if not data:
            warnings.append(
                "Eşleşen ölçüm yok. Bu 'trafik akıcı' veya 'kayıt yok' kanıtı değildir; "
                "segment adını ve tarih aralığını kontrol edin."
            )
        if truncated:
            warnings.append(f"Toplam {matched} ölçüm eşleşti, ilk {len(data)} gösteriliyor.")

        return success_envelope(
            summary=(f"{len(data)} geçmiş trafik ölçümü listelendi" + (f"; toplam {matched}." if truncated else ".")),
            data=data,
            sources=[sources.TRAFFIC],
            freshness=Freshness(
                status=status,
                ttl_seconds=self.settings.city_layer_cache_ttl_seconds,
                source_updated_at=newest or info.source_updated_at,
            ),
            limits=limits,
            warnings=warnings,
            next_queries=[
                "Belirli bir koridor için segment parametresi kullanın.",
                "Tarih aralığı için since/until (YYYY-MM-DD) verin.",
            ],
            result=result_info(returned=len(data), matched=matched, truncated=truncated, scope="traffic_history"),
        )
