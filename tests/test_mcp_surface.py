from __future__ import annotations

import json

import pytest

from app.core.settings import get_settings
from app.mcp.registry import DEFAULT_TOOL_NAMES, create_mcp_server


@pytest.mark.asyncio
async def test_all_tools_are_advertised_with_titles_and_structured_output():
    server = create_mcp_server(get_settings())
    tools = await server.list_tools()
    assert [tool.name for tool in tools] == list(DEFAULT_TOOL_NAMES)
    assert len(tools) == 17
    for tool in tools:
        assert tool.title
        assert tool.output_schema is not None
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


@pytest.mark.asyncio
async def test_departures_schema_exposes_stop_time_and_line():
    server = create_mcp_server(get_settings())
    departures = next(
        tool for tool in await server.list_tools() if tool.name == "izmir_bus_departures"
    )
    assert {"stop_id", "at", "line", "limit"} == set(departures.input_schema["properties"])
    assert departures.input_schema["required"] == ["stop_id"]


@pytest.mark.asyncio
async def test_nearby_schema_exposes_place_and_types():
    server = create_mcp_server(get_settings())
    nearby = next(tool for tool in await server.list_tools() if tool.name == "izmir_nearby")
    properties = nearby.input_schema["properties"]
    assert {"lat", "lon", "place", "bbox", "district", "types", "radius_m",
            "limit"} == set(properties)
    assert nearby.input_schema.get("required", []) == []


@pytest.mark.asyncio
async def test_health_call_returns_envelope():
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_health", {})
    text = result.content[0].text
    payload = json.loads(text)
    assert payload["ok"] is True
    assert payload["data"][0]["service"] == "izmir-mcp"


@pytest.mark.asyncio
async def test_empty_nearby_types_is_rejected():
    server = create_mcp_server(get_settings())
    result = await server.call_tool(
        "izmir_nearby", {"lat": 38.41872, "lon": 27.12827, "types": []}
    )
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["field"] == "types"


@pytest.mark.asyncio
async def test_invalid_nearby_input_is_reported_not_raised():
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_nearby", {"place": "Atlantis"})
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["field"] == "place"


@pytest.mark.asyncio
async def test_nearby_modes_are_mutually_exclusive_and_bbox_is_validated():
    server = create_mcp_server(get_settings())

    both = json.loads((await server.call_tool(
        "izmir_nearby", {"bbox": [27.12, 38.41, 27.14, 38.43], "district": "Konak"}
    )).content[0].text)
    assert both["ok"] is False
    assert both["error"]["code"] == "validation_error"

    radius = json.loads((await server.call_tool(
        "izmir_nearby", {"bbox": [27.12, 38.41, 27.14, 38.43], "radius_m": 500}
    )).content[0].text)
    assert radius["ok"] is False
    assert radius["error"]["field"] == "radius_m"

    crossed = json.loads((await server.call_tool(
        "izmir_nearby", {"bbox": [27.14, 38.43, 27.12, 38.41]}
    )).content[0].text)
    assert crossed["ok"] is False
    assert crossed["error"]["field"] == "bbox"


@pytest.mark.asyncio
async def test_nearby_district_without_a_district_capable_type_is_reported():
    server = create_mcp_server(get_settings())
    result = await server.call_tool(
        "izmir_nearby", {"district": "Karşıyaka", "types": ["parking"]}
    )
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["field"] == "types"


@pytest.mark.asyncio
async def test_bus_tools_are_advertised_with_expected_inputs():
    server = create_mcp_server(get_settings())
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert {"izmir_bus_stops", "izmir_bus_arrivals", "izmir_bus_routes"} <= set(tools)
    assert {"query", "lat", "lon", "radius_m", "limit"} == set(
        tools["izmir_bus_stops"].input_schema["properties"]
    )
    assert "stop_id" in tools["izmir_bus_arrivals"].input_schema["properties"]
    assert tools["izmir_bus_arrivals"].input_schema["required"] == ["stop_id"]
    assert {"query", "detail", "direction", "limit"} == set(
        tools["izmir_bus_routes"].input_schema["properties"]
    )


@pytest.mark.asyncio
async def test_nearby_accepts_bus_stop_type():
    server = create_mcp_server(get_settings())
    nearby = next(tool for tool in await server.list_tools() if tool.name == "izmir_nearby")
    types = nearby.input_schema["properties"]["types"]
    rendered = json.dumps(types, ensure_ascii=False)
    assert "bus_stop" in rendered


@pytest.mark.asyncio
async def test_bus_stops_validation_error_is_reported_not_raised():
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_bus_stops", {})
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["field"] == "query"


@pytest.mark.asyncio
async def test_new_city_tools_are_advertised_with_expected_inputs():
    server = create_mcp_server(get_settings())
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert {"izmir_market_schedule", "izmir_transport_disruptions",
            "izmir_city_services_nearby"} <= set(tools)
    market = tools["izmir_market_schedule"].input_schema["properties"]
    assert {"day", "district", "lat", "lon", "radius_m", "limit"} == set(market)
    disruptions = tools["izmir_transport_disruptions"].input_schema["properties"]
    assert {"operator", "line", "active_only", "limit"} == set(disruptions)
    allowed = json.dumps(disruptions["operator"], ensure_ascii=False)
    assert {"eshot", "metro", "izdeniz", "izban"} <= {name for name in ("eshot","metro","izdeniz","izban") if name in allowed}
    services = tools["izmir_city_services_nearby"].input_schema["properties"]
    assert {"kinds", "lat", "lon", "place", "bbox", "district", "radius_m", "limit"} == set(
        services
    )


@pytest.mark.asyncio
async def test_city_services_validation_error_is_reported_not_raised():
    server = create_mcp_server(get_settings())
    result = await server.call_tool(
        "izmir_city_services_nearby", {"lat": 38.4, "lon": 27.1, "kinds": []}
    )
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["field"] == "kinds"


@pytest.mark.asyncio
async def test_city_services_location_modes_are_mutually_exclusive():
    server = create_mcp_server(get_settings())
    result = await server.call_tool(
        "izmir_city_services_nearby",
        {"lat": 38.4, "lon": 27.1, "district": "Konak"},
    )
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_city_services_bbox_rejects_radius():
    server = create_mcp_server(get_settings())
    result = await server.call_tool(
        "izmir_city_services_nearby",
        {"bbox": [27.1, 38.4, 27.2, 38.5], "radius_m": 500},
    )
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["field"] == "radius_m"
