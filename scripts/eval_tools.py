"""Inspect the tool definition footprint and optionally score external predictions.

No model is called. Predictions are JSON objects keyed by scenario id, with
{"tool": "...", "arguments": {...}} values. This reports exact matches only;
the pytest suite separately exercises dispatch and envelope preservation.

    python -m scripts.eval_tools [--predictions predictions.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

CASES_PATH = Path(__file__).resolve().parents[1] / "tests/fixtures/evals/city_questions.json"


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


def score_predictions(cases: list[dict], predictions: dict) -> dict:
    correct = sum(
        predictions.get(case["id"]) == {"tool": case["tool"], "arguments": case["arguments"]} for case in cases
    )
    tool_only = sum(
        isinstance(predictions.get(case["id"]), dict) and predictions[case["id"]].get("tool") == case["tool"]
        for case in cases
    )
    return {"exact_matches": correct, "tool_matches": tool_only, "total": len(cases)}


async def footprint(server=None) -> dict:
    if server is None:
        from app.core.settings import get_settings
        from app.mcp.registry import create_mcp_server

        server = create_mcp_server(get_settings())
    tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in await server.list_tools()]
    without_output = [{key: value for key, value in tool.items() if key != "outputSchema"} for tool in tools]

    def size(value) -> int:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

    total = size(tools)
    input_only = size(without_output)
    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    prompts = await server.list_prompts()
    return {
        "tool_count": len(tools),
        "definition_utf8_bytes": total,
        "definition_without_output_schema_utf8_bytes": input_only,
        "output_schema_overhead_utf8_bytes": total - input_only,
        "structured_tool_count": sum("outputSchema" in tool for tool in tools),
        "tool_names": [tool["name"] for tool in tools],
        "resource_count": len(resources),
        "resource_template_count": len(templates),
        "prompt_count": len(prompts),
        "instructions_utf8_bytes": len((server.instructions or "").encode()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path)
    args = parser.parse_args()
    report = asyncio.run(footprint())
    report["measurement"] = "serialized tools/list definitions; bytes are not tokens"
    if args.predictions:
        report["external_predictions"] = score_predictions(
            load_cases(), json.loads(args.predictions.read_text(encoding="utf-8"))
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
