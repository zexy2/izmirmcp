"""Deterministic MCP dispatch/envelope contracts, not LLM accuracy evaluations.

Each İzmir city question pins (tool, arguments) -> (service, method, args) and
checks that the envelope the service returns reaches the client unchanged, for
fresh, stale and broken source states.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.mcp.server as handlers
from app.core.envelope import Freshness, ResponseEnvelope, Source, success_envelope
from app.core.settings import get_settings
from app.mcp.registry import DEFAULT_TOOL_NAMES, create_mcp_server
from scripts.eval_tools import footprint, load_cases, score_predictions

CASES = load_cases()


def _normal(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _payload(case: dict, state: str) -> dict:
    payload = success_envelope(
        summary=case["question"],
        data=[case["record"]] if state != "broken" else [],
        sources=[Source(name="Fixture official source", publisher="Fixture", url=None)],
        freshness=Freshness(status=state if state != "broken" else "unknown"),
        limits=["fixture scope; not live data"],
        warnings=["Belirsizliği koruyun; canlı durum çıkarımı yapmayın."],
    )
    payload["ok"] = state != "broken"
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["fresh", "stale", "broken"])
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_question_keeps_dispatch_and_envelope(case, state, monkeypatch):
    payload = _payload(case, state)
    method = AsyncMock(return_value=payload)
    service = SimpleNamespace(**{case["method"]: method})
    monkeypatch.setattr(handlers, case["service"], lambda *_a, **_kw: service)

    server = create_mcp_server(get_settings())
    result = await server.call_tool(case["tool"], case["arguments"])
    text = json.loads(result.content[0].text)
    ResponseEnvelope.model_validate(text)
    assert text == _normal(payload)
    if result.structured_content is not None:
        assert result.structured_content == _normal(payload)
    method.assert_awaited_once()
    args, kwargs = method.await_args
    assert _normal(list(args)) == case["service_args"]
    assert _normal(kwargs) == case["service_kwargs"]


def test_eval_has_twenty_unique_questions_over_known_tools():
    assert len(CASES) == 20
    assert len({case["id"] for case in CASES}) == 20
    assert all(case["question"] and case["record"] for case in CASES)
    assert {case["tool"] for case in CASES} <= set(DEFAULT_TOOL_NAMES)
    # Broad coverage: most of the advertised surface has a scenario.
    assert len({case["tool"] for case in CASES}) >= 18


def test_score_predictions_counts_exact_and_tool_matches():
    perfect = {case["id"]: {"tool": case["tool"], "arguments": case["arguments"]} for case in CASES}
    assert score_predictions(CASES, perfect) == {"exact_matches": 20, "tool_matches": 20, "total": 20}
    wrong_args = {cid: {"tool": value["tool"], "arguments": {}} for cid, value in perfect.items()}
    assert score_predictions(CASES, wrong_args)["exact_matches"] == 0
    assert score_predictions(CASES, wrong_args)["tool_matches"] == 20
    assert score_predictions(CASES, {})["tool_matches"] == 0


@pytest.mark.asyncio
async def test_footprint_separates_output_schema_cost_and_discovery_primitives():
    result = await footprint(create_mcp_server(get_settings()))
    assert result["tool_count"] == len(result["tool_names"]) == len(DEFAULT_TOOL_NAMES)
    assert result["structured_tool_count"] == result["tool_count"]
    assert result["resource_count"] + result["resource_template_count"] > 0
    assert result["prompt_count"] > 0
    assert result["instructions_utf8_bytes"] > 0
    assert result["output_schema_overhead_utf8_bytes"] > 0
    assert result["definition_utf8_bytes"] == (
        result["definition_without_output_schema_utf8_bytes"] + result["output_schema_overhead_utf8_bytes"]
    )
