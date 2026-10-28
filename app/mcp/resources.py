"""Local, credential-free discovery resources; reading never probes an upstream."""
from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer

from app.core.envelope import Freshness, ResponseEnvelope, Source, success_envelope
from app.core.settings import Settings

SOURCE_CATALOG = (
    ("runtime", "İzmir MCP runtime", "İzmir MCP", None, "local_metadata"),
    ("ckan", "İzmir Açık Veri Portalı", "İzmir Büyükşehir Belediyesi",
     "https://acikveri.bizizmir.com", "catalog_and_datastore_records"),
    ("openapi", "İzmir Büyükşehir Belediyesi açık API", "İzmir Büyükşehir Belediyesi",
     None, "parking_pharmacy_air_and_transit"),
    ("izsu", "İZSU baraj doluluk oranları", "İZSU", "https://www.izsu.gov.tr", "published_dam_levels"),
    ("metro", "İzmir Metro", "İzmir Metro A.Ş.", "https://www.izmirmetro.com.tr",
     "stations_and_frequency"),
    ("izban", "İZBAN", "İZBAN A.Ş.", "https://www.izban.com.tr", "stations_and_timetable"),
    ("izdeniz", "İZDENİZ", "İZDENİZ A.Ş.", "https://www.izdeniz.com.tr", "piers_and_timetable"),
    ("eshot_stops", "EShot otobüs durakları", "İzmir Büyükşehir Belediyesi / EShot",
     "https://acikveri.bizizmir.com/dataset/eshot-otobus-duraklari", "stops"),
    ("eshot_arrivals", "EShot durağa yaklaşan otobüsler", "İZTEK",
     "https://acikveri.bizizmir.com/dataset/duraga-yaklasan-otobusler",
     "live_vehicle_positions_without_eta"),
    ("eshot_gtfs", "EShot GTFS verisi", "İzmir Büyükşehir Belediyesi / EShot",
     "https://acikveri.bizizmir.com/dataset/toplu-ulasim-gtfs-verileri",
     "published_route_and_stop_timetable"),
    ("market", "İzmir semt pazar yerleri", "İzmir Büyükşehir Belediyesi",
     "https://acikveri.bizizmir.com/dataset/semt-pazar-yerleri", "static_market_locations"),
    ("wifi", "WizmirNET kablosuz internet noktaları", "İzmir Büyükşehir Belediyesi",
     "https://acikveri.bizizmir.com/dataset/kablosuz-internet-baglanti-noktalari",
     "static_service_locations"),
    ("izmirim_card", "İzmirim Kart dolum noktaları", "İzmir Büyükşehir Belediyesi",
     "https://acikveri.bizizmir.com/dataset/izmirim-kart-dolum-noktalari",
     "static_service_locations"),
    ("library", "İBB kütüphaneleri", "İzmir Büyükşehir Belediyesi",
     "https://acikveri.bizizmir.com/dataset/izmir-buyuksehir-belediyesi-kutuphaneleri-bilgileri",
     "static_service_locations_without_coordinates"),
    ("neighborhood_population", "İzmir mahalle nüfusu", "İzmir Büyükşehir Belediyesi",
     "https://acikveri.bizizmir.com/dataset/cinsiyete-gore-mahalle-nufus-bilgileri",
     "published_neighborhood_demographics"),
    ("neighborhood_buildings", "İzmir mahalle bina sayıları",
     "İzmir Büyükşehir Belediyesi",
     "https://acikveri.bizizmir.com/dataset/ilcelere-ait-mahalle-bazli-bina-sayilari",
     "published_building_stock"),
    ("eshot_notices", "EShot hat duyuruları", "İzmir Büyükşehir Belediyesi / EShot",
     "https://acikveri.bizizmir.com/dataset/otobus-hattina-ait-duyurular",
     "published_line_notices"),
    ("osm", "OpenStreetMap Nominatim", "OpenStreetMap contributors",
     "https://www.openstreetmap.org/copyright", "reference_points"),
)


def _document(summary: str, data: list[dict[str, Any]], *, limits: list[str] | None = None) -> str:
    payload = success_envelope(
        summary=summary,
        data=data,
        sources=[Source(name="İzmir MCP capability definitions", publisher="İzmir MCP", url=None)],
        freshness=Freshness(status="fresh", ttl_seconds=60),
        limits=["Local metadata only; no upstream health checks or live readings.", *(limits or [])],
        warnings=["Metadata freshness does not establish source availability; inspect tool-result freshness and warnings."],
    )
    return json.dumps(payload, ensure_ascii=False)


