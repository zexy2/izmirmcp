# Deployment

This document derives how to run the HTTP/stdio server, every environment
variable and the real behaviour of the security layers from the code
(`app/core/settings.py`, `app/main.py`, `app/core/*.py`, `Dockerfile`,
`docker/entrypoint.sh`). Defaults match `get_settings()` exactly. For
task-oriented profiles (local, container, public) see
[configuration.md](configuration.md).

## Ways to run

| Transport | Command | Endpoint |
|---|---|---|
| Streamable HTTP | `python -m app.main` or `izmir-mcp` | `http://127.0.0.1:8000/mcp/` |
| stdio | `python -m app.stdio` or `izmir-mcp-stdio` | stdin/stdout |
| Container (HTTP) | `docker run -p 8000:8000 -v izmir-data:/data izmir-mcp` | `http://127.0.0.1:8000/mcp/` |
| Container (stdio) | `docker run --rm -i izmir-mcp python -m app.stdio` | stdin/stdout |

`app/main.py` starts uvicorn with `proxy_headers=True`,
`forwarded_allow_ips="127.0.0.1"`. `/mcp` (without the trailing slash) is
redirected to `/mcp/` with a `308`. Transport details are in
[mcp-interface.md](mcp-interface.md).

Local setup:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m app.main
```

## Environment variables

Values are read under `IZMIR_MCP_*` names. Empty or unparseable values fall
back to the default. List variables are comma-separated (empty items are
dropped).

### Server and limits

| Variable | Default | Description |
|---|---|---|
| `IZMIR_MCP_HOST` | `127.0.0.1` | Bind address. |
| `IZMIR_MCP_PORT` | `8000` | HTTP port. |
| `IZMIR_MCP_DEFAULT_LIMIT` | `10` | Record count used when no `limit` is given. |
| `IZMIR_MCP_MAX_LIMIT` | `50` | Highest allowed `limit`. |
| `IZMIR_MCP_MAX_RADIUS_M` | `5000` | Upper bound of `radius_m`. |

The matching `Settings` fields are `default_limit`, `max_limit` and
`max_radius_m`, with defaults `10`, `50` and `5000` respectively. These values
are published in the `limits` block of the `/status` response together with
`max_body_bytes`.

### Upstream request budget

| Variable | Default | Description |
|---|---|---|
| `IZMIR_MCP_REQUEST_TIMEOUT_SECONDS` | `15.0` | Source request timeout. |
| `IZMIR_MCP_REQUEST_ATTEMPTS` | `2` | Attempt count (on 5xx/connection errors). |
| `IZMIR_MCP_RESPONSE_MAX_BYTES` | `2000000` | Source response byte cap. |

### Source URLs and caching

| Variable | Default |
|---|---|
| `IZMIR_MCP_CKAN_BASE_URL` | `https://acikveri.bizizmir.com/api/3/action` |
| `IZMIR_MCP_OPENAPI_BASE_URL` | `https://openapi.izmir.bel.tr/api` |
| `IZMIR_MCP_IZSU_DAMS_CSV_URL` | `https://openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv` |
| `IZMIR_MCP_IZSU_API_BASE_URL` | `https://izsu.gov.tr/api/proxy` |
| `IZMIR_MCP_IZSU_PAST_CACHE_TTL_SECONDS` | `604800` |
| `IZMIR_MCP_IZTEK_POSITIONS_CACHE_TTL_SECONDS` | `15` |
| `IZMIR_MCP_CBS_MAX_PAGES` | `10` |
| `IZMIR_MCP_CBS_CACHE_TTL_SECONDS` | `86400` |
| `IZMIR_MCP_EVENTS_CACHE_TTL_SECONDS` | `3600` |
| `IZMIR_MCP_HAL_CACHE_TTL_SECONDS` | `604800` |
| `IZMIR_MCP_PHARMACIES_ALL_CACHE_TTL_SECONDS` | `86400` |
| `IZMIR_MCP_IZTEK_BASE_URL` | `https://openapi.izmir.bel.tr/api/iztek` |
| `IZMIR_MCP_ESHOT_GTFS_URL` | `https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip` |
| `IZMIR_MCP_ESHOT_NOTICES_CSV_URL` | `https://openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv` |
| `IZMIR_MCP_ESHOT_STOPS_RESOURCE_ID` | `0c791266-a2e4-4f14-82b8-9a9b102fbf94` |
| `IZMIR_MCP_ESHOT_ROUTES_RESOURCE_ID` | `bd6c84f8-49ba-4cf4-81f8-81a0fbb5caa3` |
| `IZMIR_MCP_IZTEK_CACHE_TTL_SECONDS` | `20` |
| `IZMIR_MCP_IZTEK_STALE_IF_ERROR_SECONDS` | `120` |
| `IZMIR_MCP_IZTEK_POSITIONS_STALE_IF_ERROR_SECONDS` | `90` |
| `IZMIR_MCP_OPENAPI_STALE_IF_ERROR_SECONDS` | `3600` |
| `IZMIR_MCP_OPENAPI_TIMEOUT_SECONDS` | `10` |
| `IZMIR_MCP_LIVE_VEHICLE_TIMEOUT_SECONDS` | `5` |
| `IZMIR_MCP_IZTEK_MIN_REQUEST_INTERVAL_SECONDS` | `0.5` |
| `IZMIR_MCP_ESHOT_CACHE_TTL_SECONDS` | `86400` |
| `IZMIR_MCP_ESHOT_STALE_IF_ERROR_SECONDS` | `604800` |
| `IZMIR_MCP_ESHOT_NOTICES_CACHE_TTL_SECONDS` | `1800` |
| `IZMIR_MCP_CITY_LAYER_CACHE_TTL_SECONDS` | `86400` |
| `IZMIR_MCP_CITY_LAYER_STALE_IF_ERROR_SECONDS` | `604800` |
| `IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS` | `72` |

