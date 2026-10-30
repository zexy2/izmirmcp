"""Published output schemas and structuredContent must match the JSON envelope."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jsonschema import Draft202012Validator
import pytest

import app.mcp.server as handlers
from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.settings import get_settings
from app.mcp.registry import create_mcp_server
from scripts.eval_tools import load_cases

CASES = {case["tool"]: case for case in load_cases()}


@pytest.mark.asyncio
async def test_every_tool_publishes_a_valid_output_schema():
    for tool in await create_mcp_server(get_settings()).list_tools():
        assert tool.output_schema is not None, tool.name
        Draft202012Validator.check_schema(tool.output_schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("ok", [True, False])
@pytest.mark.parametrize("tool_name", sorted(CASES))
async def test_structured_content_validates_and_equals_text(tool_name, ok, monkeypatch):
    case = CASES[tool_name]
    if ok:
        payload = success_envelope(
            summary="fixture", data=[case["record"]],
            sources=[Source(name="Fixture", publisher="Fixture", url=None)],
            freshness=Freshness(status="fresh"),
        )
    else:
        payload = error_envelope(summary="fixture", warning="kaynak yok", code="source_unavailable")
    service = SimpleNamespace(**{case["method"]: AsyncMock(return_value=payload)})
    monkeypatch.setattr(handlers, case["service"], lambda *_a, **_kw: service)

    server = create_mcp_server(get_settings())
    schema = next(t for t in await server.list_tools() if t.name == tool_name).output_schema
    result = await server.call_tool(tool_name, case["arguments"])
    text = json.loads(result.content[0].text)
    assert text["ok"] is ok
    structured = result.structured_content
    assert structured is not None
    assert structured == text
    Draft202012Validator(schema).validate(structured)
