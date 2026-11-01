# API access and key management

The default installation is **open**: authentication is off and only a
per-client rate limit applies. This document explains key generation,
rotation and quotas for a protected deployment.

## Key generation

A key must be 32–256 characters and URL-safe (`A-Z a-z 0-9 . _ ~ -`).
Recommended generation:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Pass the keys, comma-separated, in `IZMIR_MCP_API_KEYS`:

```bash
export IZMIR_MCP_API_KEYS="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
```

The server keeps keys in memory **only as SHA-256 digests**; the plain text is
never stored or logged (see [privacy.md](privacy.md)).

## Client side

```http
Authorization: Bearer <key>
```

Missing or wrong key:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="izmir-mcp"
```

## Protected paths

| Path | Key required |
|---|---|
| `GET /healthz` | No (open for liveness probes) |
| `GET /readyz` | No (open for readiness probes) |
| `GET /status` | Yes (so counters and configuration do not leak) |
| `/mcp`, `/mcp/*` | Yes |

## Daily quota

When `IZMIR_MCP_API_KEY_DAILY_QUOTA` > 0, a daily request quota applies per
key and is **persisted in SQLite**: the counter is not reset when the server
restarts.

```http
HTTP/1.1 429 Too Many Requests
Retry-After: <seconds until midnight>
{"ok": false, "error_code": "quota_exceeded", ...}
```

If the quota store cannot be read, it **fails closed** with
`503 quota_unavailable`, so a broken disk does not turn into unlimited access.

The quota is separate from the in-memory rate limit:

| Protection | Storage | Purpose |
|---|---|---|
| Rate limit (60/s) | Memory | Sudden bursts |
| Daily quota | SQLite | Total usage budget |

## Rotation

1. Add the new key to the list and keep the old one.
2. Move clients to the new key.
3. Remove the old key from the list and restart the server.

Quota records are tied to the key **digest**; rotation starts a new counter
(expected behaviour).

## Limits

- There are no per-key roles or permissions: all tools are read-only and every
  valid key reaches the same surface.
- No OAuth, rotating tokens or revocation list; keys are compared statically.
- Keys live only in memory, so changes require a restart.