The CKAN TTLs (`catalog` 21600 s, `resource` 300 s), the OpenAPI TTL (120 s /
900 s stale) and the İZSU TTL (3600 s / 86400 s stale) are `Settings` fields
but are not exposed as environment variables; changing them requires code.

### GTFS store

| Variable | Default | Description |
|---|---|---|
| `IZMIR_MCP_DATABASE_PATH` | `.data/izmir_mcp.sqlite3` | Shared SQLite path for the quota and the spatial index (`/data/...` in the container). |
| `IZMIR_MCP_GTFS_DATABASE_PATH` | `.data/izmir_mcp_gtfs.sqlite3` | SQLite path of the timetable store; kept separate because a rebuild writes 2.1M rows. |
| `IZMIR_MCP_ESHOT_GTFS_MAX_BYTES` | `67108864` | ZIP cap (64 MB). |
| `IZMIR_MCP_ESHOT_GTFS_MEMBER_MAX_BYTES` | `8388608` | Member file cap (8 MB). |
| `IZMIR_MCP_ESHOT_GTFS_STOP_TIMES_MAX_BYTES` | `134217728` | `stop_times.txt` cap (128 MB). |
| `IZMIR_MCP_ESHOT_GTFS_MAX_ROWS` | `2500000` | Row cap. |
| `IZMIR_MCP_ESHOT_GTFS_CACHE_TTL_SECONDS` | `86400` | Rebuild threshold. |
| `IZMIR_MCP_ESHOT_GTFS_STALE_IF_ERROR_SECONDS` | `604800` | How long the old store is used when it cannot be refreshed. |

See [gtfs-schedule.md](gtfs-schedule.md) for the build and freshness rules.

### Local SQL snapshot

`izmir_datastore_query` only downloads explicitly allowed resources; the list
is **empty** by default. Every bound is checked against safe ranges built into
the code; the process does not start when a setting is out of range. See
[datastore-sql.md](datastore-sql.md).

| Variable | Default | Description |
|---|---|---|
| `IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS` | empty | Comma-separated, at most 100 DataStore resource ids. |
| `IZMIR_MCP_CKAN_SQL_MAX_ROWS` | `50000` | Row cap for a full copy (1–50000). |
| `IZMIR_MCP_CKAN_SQL_MAX_BYTES` | `20971520` | Total wire byte cap for a copy (1 KiB–20 MiB). |
| `IZMIR_MCP_CKAN_SQL_PAGE_SIZE` | `5000` | Rows per page (1–5000). |
| `IZMIR_MCP_CKAN_SQL_SNAPSHOT_TTL_SECONDS` | `900` | Copy cache (1–3600 s). |
| `IZMIR_MCP_CKAN_SQL_LOAD_TIMEOUT_SECONDS` | `30.0` | Full copy timeout (0.01–60 s). |
| `IZMIR_MCP_CKAN_SQL_QUERY_TIMEOUT_SECONDS` | `0.5` | SELECT execution budget (0.001–2 s). |

### HTTP security

