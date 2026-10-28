from __future__ import annotations

from typing import Literal

from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.settings import get_settings
from app.core.validation import (
    InputValidationError,
    resolve_limit,
    validate_date,
    validate_lat_lon,
    validate_radius,
)
from app.services.air import AirQualityService
from app.services.bus import BusService
from app.services.catalog import CatalogService
from app.services.city_services import KINDS as CITY_SERVICE_KINDS
from app.services.city_services import CityServicesService
from app.services.disruptions import DisruptionService
from app.services.markets import MarketService
from app.services.nearby import SUPPORTED_TYPES, NearbyService
from app.services.places import PlaceResolver
from app.services.transit import TransitService
from app.services.water import WaterService

settings = get_settings()

NearbyType = Literal[
    "parking", "pharmacy", "metro_station", "izban_station", "ferry_pier", "bus_stop",
]
TransitMode = Literal["metro", "izban", "izdeniz"]


def _validation(exc: InputValidationError) -> dict:
    return error_envelope(
        summary="Invalid request input.",
        warning=str(exc),
        code="validation_error",
        field=exc.field,
    )


async def izmir_health() -> dict:
    """Return İzmir MCP service readiness and advertised limits."""
    settings = get_settings()
    return success_envelope(
        summary="İzmir MCP is ready.",
        data=[
            {
                "service": "izmir-mcp",
                "catalog": settings.ckan_base_url,
                "open_data_api": settings.openapi_base_url,
                "upstream_health": "not_checked",
            }
        ],
        sources=[Source(name="İzmir MCP local runtime", publisher="İzmir MCP", url=None)],
        freshness=Freshness(status="fresh", ttl_seconds=30),
        limits=[
            f"default_limit={settings.default_limit}",
            f"max_limit={settings.max_limit}",
            f"max_radius_m={settings.max_radius_m}",
        ],
        warnings=["Bu araç yalnızca yerel hazırlığı bildirir; kaynak sağlığı kanıtı değildir."],
    )


