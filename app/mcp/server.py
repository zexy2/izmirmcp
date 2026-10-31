from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.settings import get_settings
from app.core.types import OptionalCount as _OptInt, OptionalNumber as _OptNum
from app.core.validation import (
    InputValidationError,
    resolve_limit,
    validate_date,
    validate_lat_lon,
    validate_radius,
)
from app.services.air import AirQualityService
from app.connectors.ibb_cbs import CBS_LAYERS, MARKET_KINDS
from app.services.bus import BusService
from app.services.cbs import CbsService
from app.services.catalog import CatalogService
from app.services.datastore_sql import DatastoreSqlService
from app.services.city_services import KINDS as CITY_SERVICE_KINDS
from app.services.city_info import CityInfoService
from app.services.city_services import CityServicesService
from app.services.disruptions import DisruptionService
from app.services.markets import MarketService
from app.services.nearby import SUPPORTED_TYPES, NearbyService
from app.services.neighborhood import NeighborhoodService
from app.services.places import PlaceResolver
from app.services.traffic import TrafficService
from app.services.transit import TransitService
from app.services.trip import TripPlanner
from app.services.water import WaterService

settings = get_settings()

# Derived from the service's own list: a layer the service learns to answer
# cannot stay rejected by the tool schema, and vice versa.
if TYPE_CHECKING:
    # mypy cannot evaluate a Literal built from a runtime tuple; the JSON schema
    # still comes from the runtime branch below.
    NearbyType = str
else:
    NearbyType = Literal[*SUPPORTED_TYPES]
TransitMode = Literal["metro", "izban", "izdeniz"]
DisruptionOperator = Literal["eshot", "metro", "izdeniz", "izban"]


def _reject_boolean_number(value: object, field: str) -> None:
    """Catch ``{"lat": true}`` before pydantic coerces it to 1.0.

    ``float | None`` accepts a bool and turns it into 1.0, so by the time the
    service sees it the caller's mistake is invisible and the query silently
    targets the Gulf of Guinea. Rejecting here keeps the error attributable.
    """
    if isinstance(value, bool):
        raise InputValidationError(f"{field} sayı olmalıdır; mantıksal değer kabul edilmez", field=field)


def _validation(exc: InputValidationError, *, tool: str | None = None) -> dict:
    """Reject an input with a typed envelope plus a structured repair hint."""
    from app.core.error_responses import validation_error_envelope

    return validation_error_envelope(exc, tool=tool)


