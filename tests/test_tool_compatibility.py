"""Backward-compatibility guard for the public MCP tool surface.

Existing tool names and input schemas must not change; new tools may be added.
Regenerate the snapshot only for an intentional, documented breaking change.
"""

import json
from pathlib import Path

import pytest

from app.core.settings import get_settings
from app.mcp.registry import create_mcp_server

SNAPSHOT = Path(__file__).parent / "fixtures" / "tool_compatibility_snapshot.json"


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


async def _current() -> dict:
    tools = await create_mcp_server(get_settings()).list_tools()
    return {tool.name: tool.input_schema for tool in tools}


@pytest.mark.asyncio
async def test_no_public_tool_removed(snapshot):
    current = await _current()
    missing = sorted(set(snapshot) - set(current))
    assert not missing, f"public tools removed: {missing}"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(json.loads(SNAPSHOT.read_text(encoding="utf-8"))))
async def test_input_schema_unchanged(name, snapshot):
    current = await _current()
    assert name in current
    assert json.loads(json.dumps(current[name])) == snapshot[name]
