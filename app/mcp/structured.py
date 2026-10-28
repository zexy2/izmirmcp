"""Validate MCP output without changing the bare-dict Python handler contract."""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, get_type_hints

from app.core.envelope import ResponseEnvelope
from app.core.tool_telemetry import tool_telemetry

P = ParamSpec("P")


def _classify(envelope: ResponseEnvelope) -> tuple[str | None, bool, bool]:
    """Derive telemetry outcome from a validated envelope.

    Only booleans, codes and counts are read; never the data, summary or any
    source text.
    """
    error_code = envelope.error.code if envelope.error else None
    truncated = bool(envelope.result_info and envelope.result_info.truncated)
    stale = envelope.freshness.status in {"stale", "broken"}
    return error_code, truncated, stale


def with_envelope_output(
    handler: Callable[P, Awaitable[dict[str, Any]]],
) -> Callable[P, Awaitable[ResponseEnvelope]]:
    @wraps(handler)
    async def structured(*args: P.args, **kwargs: P.kwargs) -> ResponseEnvelope:
        with tool_telemetry().timer(handler.__name__) as outcome:
            try:
                envelope = ResponseEnvelope.model_validate(await handler(*args, **kwargs))
            except Exception:
                outcome["error_code"] = "unexpected_error"
                raise
            error_code, truncated, stale = _classify(envelope)
            outcome["error_code"] = error_code
            outcome["truncated"] = truncated
            outcome["stale"] = stale
            return envelope

    signature = inspect.signature(handler, eval_str=True)
    structured.__annotations__ = {
        **get_type_hints(handler, include_extras=True), "return": ResponseEnvelope,
    }
    structured.__signature__ = signature.replace(return_annotation=ResponseEnvelope)
    return structured
