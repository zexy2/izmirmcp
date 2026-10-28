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
    max_nearby_types: int = 7

    ckan_base_url: str = "https://acikveri.bizizmir.com/api/3/action"
    ckan_catalog_cache_ttl_seconds: int = 21_600
    ckan_resource_cache_ttl_seconds: int = 300

    openapi_base_url: str = "https://openapi.izmir.bel.tr/api"
    openapi_cache_ttl_seconds: int = 120
    openapi_stale_if_error_seconds: int = 900

    izsu_dams_csv_url: str = (
        "https://openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv"
    )
    izsu_cache_ttl_seconds: int = 3_600
    izsu_stale_if_error_seconds: int = 86_400

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

    eshot_notices_csv_url: str = (
        "https://openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv"
    )
    eshot_notices_cache_ttl_seconds: int = 1_800

    city_layer_cache_ttl_seconds: int = 86_400
    city_layer_stale_if_error_seconds: int = 604_800

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
        ckan_base_url=os.getenv(
            "IZMIR_MCP_CKAN_BASE_URL", "https://acikveri.bizizmir.com/api/3/action"
        ),
        openapi_base_url=os.getenv(
            "IZMIR_MCP_OPENAPI_BASE_URL", "https://openapi.izmir.bel.tr/api"
        ),
        izsu_dams_csv_url=os.getenv(
            "IZMIR_MCP_IZSU_DAMS_CSV_URL",
            "https://openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv",
        ),
        eshot_stops_resource_id=os.getenv(
            "IZMIR_MCP_ESHOT_STOPS_RESOURCE_ID", "0c791266-a2e4-4f14-82b8-9a9b102fbf94"
        ),
        eshot_routes_resource_id=os.getenv(
            "IZMIR_MCP_ESHOT_ROUTES_RESOURCE_ID", "bd6c84f8-49ba-4cf4-81f8-81a0fbb5caa3"
        ),
        eshot_cache_ttl_seconds=_env_int("IZMIR_MCP_ESHOT_CACHE_TTL_SECONDS", 86_400),
        eshot_stale_if_error_seconds=_env_int(
            "IZMIR_MCP_ESHOT_STALE_IF_ERROR_SECONDS", 604_800
        ),
        iztek_base_url=os.getenv(
            "IZMIR_MCP_IZTEK_BASE_URL", "https://openapi.izmir.bel.tr/api/iztek"
        ),
        iztek_cache_ttl_seconds=_env_int("IZMIR_MCP_IZTEK_CACHE_TTL_SECONDS", 20),
        iztek_min_request_interval_seconds=_env_float(
            "IZMIR_MCP_IZTEK_MIN_REQUEST_INTERVAL_SECONDS", 0.5
        ),
        eshot_gtfs_url=os.getenv(
            "IZMIR_MCP_ESHOT_GTFS_URL",
            "https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip",
        ),
        eshot_gtfs_max_bytes=_env_int(
            "IZMIR_MCP_ESHOT_GTFS_MAX_BYTES", 64 * 1024 * 1024
        ),
        eshot_gtfs_member_max_bytes=_env_int(
            "IZMIR_MCP_ESHOT_GTFS_MEMBER_MAX_BYTES", 8 * 1024 * 1024
        ),
        eshot_gtfs_stop_times_max_bytes=_env_int(
            "IZMIR_MCP_ESHOT_GTFS_STOP_TIMES_MAX_BYTES", 128 * 1024 * 1024
        ),
        eshot_gtfs_max_rows=_env_int("IZMIR_MCP_ESHOT_GTFS_MAX_ROWS", 2_500_000),
        eshot_gtfs_cache_ttl_seconds=_env_int(
            "IZMIR_MCP_ESHOT_GTFS_CACHE_TTL_SECONDS", 86_400
        ),
        eshot_gtfs_stale_if_error_seconds=_env_int(
            "IZMIR_MCP_ESHOT_GTFS_STALE_IF_ERROR_SECONDS", 604_800
        ),
        eshot_notices_csv_url=os.getenv(
            "IZMIR_MCP_ESHOT_NOTICES_CSV_URL",
            "https://openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv",
        ),
        eshot_notices_cache_ttl_seconds=_env_int(
            "IZMIR_MCP_ESHOT_NOTICES_CACHE_TTL_SECONDS", 1_800
        ),
        city_layer_cache_ttl_seconds=_env_int(
            "IZMIR_MCP_CITY_LAYER_CACHE_TTL_SECONDS", 86_400
        ),
        city_layer_stale_if_error_seconds=_env_int(
            "IZMIR_MCP_CITY_LAYER_STALE_IF_ERROR_SECONDS", 604_800
        ),
        database_path=os.getenv(
            "IZMIR_MCP_DATABASE_PATH", ".data/izmir_mcp.sqlite3"
        ),
        client_max_body_bytes=_env_int("IZMIR_MCP_CLIENT_MAX_BODY_BYTES", 1_000_000),
        client_rate_limit_capacity=_env_int("IZMIR_MCP_CLIENT_RATE_LIMIT_CAPACITY", 60),
        client_rate_limit_refill_per_second=_env_float(
            "IZMIR_MCP_CLIENT_RATE_LIMIT_REFILL_PER_SECOND", 1.0
        ),
        client_rate_limit_max_clients=_env_int("IZMIR_MCP_CLIENT_RATE_LIMIT_MAX_CLIENTS", 10_000),
        client_max_concurrent_requests=_env_int(
            "IZMIR_MCP_CLIENT_MAX_CONCURRENT_REQUESTS", 32
        ),
        mcp_api_keys=_env_list("IZMIR_MCP_API_KEYS"),
        api_key_daily_quota=_env_int("IZMIR_MCP_API_KEY_DAILY_QUOTA", 0),
        mcp_cors_allowed_origins=_env_list("IZMIR_MCP_CORS_ALLOWED_ORIGINS"),
        access_log_enabled=_env_bool("IZMIR_MCP_ACCESS_LOG_ENABLED", True),
    )
