from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_serializer

FreshnessStatus = Literal["fresh", "stale", "unknown", "broken"]

MACHINE_HOST_MARKERS = ("api", "proxy")
MACHINE_PATH_SEGMENTS = frozenset({"api", "download", "docs"})
MACHINE_FILE_SUFFIXES = (
    ".asmx", ".csv", ".geojson", ".json", ".xls", ".xlsx", ".xml", ".zip",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_page_url(url: str | None) -> str | None:
    """Return a citable human page URL, never an API or file endpoint."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    segments = [segment.lower() for segment in parts.path.split("/") if segment]
    if parts.scheme != "https" or not host:
        return None
    if any(marker in label for label in host.split(".") for marker in MACHINE_HOST_MARKERS):
        return None
    if MACHINE_PATH_SEGMENTS.intersection(segments):
        return None
    if segments and segments[-1].endswith(MACHINE_FILE_SUFFIXES):
        return None
    return url


class Freshness(BaseModel):
    status: FreshnessStatus
    retrieved_at: str = Field(default_factory=utc_now_iso)
    source_updated_at: str | None = None
    ttl_seconds: int | None = None


class Source(BaseModel):
    name: str
    publisher: str = "İzmir Büyükşehir Belediyesi"
    url: str | None = Field(
        default=None,
        description=(
            "Human-readable source page for citations; null when the source is "
            "only an API endpoint or data file."
        ),
    )
    license: str | None = None
    dataset_id: str | None = None
    resource_id: str | None = None
    scope: str | None = None
    source_updated_at: str | None = None

    @field_serializer("url")
    def _serialize_url(self, url: str | None) -> str | None:
        return public_page_url(url)


class Repair(BaseModel):
    """Structured guidance for fixing a rejected call.

    ``next_step`` is for humans; ``tool``/``arguments`` let an agent retry
    mechanically instead of guessing. Only ever built from our own knowledge of
    the schema — never echoed from source text.
    """

    next_step: str
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    constraint: str | None = None


class ErrorInfo(BaseModel):
    code: str
    temporary: bool = False
    retry_after_ms: int | None = Field(default=None, ge=0)
    field: str | None = None
    next_step: str | None = None
    repair: Repair | None = None


class ResultInfo(BaseModel):
    returned: int = Field(ge=0)
    matched: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    scope: str = "data"
    next_step: str | None = None


def result_info(
    *, returned: int, matched: int | None = None,
    truncated: bool | None = None, scope: str = "data",
) -> ResultInfo:
    if truncated is None and matched is not None:
        truncated = matched > returned
    note = None
    if truncated:
        note = (
            "Limiti duyurulan üst sınıra kadar artırın ya da filtreleri daraltın. "
            "Bu, toplamın tamamı değildir."
        )
    elif truncated is None:
        note = "Tamlık bilinmiyor; kaynak kapsamını, limitleri ve uyarıları inceleyin."
    return ResultInfo(returned=returned, matched=matched, truncated=truncated, scope=scope, next_step=note)


class ResponseEnvelope(BaseModel):
    ok: bool = True
    summary: str
    data: list[dict[str, Any]] = Field(default_factory=list)
    freshness: Freshness
    sources: list[Source] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_queries: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    result_info: ResultInfo | None = None


def success_envelope(
    *,
    summary: str,
    data: list[dict[str, Any]] | None = None,
    sources: list[Source] | None = None,
    freshness: Freshness | None = None,
    limits: list[str] | None = None,
    warnings: list[str] | None = None,
    next_queries: list[str] | None = None,
    matched: int | None = None,
    result: ResultInfo | None = None,
) -> dict[str, Any]:
    if result is None:
        result = result_info(returned=len(data or []), matched=matched)
    envelope = ResponseEnvelope(
        summary=summary,
        data=data or [],
        sources=sources or [],
        freshness=freshness or Freshness(status="unknown"),
        limits=limits or [],
        warnings=warnings or [],
        next_queries=next_queries or [],
        result_info=result,
    )
    return envelope.model_dump(mode="json")


def error_envelope(
    *,
    summary: str,
    warning: str,
    sources: list[Source] | None = None,
    freshness_status: FreshnessStatus = "broken",
    data: list[dict[str, Any]] | None = None,
    limits: list[str] | None = None,
    code: str | None = None,
    temporary: bool | None = None,
    field: str | None = None,
    next_step: str | None = None,
    repair: Repair | dict[str, Any] | None = None,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    code = code or "request_failed"
    if temporary is None:
        temporary = code in {
            "source_unavailable", "source_rate_limited", "source_timeout",
        }
    if next_step is None:
        next_step = (
            "Daha sonra yeniden deneyin; kaynağın erişilebilirliği garanti değildir."
            if temporary
            else "Yeniden denemeden önce girdileri ve duyurulan araç limitlerini gözden geçirin."
        )
    envelope = ResponseEnvelope(
        ok=False,
        summary=summary,
        data=data or [],
        freshness=Freshness(status=freshness_status),
        sources=sources or [],
        limits=limits or [],
        warnings=[warning],
        error=ErrorInfo(
            code=code,
            temporary=temporary,
            field=field,
            next_step=next_step,
            repair=repair,
            retry_after_ms=retry_after_ms,
        ),
        result_info=result_info(returned=len(data or []), scope="error_details"),
    )
    return envelope.model_dump(mode="json")


def finite_number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# Source text is untrusted. İzmir's published names are well under 200 chars;
# a hostile or corrupted source sending a 1 MB field would inflate every
# envelope (one record made a 1.9 MB response, times the limit).
MAX_FIELD_CHARS = 512
MAX_ID_CHARS = 128


def bounded_text(value: Any, limit: int = MAX_FIELD_CHARS) -> str | None:
    """Trim a source-provided string to a sane length, collapsing whitespace.

    Not a sanitiser: the result is still data, never markup or instructions.
    """
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit]


def bounded_id(value: Any, limit: int = MAX_ID_CHARS) -> Any:
    """Identifiers are short by construction; anything longer is malformed.

    The original type is preserved (an integer stays an integer) so callers that
    match ids against a source list keep working; only absurd lengths are cut.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return text[:limit] or None
