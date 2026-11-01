# Configuration

This document is task-oriented: it explains which environment variables to set
for which scenario. The full list of variables and their defaults is in
[Deployment](deployment.md#environment-variables), locked against
`app/core/settings.py` by `tests/test_docs.py`. Example file: `.env.example`.

## Profile 1: local development (default)

Nothing needs to be set. The server binds to `127.0.0.1:8000`, authentication
is off, the Host header is not validated (a warning is logged once), and
browser origins are rejected.

## Profile 2: local container

`docker compose up --build` uses `docker-compose.yml`: the port is published
only on loopback, the root file system is read-only, all Linux capabilities
are dropped, and `IZMIR_MCP_ALLOWED_HOSTS=localhost,127.0.0.1` and
`IZMIR_MCP_EVENT_LOOP_WATCHDOG_SECONDS=60` are set. The GTFS store is built on
first start in the `/data` volume; CI skips it with
`IZMIR_MCP_SKIP_GTFS_BUILD=1`.

## Profile 3: public (internet-facing) deployment

Before binding to a public address, set at least the following:

| Variable | Why |
|---|---|
| `IZMIR_MCP_HOST=0.0.0.0` | Listen inside a container/PaaS. |
| `IZMIR_MCP_API_KEYS` | Comma-separated keys; see [API access](api-access.md). |
| `IZMIR_MCP_REQUIRE_AUTH=true` | The server refuses to start without keys (fail closed). |
| `IZMIR_MCP_ALLOWED_HOSTS` | Your public domain; returns `421` against DNS rebinding. |
| `IZMIR_MCP_CORS_ALLOWED_ORIGINS` | Only if there is a browser client; see [CORS](browser-cors.md). |
| `IZMIR_MCP_API_KEY_DAILY_QUOTA` | Daily call cap per key. |
| `IZMIR_MCP_EVENT_LOOP_WATCHDOG_SECONDS` | Restarts the process when the event loop hangs. |

`IZMIR_MCP_REQUIRE_AUTH` and `IZMIR_MCP_ALLOWED_HOSTS` are off by default for
backward compatibility; enabling them for a public deployment is the
operator's job.

## Upstream resilience

- `IZMIR_MCP_REQUEST_TIMEOUT_SECONDS`, `IZMIR_MCP_REQUEST_ATTEMPTS`: per-request
  timeout and attempt count.
- `IZMIR_MCP_HTTP_TOTAL_DEADLINE_SECONDS`: total time including retries; `0`
  disables it.
- `IZMIR_MCP_RESPONSE_MAX_BYTES`: cap on the streamed response body.
- `IZMIR_MCP_SOURCE_RATE_*`: token bucket per upstream.
- `*_STALE_IF_ERROR_SECONDS`: how long the last good response is served as
  `stale` while a source is down.
- `IZMIR_MCP_SOURCE_CACHE_MAX_ENTRIES`: in-memory cache cap.

## Test only

`IZMIR_MCP_ALLOW_PRIVATE_UPSTREAMS=1` allows private/loopback upstreams so
local test servers can be reached. Never set it in production; see
[Security](security.md). Live tests are enabled with `IZMIR_LIVE=1`.
