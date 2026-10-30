"""Live smoke checks against real İzmir sources through the in-process MCP server.

Each tool must return a success envelope with non-empty data and its key fields.
An error envelope (even a typed one) fails the check.
"""
from __future__ import annotations

import json

import pytest

from app.core.settings import get_settings
from app.mcp.registry import create_mcp_server
from tests.live._assertions import assert_ok

LIVE_CALLS = [
    ("izmir_health", {}, ("service", "upstream_health")),
    ("izmir_search_datasets", {"query": "otopark", "limit": 2}, ("id", "title")),
    ("izmir_water_status", {"kind": "dams", "limit": 3}, ("name", "occupancy_percent")),
    ("izmir_transit_stations", {"mode": "metro", "limit": 5}, ("id", "name")),
    ("izmir_bus_routes", {"query": "Konak", "limit": 3}, ("route_id", "short_name")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments,keys", LIVE_CALLS, ids=[call[0] for call in LIVE_CALLS])
async def test_live_tool_returns_data(tool, arguments, keys):
    result = await create_mcp_server(get_settings()).call_tool(tool, arguments)
    assert_ok(json.loads(result.content[0].text), keys=keys)
