"""Titles, annotations and descriptions on every advertised tool."""

from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.mcp.instructions import SERVER_INSTRUCTIONS
from app.mcp.registry import DEFAULT_TOOL_NAMES, TOOL_TITLES, create_mcp_server


def test_every_default_tool_has_a_title_and_titles_have_no_orphans():
    assert set(TOOL_TITLES) == set(DEFAULT_TOOL_NAMES)
    assert len(set(DEFAULT_TOOL_NAMES)) == len(DEFAULT_TOOL_NAMES)


@pytest.mark.asyncio
async def test_every_tool_is_titled_read_only_and_described():
    tools = await create_mcp_server(get_settings()).list_tools()
    assert [tool.name for tool in tools] == list(DEFAULT_TOOL_NAMES)
    for tool in tools:
        assert tool.name.startswith("izmir_") and len(tool.name) <= 64
        assert tool.title == TOOL_TITLES[tool.name]
        assert tool.description and len(tool.description) >= 20
        annotations = tool.annotations
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is False
        assert annotations.idempotent_hint is True
        assert tool.input_schema.get("type") == "object"


@pytest.mark.asyncio
async def test_input_schemas_do_not_allow_arbitrary_extra_types():
    """Every property declares a type, enum or anyOf; nothing is schema-less."""
    for tool in await create_mcp_server(get_settings()).list_tools():
        for name, prop in tool.input_schema.get("properties", {}).items():
            assert any(key in prop for key in ("type", "anyOf", "enum", "$ref")), (tool.name, name)


def test_server_instructions_are_present_and_bounded():
    assert SERVER_INSTRUCTIONS.strip()
    assert len(SERVER_INSTRUCTIONS.encode()) < 16_384
