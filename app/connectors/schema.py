"""Shape checks shared by connectors.

A source that changes its payload shape is not "no data": callers need a typed
``schema_drift`` failure instead of an empty list or an ``AttributeError``.
"""
from __future__ import annotations

from typing import Any

from app.connectors.http import SourceError


class SchemaDriftError(SourceError):
    """The upstream payload no longer matches the shape this connector expects."""

    code = "schema_drift"


def expect_type(payload: Any, kind: type | tuple[type, ...], *, what: str) -> Any:
    if not isinstance(payload, kind):
        raise SchemaDriftError(f"{what}: unexpected {type(payload).__name__} payload")
    return payload


def decode_member(body: bytes, *, name: str) -> str:
    """Strictly decode a ZIP member; malformed UTF-8 is a source error."""
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError(f"{name} is not valid UTF-8") from exc
