from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_list(name: str) -> tuple[str, ...]:
    """Comma-separated env value; empty entries are dropped, order is preserved."""
    raw = os.getenv(name)
    if raw is None:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000

    request_timeout_seconds: float = 15.0
    request_attempts: int = 2
    response_max_bytes: int = 2_000_000

    default_limit: int = 10
    max_limit: int = 50
    max_radius_m: int = 5_000
    max_nearby_types: int = 8

    ckan_base_url: str = "https://acikveri.bizizmir.com/api/3/action"
    ckan_catalog_cache_ttl_seconds: int = 21_600
    ckan_resource_cache_ttl_seconds: int = 300

    # Bounded local SQL over complete CKAN snapshots. Empty by default: no
    # resource is downloaded unless an operator explicitly allowlists it.
    ckan_sql_allowed_resource_ids: tuple[str, ...] = ()
    ckan_sql_max_rows: int = 50_000
    ckan_sql_max_bytes: int = 20 * 1024 * 1024
    ckan_sql_page_size: int = 5_000
    ckan_sql_snapshot_ttl_seconds: int = 900
    ckan_sql_load_timeout_seconds: float = 30.0
    ckan_sql_query_timeout_seconds: float = 0.5

    openapi_base_url: str = "https://openapi.izmir.bel.tr/api"
    openapi_cache_ttl_seconds: int = 120
    openapi_stale_if_error_seconds: int = 900

    izsu_dams_csv_url: str = "https://openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv"
    izsu_cache_ttl_seconds: int = 3_600
    izsu_stale_if_error_seconds: int = 86_400
    izsu_api_base_url: str = "https://izsu.gov.tr/api/proxy"
    izsu_past_cache_ttl_seconds: int = 7 * 86_400

    # Live bus positions are volatile; the connector clamps this to <= 15 s.
    iztek_positions_cache_ttl_seconds: int = 15

    # İBB CBS layers, events, hal prices and the full pharmacy list share the
    # openapi host cooldown, so pages are capped and responses cached.
    cbs_max_pages: int = 10
    cbs_cache_ttl_seconds: int = 86_400
    events_cache_ttl_seconds: int = 3_600
    hal_cache_ttl_seconds: int = 7 * 86_400
    pharmacies_all_cache_ttl_seconds: int = 86_400

    eshot_stops_resource_id: str = "0c791266-a2e4-4f14-82b8-9a9b102fbf94"
    eshot_routes_resource_id: str = "bd6c84f8-49ba-4cf4-81f8-81a0fbb5caa3"
    eshot_datastore_page_size: int = 1_000
    eshot_cache_ttl_seconds: int = 86_400
    eshot_stale_if_error_seconds: int = 604_800

    iztek_base_url: str = "https://openapi.izmir.bel.tr/api/iztek"
    iztek_cache_ttl_seconds: int = 20
    iztek_min_request_interval_seconds: float = 0.5

    eshot_gtfs_url: str = "https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip"
    eshot_gtfs_max_bytes: int = 64 * 1024 * 1024
    eshot_gtfs_member_max_bytes: int = 8 * 1024 * 1024
    eshot_gtfs_stop_times_max_bytes: int = 128 * 1024 * 1024
    eshot_gtfs_max_rows: int = 2_500_000
    eshot_gtfs_cache_ttl_seconds: int = 86_400
    eshot_gtfs_stale_if_error_seconds: int = 604_800

    database_path: str = ".data/izmir_mcp.sqlite3"
    # GTFS builds replace the whole file. Keeping it separate from the spatial
    # index/quota database prevents a rebuild from silently wiping other state.
    gtfs_database_path: str = ".data/izmir_mcp_gtfs.sqlite3"

    eshot_notices_csv_url: str = "https://openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv"
    eshot_notices_cache_ttl_seconds: int = 1_800

    city_layer_cache_ttl_seconds: int = 86_400
    city_layer_stale_if_error_seconds: int = 604_800
    # Traffic rows are daily arterial snapshots. A newest observation older
    # than this is reported as stale instead of fresh.
    traffic_stale_after_hours: int = 72

    mcp_max_body_bytes: int = 1_000_000

    client_max_body_bytes: int = 1_000_000
    client_rate_limit_capacity: int = 60
    client_rate_limit_refill_per_second: float = 1.0
    client_rate_limit_max_clients: int = 10_000
    client_max_concurrent_requests: int = 32
    mcp_api_keys: tuple[str, ...] = ()
    api_key_daily_quota: int = 0
    mcp_cors_allowed_origins: tuple[str, ...] = ()
    access_log_enabled: bool = True

    # Inbound Host policy. Empty keeps the old behaviour (warn only) so existing
    # deployments behind a custom domain keep working until configured.
    mcp_allowed_hosts: tuple[str, ...] = ()
    # Fail closed: refuse to start on a non-loopback bind without API keys.
    mcp_require_auth: bool = False

    # Resilience knobs consumed by the HTTP connector, source cache and the
    # event-loop watchdog. 0 disables the watchdog.
    http_total_deadline_seconds: float = 0.0  # 0 => 2 × request_timeout_seconds
    source_cache_max_entries: int = 512
    event_loop_watchdog_seconds: float = 0.0
    source_rate_capacity: int = 10
    source_rate_refill_per_second: float = 2.0
    source_rate_max_wait_seconds: float = 2.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        host=os.getenv("IZMIR_MCP_HOST", "127.0.0.1"),
        port=_env_int("IZMIR_MCP_PORT", 8000),
        request_timeout_seconds=_env_float("IZMIR_MCP_REQUEST_TIMEOUT_SECONDS", 15.0),
        request_attempts=_env_int("IZMIR_MCP_REQUEST_ATTEMPTS", 2),
        response_max_bytes=_env_int("IZMIR_MCP_RESPONSE_MAX_BYTES", 2_000_000),
        default_limit=_env_int("IZMIR_MCP_DEFAULT_LIMIT", 10),
        max_limit=_env_int("IZMIR_MCP_MAX_LIMIT", 50),
        max_radius_m=_env_int("IZMIR_MCP_MAX_RADIUS_M", 5_000),
        ckan_base_url=os.getenv("IZMIR_MCP_CKAN_BASE_URL", "https://acikveri.bizizmir.com/api/3/action"),
        ckan_sql_allowed_resource_ids=_env_list("IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS"),
        ckan_sql_max_rows=_env_int("IZMIR_MCP_CKAN_SQL_MAX_ROWS", 50_000),
        ckan_sql_max_bytes=_env_int("IZMIR_MCP_CKAN_SQL_MAX_BYTES", 20 * 1024 * 1024),
        ckan_sql_page_size=_env_int("IZMIR_MCP_CKAN_SQL_PAGE_SIZE", 5_000),
        ckan_sql_snapshot_ttl_seconds=_env_int("IZMIR_MCP_CKAN_SQL_SNAPSHOT_TTL_SECONDS", 900),
        ckan_sql_load_timeout_seconds=_env_float("IZMIR_MCP_CKAN_SQL_LOAD_TIMEOUT_SECONDS", 30.0),
        ckan_sql_query_timeout_seconds=_env_float("IZMIR_MCP_CKAN_SQL_QUERY_TIMEOUT_SECONDS", 0.5),
        openapi_base_url=os.getenv("IZMIR_MCP_OPENAPI_BASE_URL", "https://openapi.izmir.bel.tr/api"),
        izsu_dams_csv_url=os.getenv(
            "IZMIR_MCP_IZSU_DAMS_CSV_URL",
            "https://openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv",
        ),
        izsu_api_base_url=os.getenv("IZMIR_MCP_IZSU_API_BASE_URL", "https://izsu.gov.tr/api/proxy"),
        izsu_past_cache_ttl_seconds=_env_int("IZMIR_MCP_IZSU_PAST_CACHE_TTL_SECONDS", 7 * 86_400),
        iztek_positions_cache_ttl_seconds=_env_int("IZMIR_MCP_IZTEK_POSITIONS_CACHE_TTL_SECONDS", 15),
        cbs_max_pages=_env_int("IZMIR_MCP_CBS_MAX_PAGES", 10),
        cbs_cache_ttl_seconds=_env_int("IZMIR_MCP_CBS_CACHE_TTL_SECONDS", 86_400),
        events_cache_ttl_seconds=_env_int("IZMIR_MCP_EVENTS_CACHE_TTL_SECONDS", 3_600),
        hal_cache_ttl_seconds=_env_int("IZMIR_MCP_HAL_CACHE_TTL_SECONDS", 7 * 86_400),
        pharmacies_all_cache_ttl_seconds=_env_int("IZMIR_MCP_PHARMACIES_ALL_CACHE_TTL_SECONDS", 86_400),
        eshot_stops_resource_id=os.getenv("IZMIR_MCP_ESHOT_STOPS_RESOURCE_ID", "0c791266-a2e4-4f14-82b8-9a9b102fbf94"),
        eshot_routes_resource_id=os.getenv(
            "IZMIR_MCP_ESHOT_ROUTES_RESOURCE_ID", "bd6c84f8-49ba-4cf4-81f8-81a0fbb5caa3"
        ),
        eshot_cache_ttl_seconds=_env_int("IZMIR_MCP_ESHOT_CACHE_TTL_SECONDS", 86_400),
        eshot_stale_if_error_seconds=_env_int("IZMIR_MCP_ESHOT_STALE_IF_ERROR_SECONDS", 604_800),
        iztek_base_url=os.getenv("IZMIR_MCP_IZTEK_BASE_URL", "https://openapi.izmir.bel.tr/api/iztek"),
        iztek_cache_ttl_seconds=_env_int("IZMIR_MCP_IZTEK_CACHE_TTL_SECONDS", 20),
        iztek_min_request_interval_seconds=_env_float("IZMIR_MCP_IZTEK_MIN_REQUEST_INTERVAL_SECONDS", 0.5),
        eshot_gtfs_url=os.getenv(
            "IZMIR_MCP_ESHOT_GTFS_URL",
            "https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip",
        ),
        eshot_gtfs_max_bytes=_env_int("IZMIR_MCP_ESHOT_GTFS_MAX_BYTES", 64 * 1024 * 1024),
        eshot_gtfs_member_max_bytes=_env_int("IZMIR_MCP_ESHOT_GTFS_MEMBER_MAX_BYTES", 8 * 1024 * 1024),
        eshot_gtfs_stop_times_max_bytes=_env_int("IZMIR_MCP_ESHOT_GTFS_STOP_TIMES_MAX_BYTES", 128 * 1024 * 1024),
        eshot_gtfs_max_rows=_env_int("IZMIR_MCP_ESHOT_GTFS_MAX_ROWS", 2_500_000),
        eshot_gtfs_cache_ttl_seconds=_env_int("IZMIR_MCP_ESHOT_GTFS_CACHE_TTL_SECONDS", 86_400),
        eshot_gtfs_stale_if_error_seconds=_env_int("IZMIR_MCP_ESHOT_GTFS_STALE_IF_ERROR_SECONDS", 604_800),
        eshot_notices_csv_url=os.getenv(
            "IZMIR_MCP_ESHOT_NOTICES_CSV_URL",
            "https://openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv",
        ),
        eshot_notices_cache_ttl_seconds=_env_int("IZMIR_MCP_ESHOT_NOTICES_CACHE_TTL_SECONDS", 1_800),
        city_layer_cache_ttl_seconds=_env_int("IZMIR_MCP_CITY_LAYER_CACHE_TTL_SECONDS", 86_400),
        city_layer_stale_if_error_seconds=_env_int("IZMIR_MCP_CITY_LAYER_STALE_IF_ERROR_SECONDS", 604_800),
        traffic_stale_after_hours=_env_int("IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS", 72),
        database_path=os.getenv("IZMIR_MCP_DATABASE_PATH", ".data/izmir_mcp.sqlite3"),
        gtfs_database_path=os.getenv("IZMIR_MCP_GTFS_DATABASE_PATH", ".data/izmir_mcp_gtfs.sqlite3"),
        client_max_body_bytes=_env_int("IZMIR_MCP_CLIENT_MAX_BODY_BYTES", 1_000_000),
        client_rate_limit_capacity=_env_int("IZMIR_MCP_CLIENT_RATE_LIMIT_CAPACITY", 60),
        client_rate_limit_refill_per_second=_env_float("IZMIR_MCP_CLIENT_RATE_LIMIT_REFILL_PER_SECOND", 1.0),
        client_rate_limit_max_clients=_env_int("IZMIR_MCP_CLIENT_RATE_LIMIT_MAX_CLIENTS", 10_000),
        client_max_concurrent_requests=_env_int("IZMIR_MCP_CLIENT_MAX_CONCURRENT_REQUESTS", 32),
        mcp_api_keys=_env_list("IZMIR_MCP_API_KEYS"),
        api_key_daily_quota=_env_int("IZMIR_MCP_API_KEY_DAILY_QUOTA", 0),
        mcp_cors_allowed_origins=_env_list("IZMIR_MCP_CORS_ALLOWED_ORIGINS"),
        access_log_enabled=_env_bool("IZMIR_MCP_ACCESS_LOG_ENABLED", True),
        mcp_allowed_hosts=_env_list("IZMIR_MCP_ALLOWED_HOSTS"),
        mcp_require_auth=_env_bool("IZMIR_MCP_REQUIRE_AUTH", False),
        http_total_deadline_seconds=_env_float("IZMIR_MCP_HTTP_TOTAL_DEADLINE_SECONDS", 0.0),
        source_cache_max_entries=_env_int("IZMIR_MCP_SOURCE_CACHE_MAX_ENTRIES", 512),
        event_loop_watchdog_seconds=_env_float("IZMIR_MCP_EVENT_LOOP_WATCHDOG_SECONDS", 0.0),
        source_rate_capacity=_env_int("IZMIR_MCP_SOURCE_RATE_CAPACITY", 10),
        source_rate_refill_per_second=_env_float("IZMIR_MCP_SOURCE_RATE_REFILL_PER_SECOND", 2.0),
        source_rate_max_wait_seconds=_env_float("IZMIR_MCP_SOURCE_RATE_MAX_WAIT_SECONDS", 2.0),
    )
