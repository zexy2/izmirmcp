"""Build the advertised MCP surface."""
from __future__ import annotations

from importlib import metadata

from mcp.server import MCPServer
from mcp.types import Tool as MCPTool, ToolAnnotations

from app.core.settings import Settings
from app.mcp.instructions import SERVER_INSTRUCTIONS
from app.mcp.prompts import register_prompts
from app.mcp.resources import register_resources
from app.mcp.structured import with_envelope_output

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True,
)

DEFAULT_TOOL_NAMES = (
    "izmir_health",
    "izmir_search_datasets",
    "izmir_get_dataset",
    "izmir_get_resource_schema",
    "izmir_query_resource",
    "izmir_datastore_query",
    "izmir_nearby",
    "izmir_mobility_nearby",
    "izmir_water_status",
    "izmir_air_quality",
    "izmir_transit_stations",
    "izmir_transit_schedule",
    "izmir_bus_stops",
    "izmir_bus_arrivals",
    "izmir_bus_departures",
    "izmir_bus_routes",
    "izmir_market_schedule",
    "izmir_transport_disruptions",
    "izmir_city_services_nearby",
    "izmir_gtfs_status",
    "izmir_neighborhood_profile",
    "izmir_traffic_history",
    "izmir_tram_lines",
    "izmir_tram_schedule",
    "izmir_bus_line_arrivals",
    "izmir_bus_live_positions",
    "izmir_dam_status",
    "izmir_pharmacies_all",
    "izmir_cbs_layer",
    "izmir_events",
    "izmir_market_prices",
)

TOOL_TITLES = {
    "izmir_health": "İzmir MCP servis durumu",
    "izmir_search_datasets": "İzmir açık veri seti arama",
    "izmir_get_dataset": "İzmir veri seti bilgileri",
    "izmir_get_resource_schema": "İzmir kaynak kolonları",
    "izmir_query_resource": "İzmir kaynak kayıtları",
    "izmir_datastore_query": "İzmir kaynak üzerinde sınırlı SQL",
    "izmir_nearby": "Yakındaki İzmir hizmetleri",
    "izmir_mobility_nearby": "Yakındaki ulaşım seçenekleri",
    "izmir_water_status": "İZSU baraj durumu",
    "izmir_air_quality": "İzmir hava kalitesi",
    "izmir_transit_stations": "İzmir ulaşım istasyonları",
    "izmir_transit_schedule": "İzmir yayımlanmış sefer tarifesi",
    "izmir_bus_stops": "EShot otobüs durakları",
    "izmir_bus_arrivals": "EShot durağa yaklaşan otobüsler",
    "izmir_bus_departures": "EShot planlı kalkışlar (durak veya çevre)",
    "izmir_bus_routes": "EShot GTFS hat listesi ve durak detayı",
    "izmir_market_schedule": "İzmir semt pazarı takvimi",
    "izmir_transport_disruptions": "EShot hat duyuruları ve güzergâh değişiklikleri",
    "izmir_city_services_nearby": "Yakındaki WiFi, İzmirim Kart ve kütüphaneler",
    "izmir_gtfs_status": "Yerel GTFS tarife deposu durumu",
    "izmir_neighborhood_profile": "İzmir mahalle profili (nüfus ve bina)",
    "izmir_traffic_history": "İzmir ana arter trafik geçmişi",
    "izmir_tram_lines": "İzmir tramvay hatları",
    "izmir_tram_schedule": "İzmir tramvay istasyon ve sefer sıklığı",
    "izmir_bus_line_arrivals": "EShot hattın durağa yaklaşan otobüsleri",
    "izmir_bus_live_positions": "EShot hat otobüslerinin canlı konumu",
    "izmir_dam_status": "İZSU tarihli baraj durumu",
    "izmir_pharmacies_all": "İzmir tüm eczaneler",
    "izmir_cbs_layer": "İzmir CBS katmanı",
    "izmir_events": "İzmir kültür sanat etkinlikleri",
    "izmir_market_prices": "İzmir hal fiyatları",
}


def package_version() -> str:
    try:
        return metadata.version("izmir-mcp")
    except metadata.PackageNotFoundError:
        return "0.0.0-local"


class IzmirMCPServer(MCPServer):
    async def list_tools(self) -> list[MCPTool]:
        return await super().list_tools()


def create_mcp_server(settings: Settings) -> MCPServer:
    from app.mcp import server as handlers

    server = IzmirMCPServer(
        "izmir-mcp",
        title="İzmir MCP",
        version=package_version(),
        instructions=SERVER_INSTRUCTIONS,
    )
    for name in DEFAULT_TOOL_NAMES:
        handler = getattr(handlers, name)
        server.add_tool(
            with_envelope_output(handler),
            title=TOOL_TITLES[name],
            annotations=READ_ONLY,
            structured_output=True,
        )
    register_resources(server, settings)
    register_prompts(server)
    return server
