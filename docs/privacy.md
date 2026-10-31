# Privacy and data handling

This server is **read-only** and keeps no user accounts. It is still worth
stating plainly which data is processed; the table below is derived from the
code (`app/core/http_logging.py`, `app/core/api_auth.py`,
`app/core/rate_limit.py`).

## What is stored

| Data | Where | Retention |
|---|---|---|
| Per-client rate limit counter | Process memory (`ClientRateLimiter`) | Process lifetime |
| Concurrency counter | Process memory | Process lifetime |
| API key **digest** (SHA-256) | Process memory | Process lifetime |
| GTFS timetable store | `IZMIR_MCP_DATABASE_PATH` (SQLite) | Until you delete it |
| Daily quota counters (only when a quota is set) | SQLite | Per key digest, per day |
| Source response cache | Process memory | TTL (per source) |

No user data is written: no user table, no cookies, no session storage.

## What is not stored

The access log only writes these fields:

```json
{"event": "http_request", "method": "POST", "path": "/mcp/",
 "status": 200, "duration_ms": 2.9}
```

- **No query string.** Values such as `?resource_id=...` are not logged.
- **No body.** Tool inputs, coordinates and address searches are not logged.
- **No headers.** `Authorization`, `Cookie` and `Mcp-Session-Id` never appear.
- **The API key is never written under any circumstances**; only its SHA-256
  digest is compared in memory.

To turn the log off entirely: `IZMIR_MCP_ACCESS_LOG_ENABLED=false`. The full
field list is in [monitoring.md](monitoring.md).

## Data sent to third parties

The server only calls the publishing institutions' endpoints to fetch the city
data the user asked for. In these requests:

- no user identity, key or session is **sent**;
- only search parameters (coordinates, stop id, date) are sent;
- the `User-Agent` is fixed: `izmir-mcp/0.1 (+https://github.com/; read-only city data client)`.

So the publishing institution can see which IP asked about which stop. This is
unavoidable for any open data client, and this project is not a proxy or
anonymiser.

## Client identity

The client identity used for rate limiting is:

- a **single** `X-Forwarded-For` value when the server is bound to loopback (a
  local reverse proxy is expected);
- otherwise the direct TCP peer address.

`X-Real-IP`, `Forwarded` and `CF-Connecting-IP` are **ignored**; comma-separated
lists and repeated headers are rejected (spoofing tests:
`tests/test_http_security.py`).

## Data sources' own policies

This document only describes this server's behaviour. The licences and terms
of use that apply to the city data belong to the publishing institutions; see
[sources.md](sources.md).
