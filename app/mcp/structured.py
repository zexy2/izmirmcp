"""Validate MCP output without changing the bare-dict Python handler contract."""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, get_type_hints

from app.core.envelope import ResponseEnvelope

P = ParamSpec("P")


def with_envelope_output(
    handler: Callable[P, Awaitable[dict[str, Any]]],
) -> Callable[P, Awaitable[ResponseEnvelope]]:
    @wraps(handler)
    async def structured(*args: P.args, **kwargs: P.kwargs) -> ResponseEnvelope:
        return ResponseEnvelope.model_validate(await handler(*args, **kwargs))

    signature = inspect.signature(handler, eval_str=True)
    structured.__annotations__ = {
        **get_type_hints(handler, include_extras=True), "return": ResponseEnvelope,
    }
    structured.__signature__ = signature.replace(return_annotation=ResponseEnvelope)
    return structured