| Variable | Default | Description |
|---|---|---|
| `IZMIR_MCP_CLIENT_MAX_BODY_BYTES` | `1000000` | `/mcp` body cap; `413` when exceeded. |
| `IZMIR_MCP_CLIENT_RATE_LIMIT_CAPACITY` | `60` | Token bucket per client. |
| `IZMIR_MCP_CLIENT_RATE_LIMIT_REFILL_PER_SECOND` | `1.0` | Token refill per second. |
| `IZMIR_MCP_CLIENT_RATE_LIMIT_MAX_CLIENTS` | `10000` | Cap on tracked clients (LRU pruning). |
| `IZMIR_MCP_CLIENT_MAX_CONCURRENT_REQUESTS` | `32` | Concurrent `/mcp` requests. |
| `IZMIR_MCP_API_KEYS` | empty | Bearer keys; authentication is off when empty. |
| `IZMIR_MCP_API_KEY_DAILY_QUOTA` | `0` | Daily request quota per key; `0` is unlimited. Persistent (SQLite). |
| `IZMIR_MCP_CORS_ALLOWED_ORIGINS` | empty | Browser Origin allowlist. |
| `IZMIR_MCP_ACCESS_LOG_ENABLED` | `true` | Structured access log. |
| `IZMIR_MCP_ALLOWED_HOSTS` | empty | Accepted `Host` headers (comma-separated). When empty, nothing is validated and only a warning is logged; when set, other hosts get `421 misdirected_request`. |
| `IZMIR_MCP_REQUIRE_AUTH` | `false` | When `true` and `IZMIR_MCP_API_KEYS` is empty, the server refuses to start (fail closed). |
| `IZMIR_MCP_HTTP_TOTAL_DEADLINE_SECONDS` | `0` | Total time limit of an upstream request; `0` = 2 × the request timeout. |
| `IZMIR_MCP_SOURCE_CACHE_MAX_ENTRIES` | `512` | Maximum number of source cache entries. |
| `IZMIR_MCP_EVENT_LOOP_WATCHDOG_SECONDS` | `0` | Event loop hang watchdog threshold; `0` disables it. |
| `IZMIR_MCP_SOURCE_RATE_CAPACITY` | `10` | Request bucket capacity per source. |
| `IZMIR_MCP_SOURCE_RATE_REFILL_PER_SECOND` | `2.0` | Source bucket refill rate. |
| `IZMIR_MCP_SOURCE_RATE_MAX_WAIT_SECONDS` | `2.0` | Longest wait for the source bucket. |

Note: the code takes the MCP SDK's own body limit for
`IZMIR_MCP_MCP_MAX_BODY_BYTES` from the `mcp_max_body_bytes` field (default
1 MB); it is not exposed separately through the environment and should be kept
in line with `CLIENT_MAX_BODY_BYTES`.

## Authentication

Off when `IZMIR_MCP_API_KEYS` is empty. When set, `/status` and `/mcp`/`/mcp/*`
require `Authorization: Bearer <key>`; missing/wrong → `401` +
`WWW-Authenticate: Bearer realm="izmir-mcp"`. Keys are compared by SHA-256
digest (`hmac.compare_digest`) and are not logged. Validation: 1–100 unique
keys, 32–256 characters, `[A-Za-z0-9._~-]`. Otherwise the process does not
start (`ValueError`). `/healthz` and `/readyz` are **always** open. Key
generation, rotation and quotas: [api-access.md](api-access.md).

## Origin allowlist and CORS

When a browser sends `Origin`, the value must be in the allowlist; otherwise
`403` `origin_not_allowed`. CLI/MCP clients that send no `Origin` are
unaffected. While the allowlist is empty, every browser Origin is rejected
(fail closed).

Validation: at most 32 unique origins; `https` required (`http` only for
`localhost`, `127.0.0.1`, `[::1]`); wildcards, credentials, paths, queries and
fragments are forbidden; lowercase host. CORS response headers: allowed
methods `GET, POST, DELETE, OPTIONS`; exposed headers `Mcp-Session-Id`,
`Mcp-Protocol-Version`, `WWW-Authenticate`, `Retry-After`; `max-age=600`.
Preflight `OPTIONS` → `204`. Details: [browser-cors.md](browser-cors.md).

## Abuse protection layers

Order (inside out): abuse guard → auth → access log → CORS. Overruns return an
**HTTP code** + `{"ok": false, "error_code", "summary"}`, not an envelope:

| Case | Code | Header |
|---|---|---|
| Body cap | `413 payload_too_large` | — |
| Rate limit | `429 rate_limited` | `Retry-After` |
| Concurrency | `503 server_busy` | `Retry-After: 1` |
| Authentication | `401 unauthorized` | `WWW-Authenticate` |
| Origin | `403 origin_not_allowed` | `Vary: Origin` |

- The rate limit and counters are **in-process and volatile**. In a
  multi-worker deployment every worker applies its own budget; put a reverse
  proxy in front for a global limit.