def _coverage(settings: Settings, actual_tools: set[str]) -> list[dict[str, Any]]:
    entries = [
        ("runtime", ["izmir_health"], ["runtime"], "local_readiness",
         "Local readiness only; does not check upstream data sources."),
        ("catalog", ["izmir_search_datasets", "izmir_get_dataset", "izmir_get_resource_schema",
                     "izmir_query_resource"], ["ckan"], "catalog_and_records",
         "Inspect the resource schema first; datastore_active is not proof of a working query."),
        ("nearby", ["izmir_nearby"], ["openapi", "osm"], "mixed_snapshots_and_static_locations",
         "Radius, bbox or district-wide. Bbox has no reference point, so distance_m is null "
         "and edges are inclusive. District mode covers pharmacy through its published region "
         "text only; parking and transit publish no district. Parking is a snapshot, pharmacy "
         "rosters are daily, stations are static."),
        ("water", ["izmir_water_status"], ["izsu"], "published_dam_levels",
         "Dam CSV only. İZSU fault API returned HTTP 500 during verification; kind=faults "
         "reports source_unavailable instead of inventing outages."),
        ("air_quality", ["izmir_air_quality"], ["openapi"], "station_readings",
         "No coordinates or units; observations may be dated a day earlier than requested."),
        ("bus", ["izmir_bus_stops", "izmir_bus_arrivals", "izmir_bus_departures",
                 "izmir_bus_routes", "izmir_gtfs_status"],
         ["eshot_stops", "eshot_arrivals", "eshot_gtfs"],
         "stops_live_vehicle_positions_and_published_timetable",
         "Approaching-bus data has no ETA in minutes and an empty payload is not proof "
         "of no service. Route detail returns published stop patterns per direction; "
         "variants stay separate and headsigns are never invented. Scheduled departures "
         "are published timetable rows, not live departures; GTFS calendar ends "
         "2026-10-09, so later dates return a staleness warning and no rows."),
        ("markets", ["izmir_market_schedule"], ["market"], "static_market_locations",
         "Weekday is parsed from free-text notes; unknown days are tagged, never guessed."),
        ("transport_notices", ["izmir_transport_disruptions"], ["eshot_notices"],
         "published_line_notices",
         "Announcements such as route changes, not live delays or vehicle status."),
        ("city_services", ["izmir_city_services_nearby"], ["wifi", "izmirim_card", "library"],
         "static_service_locations",
         "Static snapshots. The library layer has no coordinates, so it cannot be "
         "radius-filtered."),
        ("neighborhood", ["izmir_neighborhood_profile"],
         ["neighborhood_population", "neighborhood_buildings"],
         "published_neighborhood_statistics",
         "Two separately published layers with different years; a missing layer "
         "is null, never zero."),
        ("transit", ["izmir_transit_stations", "izmir_transit_schedule"], ["metro", "izban", "izdeniz"],
         "published_timetable",
         "Published timetables, not live departures or ETAs. Metro is a frequency table. "
         "İZDENİZ day is the source's own id."),
    ]
    data = []
    for capability, names, source_ids, kind, warning in entries:
        enabled = any(name in actual_tools for name in names)
        data.append(
            {
                "capability": capability,
                "tools": [name for name in names if name in actual_tools],
                "source_ids": source_ids,
                "data_kind": kind,
                "configuration_status": "enabled" if enabled else "disabled",
                "upstream_health": "not_checked",
                "warning": warning,
            }
        )
    return data


def register_resources(server: MCPServer, settings: Settings) -> None:
    @server.resource(
        "izmir://coverage", name="izmir_coverage", title="İzmir veri kapsamı",
        description="Supported capabilities and configuration gates, not live source health.",
        mime_type="application/json",
    )
    async def coverage() -> str:
        actual_tools = {tool.name for tool in await server.list_tools()}
        return _document(
            "İzmir MCP configured coverage; upstream health not checked.",
            _coverage(settings, actual_tools),
            limits=[f"tool_count={len(actual_tools)}", f"max_radius_m={settings.max_radius_m}"],
        )

    @server.resource(
        "izmir://sources", name="izmir_sources", title="İzmir veri kaynakları",
        description="Canonical publishers and public source references; no secrets or deployment URLs.",
        mime_type="application/json",
    )
    def sources() -> str:
        return _document(
            "İzmir MCP source directory, not a health report.",
            [
                {
                    "source_id": source_id,
                    "name": name,
                    "publisher": publisher,
                    "url": url,
                    "data_kind": kind,
                    "license": None,
                    "license_note": "Inspect dataset/source terms; public read access is not a license grant.",
                    "freshness_note": "Actual timestamps, TTL and fallback status are supplied by each tool result.",
                    "upstream_health": "not_checked",
                }
                for source_id, name, publisher, url, kind in SOURCE_CATALOG
            ],
        )

    @server.resource(
        "izmir://schema/catalog", name="izmir_catalog_schema", title="Katalog keşif şeması",
        description="Catalog tool inputs, envelope schema and query bounds, not a live field schema.",
        mime_type="application/json",
    )
    async def catalog_schema() -> str:
        catalog_tools = {
            "izmir_search_datasets", "izmir_get_dataset",
            "izmir_get_resource_schema", "izmir_query_resource",
        }
        return _document(
            "Catalog discovery workflow and response contract.",
            [
                {
                    "workflow": [
                        "izmir_search_datasets",
                        "izmir_get_dataset",
                        "izmir_get_resource_schema",
                        "izmir_query_resource",
                    ],
                    "tools": [
                        {"name": tool.name, "input_schema": tool.input_schema}
                        for tool in await server.list_tools()
                        if tool.name in catalog_tools
                    ],
                    "envelope_schema": ResponseEnvelope.model_json_schema(),
                    "resource_fields_are_dynamic": True,
                    "field_schema_instruction": "Call izmir_get_resource_schema for the selected resource_id before querying.",
                    "query_bounds": {
                        "default_limit": settings.default_limit,
                        "max_limit": settings.max_limit,
                    },
                }
            ],
        )