async def izmir_search_datasets(
    query: str,
    formats: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    """Search the İzmir open data catalog by topic."""
    return await CatalogService(settings=get_settings()).search_datasets(
        query=query, formats=formats, limit=limit
    )


async def izmir_get_dataset(dataset_id: str) -> dict:
    """Return metadata and resources for one İzmir dataset."""
    return await CatalogService(settings=get_settings()).get_dataset(dataset_id)


async def izmir_get_resource_schema(resource_id: str) -> dict:
    """Return the DataStore field schema for one resource."""
    return await CatalogService(settings=get_settings()).get_resource_schema(resource_id)


async def izmir_query_resource(
    resource_id: str,
    filters: dict | None = None,
    limit: int | None = None,
) -> dict:
    """Query İzmir CKAN DataStore records with guarded filters and limits.

    Uses datastore_search, not SQL. Field names must come from the resource schema.
    """
    return await CatalogService(settings=get_settings()).query_resource(
        resource_id=resource_id, filters=filters, limit=limit
    )


async def izmir_nearby(
    lat: float | None = None,
    lon: float | None = None,
    place: str | None = None,
    types: list[NearbyType] | None = None,
    radius_m: int | None = None,
    limit: int | None = None,
) -> dict:
    """Find nearby İzmir parking, pharmacies, metro stations, İZBAN stations and ferry piers.

    Supply either coordinates or `place` (a district or neighborhood reference
    point such as Konak, Karşıyaka, Alsancak, Bornova Merkez). Reference points are
    approximate, not address geocoding. Parking occupancy is a snapshot; pharmacy
    rosters are daily and should be confirmed by phone. Static locations are not
    live service status.
    """
    settings = get_settings()
    try:
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        if (lat is None) != (lon is None):
            raise InputValidationError("lat and lon must be supplied together", field="lat")
        if place is not None and lat is not None:
            raise InputValidationError("place cannot be combined with lat/lon", field="place")
        selected = list(SUPPORTED_TYPES) if types is None else list(types)
        if not selected or any(kind not in SUPPORTED_TYPES for kind in selected):
            raise InputValidationError(
                f"types must be a non-empty subset of: {', '.join(SUPPORTED_TYPES)}",
                field="types",
            )
        if len(selected) > settings.max_nearby_types:
            raise InputValidationError(
                f"types must contain <= {settings.max_nearby_types} items", field="types"
            )
        reference_label = None
        if place is not None:
            resolved = PlaceResolver().resolve(place)
            lat, lon = resolved.lat, resolved.lon
            reference_label = f"{resolved.name} ({resolved.kind} reference point)"
        elif lat is None or lon is None:
            raise InputValidationError(
                "supply lat/lon or place (for example place='Konak')", field="place"
            )
        validate_lat_lon(lat, lon)
        if radius_m is None:
            # A district/neighborhood reference point needs a wider default
            # than an exact coordinate supplied by the caller.
            safe_radius = settings.max_radius_m if place is not None else 1500
        else:
            safe_radius = validate_radius(radius_m, settings.max_radius_m)
    except InputValidationError as exc:
        return _validation(exc)
    envelope = await NearbyService(settings=settings).nearby(
        lat=lat,
        lon=lon,
        types=selected,
        radius_m=safe_radius,
        limit=safe_limit,
        reference_label=reference_label,
    )
    if place is not None:
        envelope["warnings"] = [
            *envelope.get("warnings", []),
            "Konum, ilçe/mahalle için yaklaşık referans noktasıdır; kesin adres değildir.",
        ]
    return envelope


async def izmir_water_status(
    kind: Literal["dams", "faults"] = "dams",
    limit: int | None = None,
) -> dict:
    """Return İZSU dam occupancy, or report the unavailable outage feed.

    `kind="faults"` returns an explicit source-unavailable result: İZSU's public
    outage API returned HTTP 500 during verification. No outage data is invented.
    Dam levels come from the published İZSU CSV and can lag behind real time.
    """
    try:
        return await WaterService(settings=get_settings()).status(kind=kind, limit=limit)
    except InputValidationError as exc:
        return _validation(exc)


async def izmir_air_quality(
    date: str | None = None,
    station: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return İzmir air-quality station readings for one date.

    The source returns station names and pollutant values but no coordinates or
    units; observed_at may be earlier than the requested date.
    """
    try:
        day = validate_date(date)
    except InputValidationError as exc:
        return _validation(exc)
    return await AirQualityService(settings=get_settings()).readings(
        day=day, station=station, limit=limit
    )


async def izmir_transit_stations(
    mode: TransitMode,
    limit: int | None = None,
) -> dict:
    """List metro stations, İZBAN stations or İZDENİZ ferry piers with coordinates."""
    try:
        return await TransitService(settings=get_settings()).stations(mode=mode, limit=limit)
    except InputValidationError as exc:
        return _validation(exc)


async def izmir_transit_schedule(
    mode: TransitMode,
    from_id: int | None = None,
    to_id: int | None = None,
    pier_id: int | None = None,
    day: int = 1,
) -> dict:
    """Return a published timetable: metro frequency windows, İZBAN or İZDENİZ trips.

    Metro is a city-wide frequency table (no station pair). İZBAN requires
    from_id and to_id. İZDENİZ accepts pier_id, or from_id and to_id. `day` is the
    source's own day id, not a verified weekday. Timetables are not live ETAs.
    """
    try:
        return await TransitService(settings=get_settings()).schedule(
            mode=mode, from_id=from_id, to_id=to_id, pier_id=pier_id, day=day
        )
    except InputValidationError as exc:
        return _validation(exc)


async def izmir_bus_stops(
    query: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int | None = None,
    limit: int | None = None,
) -> dict:
    """Find EShot bus stops by name, or list stops within a radius of a coordinate.

    Supply `query` (stop name or stop id, matched case/accent-insensitively) or
    `lat`+`lon` with an optional `radius_m`. The stop list is the published
    `eshot-otobus-duraklari` dataset; locations are static, not live service.
    """
    try:
        return await BusService(settings=get_settings()).stops(
            query=query, lat=lat, lon=lon, radius_m=radius_m, limit=limit
        )
    except InputValidationError as exc:
        return _validation(exc)


async def izmir_bus_arrivals(stop_id: str, limit: int | None = None) -> dict:
    """Return EShot buses currently approaching one stop (live vehicle positions).

    `stop_id` must come from the published stop list (`izmir_bus_stops`). The
    source publishes remaining stop count and current vehicle position only; it
    has no ETA in minutes. An empty payload does not prove that no bus is running.
    """
    try:
        return await BusService(settings=get_settings()).arrivals(
            stop_id=str(stop_id or "").strip(), limit=limit
        )
    except InputValidationError as exc:
        return _validation(exc)


async def izmir_bus_routes(query: str | None = None, limit: int | None = None) -> dict:
    """List EShot routes from the published GTFS feed, optionally filtered by name.

    The feed's service calendar may be out of date; `calendar_end` and warnings
    show the verified window. GTFS `stop_times` are not loaded, so no departure
    times are returned.
    """
    try:
        return await BusService(settings=get_settings()).routes(query=query, limit=limit)
    except InputValidationError as exc:
        return _validation(exc)


CityServiceKind = Literal["wifi", "izmirim_card", "library"]


def _require_point(lat: float | None, lon: float | None, place: str | None) -> tuple[float, float, str | None]:
    settings = get_settings()
    if (lat is None) != (lon is None):
        raise InputValidationError("lat and lon must be supplied together", field="lat")
    if place is not None and lat is not None:
        raise InputValidationError("place cannot be combined with lat/lon", field="place")
    if place is not None:
        resolved = PlaceResolver().resolve(place)
        return resolved.lat, resolved.lon, f"{resolved.name} ({resolved.kind} reference point)"
    if lat is None or lon is None:
        raise InputValidationError(
            "supply lat/lon or place (for example place='Konak')", field="place"
        )
    validate_lat_lon(lat, lon)
    return lat, lon, None


async def izmir_market_schedule(
    day: str | None = None,
    district: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int | None = None,
    limit: int | None = None,
) -> dict:
    """List İzmir neighborhood market places, optionally filtered by weekday, district or proximity.

    `day` accepts a Turkish weekday (pazartesi..pazar), `bugun` or `yarin`. The
    weekday is parsed from the source's free-text note; rows without a parseable
    day carry `day_confidence='unknown'` and are never guessed. Coordinates are
    published; opening hours and open/closed status are not.
    """
    settings = get_settings()
    try:
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        return await MarketService(settings=settings).schedule(
            day=day, district=district, lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit
        )
    except InputValidationError as exc:
        return _validation(exc)


async def izmir_transport_disruptions(
    line: str | None = None,
    active_only: bool = False,
    limit: int | None = None,
) -> dict:
    """List published EShot bus line notices such as planned route changes.

    These are announcements, not live delays or vehicle status. `active` is
    derived from the notice's own start/end dates against the system date.
    """
    settings = get_settings()
    try:
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        return await DisruptionService(settings=settings).list(
            line=line, active_only=bool(active_only), limit=safe_limit
        )
    except InputValidationError as exc:
        return _validation(exc)


async def izmir_city_services_nearby(
    kinds: list[CityServiceKind] | None = None,
    lat: float | None = None,
    lon: float | None = None,
    place: str | None = None,
    radius_m: int | None = None,
    limit: int | None = None,
) -> dict:
    """Find WizmirNET WiFi points, İzmirim Kart top-up points and libraries.

    Supply coordinates or `place`. `kinds` defaults to all three. WiFi and card
    points carry published coordinates; the library layer has no coordinates, so
    libraries are listed by district and address and cannot be radius-filtered.
    All three are static snapshots, not live open/closed status.
    """
    settings = get_settings()
    try:
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        selected = list(CITY_SERVICE_KINDS) if kinds is None else list(kinds)
        if not selected or any(kind not in CITY_SERVICE_KINDS for kind in selected):
            raise InputValidationError(
                f"kinds must be a non-empty subset of: {', '.join(CITY_SERVICE_KINDS)}",
                field="kinds",
            )
        resolved_lat, resolved_lon, reference_label = _require_point(lat, lon, place)
        if radius_m is None:
            safe_radius = settings.max_radius_m if place is not None else 1500
        else:
            safe_radius = validate_radius(radius_m, settings.max_radius_m)
    except InputValidationError as exc:
        return _validation(exc)
    envelope = await CityServicesService(settings=settings).nearby(
        kinds=selected,
        lat=resolved_lat,
        lon=resolved_lon,
        radius_m=safe_radius,
        limit=safe_limit,
        reference_label=reference_label,
    )
    if place is not None:
        envelope["warnings"] = [
            *envelope.get("warnings", []),
            "Konum, ilçe/mahalle için yaklaşık referans noktasıdır; kesin adres değildir.",
        ]
    return envelope