async def izmir_health() -> dict:
    """Return İzmir MCP service readiness and advertised limits."""
    settings = get_settings()
    return success_envelope(
        summary="İzmir MCP hazır.",
        data=[
            {
                "service": "izmir-mcp",
                # Human-facing portals only. Raw API bases taught callers to
                # scrape upstream endpoints directly and bypass this server.
                "catalog": "https://acikveri.bizizmir.com",
                "open_data_portal": "https://www.izmir.bel.tr",
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
    limit: _OptInt = None,
) -> dict:
    """Search the İzmir open data catalog by topic."""
    return await CatalogService(settings=get_settings()).search_datasets(query=query, formats=formats, limit=limit)


async def izmir_get_dataset(dataset_id: str) -> dict:
    """Return metadata and resources for one İzmir dataset."""
    return await CatalogService(settings=get_settings()).get_dataset(dataset_id)


async def izmir_get_resource_schema(resource_id: str) -> dict:
    """Return the DataStore field schema for one resource."""
    return await CatalogService(settings=get_settings()).get_resource_schema(resource_id)


async def izmir_query_resource(
    resource_id: str,
    filters: dict | None = None,
    search: str | None = None,
    sort: str | None = None,
    limit: _OptInt = None,
) -> dict:
    """Query İzmir CKAN DataStore records with guarded filters, search and sort.

    Uses ``datastore_search`` only: this CKAN does not expose
    ``datastore_search_sql`` ("Action name not known"), so no SQL is accepted.
    - `filters`: exact-match object; field names must come from the resource schema.
    - `search`: free-text server-side match (`q`), not SQL.
    - `sort`: ``COLUMN`` or ``COLUMN asc|desc``; the column must exist in the schema.
    """
    return await CatalogService(settings=get_settings()).query_resource(
        resource_id=resource_id, filters=filters, search=search, sort=sort, limit=limit
    )


async def izmir_datastore_query(
    resource_id: str,
    sql: str,
    limit: int | None = None,
) -> dict:
    """Run one bounded SELECT over a complete local snapshot of an allowlisted resource.

    İzmir's CKAN has no ``datastore_search_sql``. The server downloads the whole
    allowlisted DataStore resource into an isolated in-memory SQLite table named
    ``records`` and runs a single SELECT there. Use ``izmir_get_resource_schema``
    first for published column names. No joins, subqueries, CTEs, unions, windows,
    writes or arbitrary functions are allowed, and a snapshot that cannot be
    captured completely is reported as ``source_unavailable`` instead of a partial
    aggregate. The resource must be enabled in
    ``IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS``.
    """
    return await DatastoreSqlService(settings=get_settings()).query(resource_id=resource_id, sql=sql, limit=limit)


async def izmir_nearby(
    lat: _OptNum = None,
    lon: _OptNum = None,
    place: str | None = None,
    place_district: str | None = None,
    bbox: list[float] | None = None,
    district: str | None = None,
    types: list[NearbyType] | None = None,
    radius_m: _OptInt = None,
    limit: _OptInt = None,
) -> dict:
    """Find İzmir services by radius, rectangle or district-wide list.

    Supply exactly one location mode:
    - `lat`+`lon`, or `place` (an approximate district/neighborhood reference
      point such as Konak, Karşıyaka, Alsancak) with an optional `radius_m`.
    - `bbox` as `[min_lon, min_lat, max_lon, max_lat]`; all edges are inclusive,
      there is no reference point, and `distance_m` is null.
    - `district` for a district-wide list without distances. Currently only
      pharmacy publishes a usable district/region label; other selected types
      are skipped with a warning because their sources publish no district.
    Parking occupancy is a snapshot; pharmacy rosters are daily and should be
    confirmed by phone. Static locations are not live service status.
    """
    settings = get_settings()
    try:
        _reject_boolean_number(lat, "lat")
        _reject_boolean_number(lon, "lon")
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        if (lat is None) != (lon is None):
            raise InputValidationError("lat ve lon birlikte verilmelidir", field="lat")
        if place is not None and lat is not None:
            raise InputValidationError("place ile lat/lon birlikte kullanılamaz", field="place")
        location_modes = sum([bbox is not None, district is not None, place is not None, lat is not None])
        if location_modes > 1:
            raise InputValidationError(
                "bbox, district, place ve lat/lon aynı anda kullanılamaz; yalnızca bir mod seçin",
                field="bbox" if bbox is not None else "district",
            )
        if (bbox is not None or district is not None) and radius_m is not None:
            raise InputValidationError(
                "radius_m yalnızca lat/lon veya place modunda geçerlidir; bbox/district ile kullanılamaz",
                field="radius_m",
            )
        selected = list(SUPPORTED_TYPES) if types is None else list(types)
        if not selected or any(kind not in SUPPORTED_TYPES for kind in selected):
            raise InputValidationError(
                f"types boş olamaz; şunlardan bir alt küme olmalıdır: {', '.join(SUPPORTED_TYPES)}",
                field="types",
            )
        if len(selected) > settings.max_nearby_types:
            raise InputValidationError(f"types en fazla {settings.max_nearby_types} öğe içerebilir", field="types")
        if bbox is not None:
            return await NearbyService(settings=settings).bbox(bbox=bbox, types=selected, limit=safe_limit)
        if district is not None:
            return await NearbyService(settings=settings).district(district=district, types=selected, limit=safe_limit)
        reference_label = None
        if place_district is not None and place is None:
            raise InputValidationError("place_district yalnızca place ile kullanılabilir", field="place_district")
        if place is not None:
            resolved = PlaceResolver().resolve(place, district=place_district)
            lat, lon = resolved.lat, resolved.lon
            where = f"{resolved.name}, {resolved.district}" if resolved.district else resolved.name
            reference_label = f"{where} (referans noktası)"
        elif lat is None or lon is None:
            raise InputValidationError(
                "lat/lon, place, bbox veya district verin (örn. place='Konak')",
                field="place",
            )
        validate_lat_lon(lat, lon)
        if radius_m is None:
            # A district/neighborhood reference point needs a wider default
            # than an exact coordinate supplied by the caller.
            safe_radius = settings.max_radius_m if place is not None else 1500
        else:
            safe_radius = validate_radius(radius_m, settings.max_radius_m)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_nearby")
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


async def izmir_mobility_nearby(
    lat: _OptNum = None,
    lon: _OptNum = None,
    place: str | None = None,
    place_district: str | None = None,
    radius_m: _OptInt = None,
    limit: _OptInt = None,
) -> dict:
    """Answer "what transport is near me" in one envelope.

    Preset over `izmir_nearby` with transport layers only: metro, İZBAN and
    ferry stops, ESHOT bus stops, taxi stands, charging stations and parking,
    nearest first, plus a per-mode count in `summary`. Supply `lat`+`lon` or a
    published `place` reference point (never an address). Two upstream
    mobility components cannot be included honestly: İzmir publishes no
    air-quality station coordinates and no live traffic index
    (`/api/ibb/trafikyogunluk` returns 404); both are stated in `warnings`.
    Locations are static/published, not live service or ETA.
    """
    settings = get_settings()
    try:
        _reject_boolean_number(lat, "lat")
        _reject_boolean_number(lon, "lon")
        lat_value, lon_value, label = _require_point(lat, lon, place, place_district)
        safe_radius = validate_radius(1000 if radius_m is None else radius_m, settings.max_radius_m)
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_mobility_nearby")
    envelope = await NearbyService(settings=settings).mobility(
        lat=lat_value,
        lon=lon_value,
        radius_m=safe_radius,
        limit=safe_limit,
        reference_label=label,
    )
    if place is not None:
        envelope["warnings"] = sorted(
            set(
                [
                    *envelope.get("warnings", []),
                    "Konum, ilçe/mahalle için yaklaşık referans noktasıdır; kesin adres değildir.",
                ]
            )
        )
    return envelope


async def izmir_water_status(
    kind: Literal["dams", "faults"] = "dams",
    limit: _OptInt = None,
) -> dict:
    """Return İZSU dam occupancy, or report the unavailable outage feed.

    `kind="faults"` returns an explicit source-unavailable result: İZSU's public
    outage API returned HTTP 500 during verification. No outage data is invented.
    Dam levels come from the published İZSU CSV and can lag behind real time.
    """
    try:
        return await WaterService(settings=get_settings()).status(kind=kind, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_water_status")


async def izmir_air_quality(
    date: str | None = None,
    station: str | None = None,
    limit: _OptInt = None,
) -> dict:
    """Return İzmir air-quality station readings for one date.

    The source returns station names and pollutant values but no coordinates or
    units; observed_at may be earlier than the requested date.
    """
    try:
        day = validate_date(date)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_air_quality")
    return await AirQualityService(settings=get_settings()).readings(day=day, station=station, limit=limit)


async def izmir_transit_stations(
    mode: TransitMode,
    limit: _OptInt = None,
) -> dict:
    """List metro stations, İZBAN stations or İZDENİZ ferry piers with coordinates."""
    try:
        return await TransitService(settings=get_settings()).stations(mode=mode, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_transit_stations")


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
        return _validation(exc, tool="izmir_transit_schedule")


async def izmir_neighborhood_profile(
    neighborhood: str | None = None,
    district: str | None = None,
    limit: _OptInt = None,
) -> dict:
    """Return published population and building counts for İzmir neighborhoods.

    Supply `neighborhood` (with an optional `district` hint) for one profile, or
    `district` alone to list that district's neighborhoods. Joined from two
    separately published CKAN layers; they carry different publication years, so
    `population_year`/`building_year` are null when the source publishes none.
    `persons_per_building` is a raw division, not a census-time snapshot.
    """
    try:
        return await NeighborhoodService(settings=get_settings()).profile(
            neighborhood=neighborhood, district=district, limit=limit
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_neighborhood_profile")


async def izmir_traffic_history(
    segment: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return İzmir arterial speed/duration **history**, not live traffic.

    İzmir publishes no live traffic index (`/api/ibb/trafikyogunluk` returns 404).
    The only real data is a per-segment history: fixed point pairs such as
    "Marina Kavşağı → Konak Pier" with measured speed and duration. `since` and
    `until` are YYYY-MM-DD; `segment` matches either endpoint name.
    """
    settings = get_settings()
    try:
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        return await TrafficService(settings=settings).list(segment=segment, since=since, until=until, limit=safe_limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_traffic_history")


async def izmir_gtfs_status() -> dict:
    """Report the local EShot GTFS timetable store without touching the network.

    Returns build time, feed publication time, row counts and the service
    calendar window, and says explicitly when that calendar has expired. A
    missing store is source_unavailable, not an empty timetable. This never
    proves live departures or vehicle positions.
    """
    return await BusService(settings=get_settings()).timetable_status()


async def izmir_bus_stops(
    query: str | None = None,
    lat: _OptNum = None,
    lon: _OptNum = None,
    radius_m: _OptInt = None,
    limit: _OptInt = None,
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
        return _validation(exc, tool="izmir_bus_stops")


async def izmir_bus_arrivals(stop_id: str, limit: int | None = None) -> dict:
    """Return EShot buses currently approaching one stop (live vehicle positions).

    `stop_id` must come from the published stop list (`izmir_bus_stops`). The
    source publishes remaining stop count and current vehicle position only; it
    has no ETA in minutes. An empty payload does not prove that no bus is running.
    """
    try:
        return await BusService(settings=get_settings()).arrivals(stop_id=str(stop_id or "").strip(), limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_bus_arrivals")


async def izmir_bus_departures(
    stop_id: str | None = None,
    stop_query: str | None = None,
    lat: _OptNum = None,
    lon: _OptNum = None,
    radius_m: _OptInt = None,
    at: str | None = None,
    line: str | None = None,
    limit: _OptInt = None,
) -> dict:
    """Return scheduled GTFS departures for one stop, or for stops near a point.

    Supply exactly one target:
    - `stop_id` for one published EShot stop.
    - `stop_query` to find stop ids by name (Turkish/ASCII spellings, fuzzy
      suggestions labelled). This mode returns stop candidates, **not**
      departures; confirm one, then call again with `stop_id`.
    - `lat`+`lon` with an optional `radius_m` (default 500 m) to merge planned
      departures from the nearest published stops; each row carries `stop_id`,
      `stop_name` and `distance_m`.
    `at` accepts `HH:MM` (Europe/Istanbul) or an ISO-8601 date/time and defaults
    to now; it does not apply to `stop_query`. `line` filters departures by
    published route short name. Results are published timetable times, never
    live ETAs, and every answer carries the feed's `calendar_end`. The EShot
    calendar currently ends on 2026-10-09, so later dates return no timetable
    rows with an explicit staleness warning.
    """
    _reject_boolean_number(lat, "lat")
    _reject_boolean_number(lon, "lon")
    try:
        return await BusService(settings=get_settings()).departures(
            stop_id=stop_id,
            stop_query=stop_query,
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            at=at,
            line=line,
            limit=limit,
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_bus_departures")


async def izmir_bus_routes(
    query: str | None = None,
    detail: bool = False,
    direction: str | None = None,
    limit: _OptInt = None,
) -> dict:
    """List EShot routes, or return one line's ordered stops per direction.

    `detail=true` requires `query` to be an exact line code or route id and
    returns every published stop pattern for each `direction_id`, in
    `stop_sequence` order. `direction` (`0` or `1`) filters to one direction and
    is only valid with `detail=true`; `limit` then does not truncate patterns.
    The feed's service calendar may be out of date; `calendar_end`, limits and
    warnings show the verified window. Stop names and headsigns come from the
    feed and are never invented. Scheduled stop departures are returned by
    `izmir_bus_departures`.
    """
    try:
        return await BusService(settings=get_settings()).routes(
            query=query, detail=detail, direction=direction, limit=limit
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_bus_routes")


CityServiceKind = Literal["wifi", "izmirim_card", "library"]


def _require_point(
    lat: float | None,
    lon: float | None,
    place: str | None,
    place_district: str | None = None,
) -> tuple[float, float, str | None]:
    _reject_boolean_number(lat, "lat")
    _reject_boolean_number(lon, "lon")
    if (lat is None) != (lon is None):
        raise InputValidationError("lat ve lon birlikte verilmelidir", field="lat")
    if place is not None and lat is not None:
        raise InputValidationError("place ile lat/lon birlikte kullanılamaz", field="place")
    if place_district is not None and place is None:
        raise InputValidationError("place_district yalnızca place ile kullanılabilir", field="place_district")
    if place is not None:
        resolved = PlaceResolver().resolve(place, district=place_district)
        where = f"{resolved.name}, {resolved.district}" if resolved.district else resolved.name
        return resolved.lat, resolved.lon, f"{where} (referans noktası)"
    if lat is None or lon is None:
        raise InputValidationError("lat/lon veya place verin (örn. place='Konak')", field="place")
    validate_lat_lon(lat, lon)
    return lat, lon, None


async def izmir_market_schedule(
    day: str | None = None,
    district: str | None = None,
    lat: _OptNum = None,
    lon: _OptNum = None,
    radius_m: _OptInt = None,
    limit: _OptInt = None,
) -> dict:
    """List İzmir neighborhood market places, optionally filtered by weekday, district or proximity.

    `day` accepts a Turkish weekday (pazartesi..pazar), `bugun` or `yarin`. The
    weekday is parsed from the source's free-text note; rows without a parseable
    day carry `day_confidence='unknown'` and are never guessed. Coordinates are
    published; opening hours and open/closed status are not.
    """
    settings = get_settings()
    try:
        _reject_boolean_number(lat, "lat")
        _reject_boolean_number(lon, "lon")
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        return await MarketService(settings=settings).schedule(
            day=day, district=district, lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_market_schedule")


async def izmir_transport_disruptions(
    operator: DisruptionOperator | None = None,
    line: str | None = None,
    active_only: bool = False,
    limit: _OptInt = None,
) -> dict:
    """List published transport announcements for İzmir operators.

    Operators: eshot (bus line notices with start/end dates), metro (İzmir Metro
    announcements) and izdeniz (ferry announcements). Omit `operator` to merge
    all three. These are announcements, not live delays or vehicle telemetry.
    `active` is computed only for ESHOT, which publishes a validity window;
    for the others it is null because no window is published.

    `operator="izban"` returns an explicit source_unavailable: İZBAN has no
    reachable announcement feed (verified 2026-10-28).
    """
    settings = get_settings()
    try:
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        return await DisruptionService(settings=settings).list(
            operator=operator, line=line, active_only=bool(active_only), limit=safe_limit
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_transport_disruptions")


async def izmir_city_services_nearby(
    kinds: list[CityServiceKind] | None = None,
    lat: _OptNum = None,
    lon: _OptNum = None,
    place: str | None = None,
    place_district: str | None = None,
    bbox: list[float] | None = None,
    district: str | None = None,
    radius_m: _OptInt = None,
    limit: _OptInt = None,
) -> dict:
    """Find WizmirNET WiFi points, İzmirim Kart top-up points and libraries.

    Supply exactly one location mode:
    - `lat`+`lon`, or `place` with an optional `radius_m` (distance-ranked).
    - `bbox` as `[min_lon, min_lat, max_lon, max_lat]`; edges inclusive, no
      reference point, `distance_m` is null. The library layer publishes no
      coordinates and therefore never appears in a rectangle.
    - `district` for a district-wide list; matching uses the source's own
      district field or address text, not an administrative boundary.
    `kinds` defaults to all three. All three are static snapshots, not live
    open/closed status.
    """
    settings = get_settings()
    try:
        safe_limit = resolve_limit(limit, settings.default_limit, settings.max_limit)
        selected: list[str] = list(CITY_SERVICE_KINDS) if kinds is None else list(kinds)
        if not selected or any(kind not in CITY_SERVICE_KINDS for kind in selected):
            raise InputValidationError(
                f"kinds boş olamaz; şunlardan bir alt küme olmalıdır: {', '.join(CITY_SERVICE_KINDS)}",
                field="kinds",
            )
        if (lat is None) != (lon is None):
            raise InputValidationError("lat ve lon birlikte verilmelidir", field="lat")
        if place is not None and lat is not None:
            raise InputValidationError("place ile lat/lon birlikte kullanılamaz", field="place")
        location_modes = sum([bbox is not None, district is not None, place is not None, lat is not None])
        if location_modes > 1:
            raise InputValidationError(
                "bbox, district, place ve lat/lon aynı anda kullanılamaz; yalnızca bir mod seçin",
                field="bbox" if bbox is not None else "district",
            )
        if (bbox is not None or district is not None) and radius_m is not None:
            raise InputValidationError(
                "radius_m yalnızca lat/lon veya place modunda geçerlidir; bbox/district ile kullanılamaz",
                field="radius_m",
            )
        if bbox is not None:
            return await CityServicesService(settings=settings).bbox(bbox=bbox, kinds=selected, limit=safe_limit)
        if district is not None:
            return await CityServicesService(settings=settings).district(
                district=district, kinds=selected, limit=safe_limit
            )
        resolved_lat, resolved_lon, reference_label = _require_point(lat, lon, place, place_district)
        if radius_m is None:
            safe_radius = settings.max_radius_m if place is not None else 1500
        else:
            safe_radius = validate_radius(radius_m, settings.max_radius_m)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_city_services_nearby")
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


if TYPE_CHECKING:
    CbsLayer = str
    HalKind = str
else:
    CbsLayer = Literal[*CBS_LAYERS]
    HalKind = Literal[*MARKET_KINDS]


async def izmir_tram_lines() -> dict:
    """List İzmir tram lines and directions with their `line_id` values.

    Use the returned `line_id` with `izmir_tram_schedule`. Published data only,
    not live tram positions.
    """
    return await TransitService(settings=get_settings()).tram_lines()


async def izmir_tram_schedule(line_id: int) -> dict:
    """Return stations and published headways for one tram line.

    `line_id` must come from `izmir_tram_lines`. Headways are a published
    timetable, not live arrival times.
    """
    try:
        return await TransitService(settings=get_settings()).tram_schedule(line_id=line_id)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_tram_schedule")


async def izmir_bus_line_arrivals(line: str, stop_id: str | None = None, limit: _OptInt = None) -> dict:
    """Return buses of one EShot line approaching a stop.

    With `stop_id` (from `izmir_bus_stops`) the stop's live arrivals are filtered
    to `line`. Without it there is no stop to approach, so the line's live bus
    positions are returned instead. No ETA in minutes is published.
    """
    try:
        return await BusService(settings=get_settings()).line_arrivals(line=line, stop_id=stop_id, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_bus_line_arrivals")


async def izmir_bus_live_positions(line: str, limit: _OptInt = None) -> dict:
    """Return live vehicle positions of buses on one EShot line.

    Positions are cached for at most 15 seconds and are a snapshot; an empty
    result does not prove that no bus is running.
    """
    try:
        return await BusService(settings=get_settings()).line_live_positions(line=line, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_bus_live_positions")


async def izmir_dam_status(date: str | None = None, dam_name: str | None = None, limit: _OptInt = None) -> dict:
    """Return İZSU dam levels for one day, optionally a single dam.

    `date` is `YYYY-MM-DD` (default today, never in the future). `dam_name`
    matches case- and Turkish-letter-insensitively (e.g. "Tahtalı").
    """
    try:
        return await WaterService(settings=get_settings()).dam_status(date=date, dam_name=dam_name, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_dam_status")


async def izmir_pharmacies_all(
    area: str | None = None,
    query: str | None = None,
    lat: _OptNum = None,
    lon: _OptNum = None,
    radius_m: _OptInt = None,
    limit: _OptInt = None,
) -> dict:
    """List all İzmir pharmacies (not only on-duty ones).

    `area` filters the published region label, `query` the name. `lat`+`lon`
    with optional `radius_m` ranks by straight-line distance. For tonight's
    on-duty pharmacy use `izmir_nearby(types=["pharmacy"])`.
    """
    try:
        _reject_boolean_number(lat, "lat")
        _reject_boolean_number(lon, "lon")
        return await CbsService(settings=get_settings()).pharmacies_all(
            area=area,
            query=query,
            near_lat=lat,
            near_lon=lon,
            radius_m=radius_m,
            limit=limit,
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_pharmacies_all")


async def izmir_cbs_layer(
    layer: CbsLayer,
    lat: _OptNum = None,
    lon: _OptNum = None,
    radius_m: _OptInt = None,
    district: str | None = None,
    limit: _OptInt = None,
) -> dict:
    """Return places from one allowlisted İzmir Büyükşehir GIS (CBS) layer.

    Examples: muzeler, hastaneler, plajlar, kutuphaneler. Locations are a
    published layer, not opening hours or live status.
    """
    try:
        _reject_boolean_number(lat, "lat")
        _reject_boolean_number(lon, "lon")
        return await CbsService(settings=get_settings()).layer(
            layer=layer,
            near_lat=lat,
            near_lon=lon,
            radius_m=radius_m,
            district=district,
            limit=limit,
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_cbs_layer")


async def izmir_events(query: str | None = None, free_only: bool = False, limit: _OptInt = None) -> dict:
    """Return İzmir Büyükşehir culture and arts events.

    `query` matches title/venue text; `free_only` keeps free events. Confirm
    times with the organiser before attending.
    """
    try:
        return await CbsService(settings=get_settings()).events(query=query, free_only=free_only, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_events")


async def izmir_market_prices(
    kind: HalKind = "sebzemeyve",
    day: str | None = None,
    query: str | None = None,
    limit: _OptInt = None,
) -> dict:
    """Return İzmir wholesale market (hal) prices for produce or fish.

    `day` is `YYYY-MM-DD` (default today). If the source has no prices for
    that day, earlier days are tried and the actual day is reported. For
    neighbourhood market days use `izmir_market_schedule`.
    """
    try:
        return await CbsService(settings=get_settings()).market_prices(kind=kind, day=day, query=query, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_market_prices")


async def izmir_fare(
    from_station: int | str,
    to_station: int | str,
    transfer: bool = False,
    htt: bool = False,
) -> dict:
    """Return the published İZBAN fare between two stations (TL, by rider type).

    `from_station`/`to_station` take an İZBAN station id or name (Turkish
    letters and case are ignored; an ambiguous name is rejected with the
    candidates). `transfer` is the source's aktarma flag; `htt` is the source's
    own tariff flag whose meaning the API does not document. Not a live price.
    """
    try:
        _reject_boolean_number(from_station, "from_station")
        _reject_boolean_number(to_station, "to_station")
        return await CityInfoService(settings=get_settings()).izban_fare(
            from_station=from_station, to_station=to_station, transfer=transfer, htt=htt
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_fare")


async def izmir_parking_fees(query: str | None = None, limit: _OptInt = None) -> dict:
    """Return İZELMAN's published parking tariffs (TL per duration band).

    `query` is a plain name fragment (e.g. "Konak"). For live free spaces use
    `izmir_nearby(types=["parking"])`; this tool has tariffs only.
    """
    try:
        return await CityInfoService(settings=get_settings()).parking_fees(query=query, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_parking_fees")


async def izmir_traffic_cameras(
    query: str | None = None,
    lat: _OptNum = None,
    lon: _OptNum = None,
    radius_m: _OptInt = None,
    limit: _OptInt = None,
) -> dict:
    """Return İzmir traffic camera locations, optionally near a point.

    Locations only: the source publishes no image or stream URL. `lat`+`lon`
    with optional `radius_m` (default 2000, max 50000) ranks by distance.
    """
    try:
        _reject_boolean_number(lat, "lat")
        _reject_boolean_number(lon, "lon")
        return await CityInfoService(settings=get_settings()).traffic_cameras(
            query=query, lat=lat, lon=lon, radius_m=radius_m, limit=limit
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_traffic_cameras")


async def izmir_water_production(name: str | None = None, limit: _OptInt = None) -> dict:
    """Return IZSU water production per dam or well group (latest published snapshot).

    The resource has no date column, so this is not "today's" production and
    the unit is not stated by the source. For dam fill levels use `izmir_dam_status`.
    """
    try:
        return await CityInfoService(settings=get_settings()).water_production(name=name, limit=limit)
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_water_production")


async def izmir_plan_trip(
    origin: str,
    destination: str,
    depart_at: str | None = None,
    max_options: int = 3,
) -> dict:
    """Compare direct public-transport options between two İzmir places.

    `origin`/`destination` are district or neighbourhood names (max 80 chars).
    Returns up to `max_options` (1-5) single-mode options (metro, İZBAN,
    İZDENİZ ferry, ESHOT bus) ranked by approximate duration, with walk/ride
    legs, the İZBAN fare when known and active disruption titles. Durations are
    straight-line estimates, not a timetable or live ETA. `depart_at` is an
    ISO-8601 time kept for information only. Partial results are returned when
    an upstream fails; use `izmir_transit_schedule` for actual departures.
    """
    try:
        return await TripPlanner(settings=get_settings()).plan(
            origin=origin, destination=destination, depart_at=depart_at, max_options=max_options
        )
    except InputValidationError as exc:
        return _validation(exc, tool="izmir_plan_trip")