- The client identity is the direct connection address. `X-Forwarded-For` is
  honoured **only** while the server is bound to loopback and the request
  carries a **single** header with a **single bare value** (no commas or
  whitespace). Lists, repeated headers or empty values are not trusted; the
  socket peer is used. So one connection cannot mint a fake identity per
  request to bypass the rate limit (`tests/test_http_security.py`).
- Security tests: `tests/test_http_security.py` covers authentication bypass
  variants (scheme, length, duplicate header, path encoding), origin bypass
  (scheme, port, subdomain, duplicate header, `null`, `*`), the body cap
  (Content-Length, chunked, fake length) and log hygiene.
- The access log writes method, path, status and duration; query string, body,
  headers and API key are **never** logged. Details:
  [monitoring.md](monitoring.md).
- This layer is not an authorization server; it compares static keys and has
  no OAuth/rotating keys.

## Container image

The `Dockerfile` is a two-stage build (`builder` + runtime) on a digest-pinned
`python:3.11-slim`, with the non-root `izmir` user (uid 10001) and a `/data`
volume. `PYTHONUNBUFFERED=1`, `IZMIR_MCP_HOST=0.0.0.0`, `IZMIR_MCP_PORT=8000`,
`IZMIR_MCP_DATABASE_PATH=/data/izmir_mcp.sqlite3` and
`IZMIR_MCP_GTFS_DATABASE_PATH=/data/izmir_mcp_gtfs.sqlite3` are fixed at build
time. `HEALTHCHECK` probes `/healthz` (it does not measure source health).

`.data/`, `.venv/`, `tests/`, `scripts/` and `docs/` stay out of the image
(`.dockerignore`); `app/data/places.json` is included.

`docker/entrypoint.sh` pre-builds the GTFS store at startup
(`python -m app.storage.gtfs_schedule`). If that fails, the container **does
not stop**: timetable tools honestly return `source_unavailable` and the rest
keep working. Skip the build with `IZMIR_MCP_SKIP_GTFS_BUILD=1` (read only by
the container entrypoint, not by the Python code).

Building the GTFS store by hand:

```bash
python -m app.storage.gtfs_schedule --database .data/izmir_mcp_gtfs.sqlite3
```

Success returns `0`, any error `2`; nothing is written for an invalid archive.

## CI

`.github/workflows/ci.yml` jobs (actions pinned to commit SHAs,
`permissions: contents: read`):

- `lint` — `ruff check` (blocking) and `mypy` (report-only for now).
- `test` — Python 3.11/3.12/3.13 matrix: `pytest` (the 36-tool surface locked
  by `tests/test_tool_compatibility.py`), the offline protocol smoke
  (`scripts/smoke_mcp.py`), and a server start with `/healthz`+`/readyz`+`/status`
  probes.
- `conformance` — the official MCP conformance subset; reports are uploaded as
  artifacts.
- `docker` — image build, `/healthz` inside the container
  (`IZMIR_MCP_SKIP_GTFS_BUILD=1`), Trivy scan (HIGH/CRITICAL) and syft SBOM.
- `audit` — `pip-audit` over `requirements.lock`.
- `live` — `IZMIR_LIVE=1` live tests, UAT and smoke; non-blocking.

`release.yml` builds the package from a `v*` tag, uploads it to PyPI with
trusted publishing (OIDC) when enabled, pushes the image to GHCR and publishes
`server.json` to the MCP registry (see [registry.md](registry.md)).
`uptime.yml` probes the endpoint in the `UPTIME_URL` repository variable every
10 minutes with `scripts/uptime_check.py`; on failure it opens a single
incident issue and closes it once healthy. Details:
[Development](development.md).

## Running CI locally

You can run the workflow locally one-to-one without GitHub Actions billing
(`act` uses a real runner image on Docker):

```bash
brew install act
docker pull --platform linux/arm64 catthehacker/ubuntu:act-latest
act -j test --pull=false       # pytest + protocol smoke + live smoke + server probe
act -j docker --pull=false     # image build + container healthz
```

`~/.actrc` (required for arm64):

```text
--container-architecture=linux/arm64
-P=ubuntu-latest=catthehacker/ubuntu:act-latest
```

Notes:

- By default `act` asks for an interactive image choice; `~/.actrc` turns that
  off.
- The runner image is ~2.3 GB; the first `docker pull` takes long and may tie
  up Docker Desktop for a while.
- The live smoke step calls third-party APIs; it is `continue-on-error` inside
  `act` too, so it does not block.
- This method ran successfully for both jobs on 2026-10-28.
