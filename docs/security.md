# Security and threat model

İzmir MCP is read-only: it writes no data, stores no user data and only reads
public city sources. This document summarises the attack surface and the
in-code defence for each surface. To report a vulnerability, use a private
GitHub security advisory (see `SECURITY.md`). The latest scan results are in the
[security report](development/reports/security-report.md).

## Assets and actors

- **Assets:** the server's network position (internal network, cloud metadata
  endpoints), compute resources (CPU, memory, disk), API keys and quota
  counters.
- **Actors:** a malicious MCP client, a third-party page in a browser (DNS
  rebinding / CSRF), a compromised or faulty upstream source, and content that
  tries to inject model instructions through text in tool output.

## SSRF and upstream policy

`app/connectors/http.py`:

- Upstream addresses come from configuration; clients cannot supply URLs.
- `_GuardedTransport` resolves the name once, validates **every** answer and
  binds the socket to the validated IP (Host and TLS SNI are preserved). DNS
  rebinding between check and connect is not possible.
- Loopback, RFC1918, link-local (`169.254.169.254`), CGNAT, multicast, reserved
  ranges and IPv4-mapped / 6to4 IPv6 addresses are rejected.
- Redirects are only followed to the same origin and a bounded number of times.
- `trust_env=False`: `HTTP(S)_PROXY` in the environment cannot redirect
  upstream traffic.
- `IZMIR_MCP_ALLOW_PRIVATE_UPSTREAMS` is for tests only and off by default.

## Resource consumption

- Upstream bodies are streamed and cut off once `IZMIR_MCP_RESPONSE_MAX_BYTES`
  is exceeded; the GTFS ZIP has archive, member and row caps.
- `IZMIR_MCP_HTTP_TOTAL_DEADLINE_SECONDS` bounds the time including retries.
- Unreachable hosts get a 60 s cool-down; the table is an LRU capped at 256
  hosts.
- Incoming bodies are capped by `IZMIR_MCP_CLIENT_MAX_BODY_BYTES` (`413`,
  including chunked bodies and a fake `Content-Length`).
- Per-client rate limit (`429`), concurrency cap (`503`) and an optional daily
  quota per key.
- `izmir_datastore_query` runs a single SELECT only over the local copy of
  allowed resources, with a SQLite authorizer, a row/byte budget and a query
  timeout. See [Local SQL](datastore-sql.md).
- If the event loop hangs, the watchdog logs a stack dump and restarts the
  process.

## Incoming request validation

| Check | Default | Response |
|---|---|---|
| API key (`IZMIR_MCP_API_KEYS`) | off | `401 unauthorized` |
| `IZMIR_MCP_REQUIRE_AUTH` | `false` | startup error without keys; a warning on a public bind while off |
| Host allowlist (`IZMIR_MCP_ALLOWED_HOSTS`) | empty: warning only | `421` |
| Origin allowlist (`IZMIR_MCP_CORS_ALLOWED_ORIGINS`) | empty: browsers rejected | `403 origin_not_allowed` |

The defaults are loose for backward compatibility and are only safe on
loopback. For an internet-facing deployment see
[Configuration](configuration.md#profile-3-public-internet-facing-deployment).

## Logging and privacy

The API key is never logged under any circumstances; only its SHA-256 digest is
kept in memory. The access log can be turned off with
`IZMIR_MCP_ACCESS_LOG_ENABLED`. Details: [Privacy](privacy.md).

## Model side (prompt injection)

Upstream text is always returned as data and shortened with `bounded_text`.
Prompt arguments are JSON-encoded and labelled "user data, not instructions";
non-printable values and values longer than 200 characters are rejected.

## Supply chain

The Docker base image is pinned by digest, dependencies by a hashed lock, and
GitHub actions by commit SHA. CI runs a Trivy image scan, a syft SBOM and
`pip-audit`; releases are published with PyPI trusted publishing (OIDC).

## Out of scope

TLS termination (put a reverse proxy in front), DDoS protection and the
integrity of upstream sources are outside this project's control.
