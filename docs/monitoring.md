# Monitoring

This document derives the observability contract of the HTTP surface from the
code: `app/main.py` (endpoints), `app/core/http_logging.py` (logs),
`app/core/rate_limit.py` (telemetry) and `app/core/abuse_guard.py` (rejection
codes).

Core principle: **no health endpoint probes third-party sources.** Source
health is only read from the `freshness`/`warnings` fields of tool responses.
This keeps a probe storm from tripping the rate limits of sources such as
İZTEK/CKAN.

## Endpoints

| Endpoint | Method | Purpose | Auth | Status code |
|---|---|---|---|---|
| `/healthz` | GET | Is the process up? | None | Always `200` |
| `/readyz` | GET | Local readiness (is the tool surface built?) | None | Ready `200`, not ready `503` |
| `/status` | GET | Tool list, limits, rate/concurrency telemetry | Required when `API_KEYS` is set | `200` / `401` |
| `/mcp` | GET/POST/… | `308` redirect → `/mcp/` | Required when `API_KEYS` is set | `308` |
| `/mcp/` | POST | Streamable HTTP MCP | Required when `API_KEYS` is set | `200` / guard codes |

### `/healthz`

```json
{"ok": true, "service": "izmir-mcp"}
```

Process liveness only. The Docker `HEALTHCHECK` probes this.

### `/readyz`

```json
{
  "ok": true,
  "service": "izmir-mcp",
  "ready": true,
  "upstream_health": "not_checked",
  "checks": {"tool_surface": "ok", "tool_count": 36}
}
```

`upstream_health` is **always** `"not_checked"`. If the tool surface cannot be
built, `checks.tool_surface="error:<Type>"` or `"empty"`, `ready=false`, HTTP
`503`. The MCP session manager must be running during the lifespan; otherwise
the probe does not answer.

### `/status`

```json
{
  "service": "izmir-mcp",
  "tools": ["izmir_health", "…"],
  "tool_count": 36,
  "limits": {"default_limit": 10, "max_limit": 50, "max_radius_m": 5000, "max_body_bytes": 1000000},
  "rate_limit": {"tracked_clients": 0, "capacity": 60, "refill_per_second": 1.0, "max_clients": 10000, "allowed": 0, "rejected": 0},
  "concurrency": {"current": 0, "max_concurrent": 32, "rejected": 0},
  "auth": "disabled",
  "upstream_health": "not_checked"
}
```

The `auth` value `"enabled"`/`"disabled"` reflects whether
`IZMIR_MCP_API_KEYS` is set.

## Guard rejections

The guard layers on `/mcp` return an HTTP code + a minimal body. Structurally:

```json
{"ok": false, "error_code": "rate_limited", "summary": "Too many requests from this client."}
```

| `error_code` | HTTP | Header |
|---|---|---|
| `payload_too_large` | 413 | — |
| `rate_limited` | 429 | `Retry-After: <s>` |
| `server_busy` | 503 | `Retry-After: 1` |
| `unauthorized` | 401 | `WWW-Authenticate: Bearer realm="izmir-mcp"` |
| `origin_not_allowed` | 403 | `Vary: Origin` |

These rejections carry no envelope (see
[response-contract.md](response-contract.md)). Alert thresholds: if
`rate_limit.rejected` and `concurrency.rejected` keep growing, add a reverse
proxy or more capacity. Counters are per process; in a multi-worker
deployment read them per worker.

## Access log

The `izmir_mcp.access` logger writes **one line of JSON** per HTTP request while
`IZMIR_MCP_ACCESS_LOG_ENABLED=true`:

```json
{"event": "http_request", "method": "POST", "path": "/mcp/", "status": 200, "duration_ms": 42.7}
```

Fields:

| Field | Meaning |
|---|---|
| `event` | Always `http_request`. |
| `method` | HTTP method. |
| `path` | Path (without the query string). |
| `status` | Response status code (`500` when there is no response). |
| `duration_ms` | Duration in milliseconds (1 decimal). |

**Not logged:** query string, body, headers and API key. This keeps shared logs
from leaking caller content or credentials. Turn it off entirely with
`IZMIR_MCP_ACCESS_LOG_ENABLED=false`. See [privacy.md](privacy.md).

## Probe recommendations

- Liveness: `GET /healthz` every 15–30 s.
- Readiness: `GET /readyz` at startup and after deployments; `503` stops traffic
  routing.
- Alerts: `rate_limit.rejected`, `concurrency.rejected` and an unexpected
  `tool_count` in `/status` (an unexpected surface change).
- Track source health not through probes but through `freshness.status` and
  `warnings` of sample tool calls. Live smoke test:
  `python scripts/smoke_live.py` (uses the network, non-blocking in CI).
- Public endpoint uptime: `scripts/uptime_check.py`, run by `uptime.yml` (see
  [development.md](development.md#scripts)).

## Log/routing notes

- `X-Forwarded-For` is only honoured while the server is bound to loopback;
  otherwise it is ignored, so a spoofed XFF from outside cannot change the
  client identity.
- uvicorn starts with `proxy_headers=True`, `forwarded_allow_ips="127.0.0.1"`;
  the reverse proxy must connect over localhost.
- Rate/concurrency counters are volatile and reset on restart. There is no
  persistent metrics backend.

## Tool telemetry

The `tools_telemetry` field in `/status` publishes the following per tool:

```json
{"izmir_nearby": {"calls": 12, "errors": 1,
  "error_codes": {"validation_error": 1},
  "truncated": 0, "stale": 0,
  "mean_ms": 18.4, "p50_ms": 12.0, "p95_ms": 61.2, "max_ms": 88.0}}
```

Rules:

- **Input and response text are never stored.** Only counts, codes and
  durations.
- Latency samples are capped at **256** per tool; counters grow without bound.
- Records are also created for failed calls (even when the block raises).
- Per process: reset on restart.
- At most 64 tools are tracked; beyond that the least-called one is dropped.

`p95` is based on the last 256 samples; under low traffic it may equal a single
sample.

## Readiness details

`/readyz` runs three local checks and **hides the detail text** (the endpoint
requires no authentication):

| Check | Meaning | Affects `ready` |
|---|---|---|
| `tool_surface` | The tool surface is not empty | Yes |
| `timetable_store` | The GTFS store is readable | Only when `broken`; `absent` is normal |
| `database_directory` | The SQLite directory is writable | Yes |

`timetable_store=absent` **counts as ready**: the store is built on the first
departures query. `broken` (a corrupt file) is not ready, because the lazy build
does not fix it.

`/status` gives the same information with `detail` and without paths (it
requires authentication).

## JSON-RPC gate

A malformed envelope is rejected before it reaches the SDK:

| Case | Code | HTTP |
|---|---|---|
| Unparseable body | `-32700` | 400 |
| `jsonrpc` ≠ `"2.0"` | `-32600` | 400 |
| Missing/invalid `method` | `-32600` | 400 |
| Empty batch | `-32600` | 400 |

Responses always carry `Cache-Control: no-store`.
