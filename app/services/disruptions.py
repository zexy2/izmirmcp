from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from app.connectors.city_layers import BusNoticeConnector
from app.connectors.operators import OperatorAnnouncementConnector
from app.core.envelope import Source, error_envelope, result_info, success_envelope
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services import sources
from app.core.envelope import Freshness

# "izban" is deliberately listed: it has no reachable feed, so asking for it
# must return an explicit unavailable result rather than silent silence.
OPERATORS = ("eshot", "metro", "izdeniz", "izban")

LIMITS = [
    "Kaynak, operatörlerin kendi duyurularıdır (planlı güzergâh değişikliği, sefer "
    "düzenlemesi gibi); canlı gecikme, araç konumu veya arıza telemetrisi değildir.",
    "Duyuru metni kaynağın kendi ifadesidir; etki alanı ve süresi bağımsız doğrulanmadı.",
    "Yalnızca ESHOT duyuruları makine-okunur başlangıç/bitiş tarihi yayımlar; diğer "
    "operatörlerde active alanı null döner.",
    "İZBAN için erişilebilir bir duyuru akışı yoktur; sonuç her zaman unavailable'dır.",
]


def _negate_date(value: str | None) -> tuple[int, str]:
    """Sort most-recent-first without parsing arbitrary text.

    ISO-like timestamps sort lexicographically, so inverting the numeric date
    components keeps the ordering stable while tolerating unknown values.
    """
    text = str(value or "")
    digits = "".join(char for char in text[:10] if char.isdigit())
    return (-int(digits), text) if len(digits) >= 8 else (0, text)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class DisruptionService:
    def __init__(
        self,
        *,
        settings: Settings,
        api: BusNoticeConnector | None = None,
        operators: OperatorAnnouncementConnector | None = None,
    ):
        self.settings = settings
        self.api = api or BusNoticeConnector(settings)
        self.operators = operators or OperatorAnnouncementConnector(settings)

    async def list(
        self,
        *,
        operator: str | None = None,
        line: str | None = None,
        active_only: bool = False,
        today: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
        if line is not None and not str(line).strip():
            raise InputValidationError("line must not be blank", field="line")
        if operator is not None:
            operator = str(operator).strip().casefold()
            if operator not in OPERATORS:
                raise InputValidationError(
                    f"operator must be one of: {', '.join(OPERATORS)}", field="operator"
                )
        try:
            reference = date.fromisoformat(today) if today else date.today()
        except ValueError as exc:
            raise InputValidationError("today must use YYYY-MM-DD", field="today") from exc

        selected = [operator] if operator else ["eshot", "metro", "izdeniz"]

        if selected == ["izban"]:
            return error_envelope(
                summary="İZBAN duyuru akışı kullanılamıyor.",
                warning=(
                    "İZBAN için erişilebilir makine-okunur duyuru/aksaklık ucu doğrulanamadı "
                    "(2026-10-28: Rss.aspx ve Sayfalar/Single.aspx HTTP 302 → FileNotFound; "
                    "metrotramapi'de İZBAN duyuru yolu 404). Duyuru yok sayılmaz, kaynak "
                    "erişilemiyor olarak bildirilir."
                ),
                code="source_unavailable",
                sources=[sources.IZBAN_NOTICES],
                limits=LIMITS,
            )

        loaders = {
            "eshot": (self.api.bus_notices, sources.ESHOT_NOTICES),
            "metro": (self.operators.metro_announcements, sources.METRO_NOTICES),
            "izdeniz": (self.operators.ferry_announcements, sources.FERRY_NOTICES),
        }
        outcomes = await asyncio.gather(
            *(loaders[name][0]() for name in selected), return_exceptions=True
        )

        rows: list[dict[str, Any]] = []
        used: list[Source] = []
        unavailable: list[str] = []
        statuses: list[str] = []
        observed: list[str] = []
        empty_operators: list[str] = []

        for name, outcome in zip(selected, outcomes):
            _loader, source = loaders[name]
            if isinstance(outcome, BaseException):
                unavailable.append(name)
                continue
            items, info = outcome
            used.append(source)
            statuses.append(info.status)
            if info.source_updated_at:
                observed.append(info.source_updated_at)
            if not items:
                empty_operators.append(name)
            for item in items:
                rows.append(self._normalise(name, item, reference))

        if not used:
            return error_envelope(
                summary="Seçilen operatörlerin duyuruları okunamadı.",
                warning="Hiçbir operatör duyuru kaynağı yanıt vermedi.",
                code="source_unavailable",
                sources=[],
                limits=LIMITS,
            )

        warnings = list(LIMITS)
        if unavailable:
            warnings.append(
                f"{', '.join(unavailable)} duyuru kaynağı okunamadı (unavailable); "
                "bu operatör için 'aksaklık yok' sonucu çıkarılmamalıdır."
            )
        if empty_operators:
            warnings.append(
                f"{', '.join(empty_operators)} kaynağı bu an için boş duyuru listesi döndürdü; "
                "bu 'duyuru yok' kanıtı değildir."
            )

        limits = [f"limit={safe_limit}", f"reference_date={reference.isoformat()}"]
        if operator:
            limits.append(f"operator={operator}")
        else:
            limits.append(f"operators={','.join(selected)}")

        if line is not None:
            wanted = str(line).strip()
            rows = [row for row in rows if row.get("line") == wanted]
            limits.append(f"line={wanted[:20]}")
        if active_only:
            rows = [row for row in rows if row.get("active") is True]

        # Active first, then the most recently published; reverse the date sort
        # so a notice published in 2021 does not outrank today's announcement.
        rows.sort(
            key=lambda row: (
                row.get("active") is not None and not row["active"],
                _negate_date(row.get("published_at")),
                row.get("operator") or "",
            )
        )
        matched = len(rows)
        data = rows[:safe_limit]
        truncated = matched > len(data)
        if truncated:
            warnings.append(
                f"Toplam {matched} duyuru eşleşti, ilk {len(data)} gösteriliyor; bu tam liste değildir."
            )
        if not data:
            warnings.append("Eşleşen duyuru yok. Bu, aksaklık olmadığının kanıtı değildir.")

        return success_envelope(
            summary=(
                f"{len(data)} duyuru listelendi"
                f" ({', '.join(selected)}); toplam {matched} eşleşme."
                + (" İlk sonuçlar gösteriliyor." if truncated else "")
            ),
            data=data,
            sources=used,
            freshness=Freshness(
                status="stale" if "stale" in statuses else "fresh",
                ttl_seconds=self.settings.eshot_notices_cache_ttl_seconds,
                source_updated_at=max(observed) if observed else None,
            ),
            limits=limits,
            warnings=warnings,
            next_queries=[
                "Belirli bir operatör için operator parametresi kullanın.",
                "Belirli bir hat için line parametresi kullanın (yalnızca ESHOT).",
            ],
            result=result_info(
                returned=len(data), matched=matched, truncated=truncated, scope="operator_notices"
            ),
        )

    @staticmethod
    def _normalise(operator: str, item: dict[str, Any], reference: date) -> dict[str, Any]:
        row: dict[str, Any] = {"operator": operator}
        if operator == "eshot":
            starts = _parse_date(item.get("starts_at"))
            ends = _parse_date(item.get("ends_at"))
            row.update(
                {
                    "line": item.get("line"),
                    "title": item.get("title"),
                    "summary": None,
                    "starts_at": item.get("starts_at"),
                    "ends_at": item.get("ends_at"),
                    "published_at": item.get("starts_at"),
                    "active": bool(
                        (starts is None or starts <= reference)
                        and (ends is None or ends >= reference)
                    ),
                    "url": None,
                }
            )
            return row
        row.update(
            {
                "line": None,
                "title": item.get("title"),
                "summary": item.get("summary"),
                "starts_at": None,
                "ends_at": None,
                "published_at": item.get("published_at"),
                # These operators publish no validity window, so "active" is unknown.
                "active": None,
                "url": item.get("url"),
            }
        )
        return row
