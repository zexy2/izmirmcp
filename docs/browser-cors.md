# Browser access and CORS

This server can be called from **browser applications**, but by default it is
only open to clients that send no `Origin` (CLI, desktop MCP clients,
server-to-server). When a browser request arrives, its origin must be
**explicitly** allowed.

## Default behaviour

| `IZMIR_MCP_CORS_ALLOWED_ORIGINS` | Browser sending an Origin | Client without an Origin |
|---|---|---|
| empty (default) | **403 `origin_not_allowed`** | works |

This is a "fail closed" approach: a misconfigured deployment is open to no
browser at all instead of to every site.

## Allowlist

```bash
export IZMIR_MCP_CORS_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"
```

Rules (validated at startup; a violation stops the process with `ValueError`):

- At most **32** unique origins.
- `https://` is required; `http://` only for `localhost`, `127.0.0.1`, `[::1]`.
- Nothing beyond scheme + host + (optional) port: no path, query or fragment.
- No wildcard (`*`), percent-encoding or credentials (`user:pass@`).
- The host must be lowercase.

## Response headers

For an allowed origin:

```http
Access-Control-Allow-Origin: https://app.example.com
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Accept, Content-Type, Authorization, Mcp-Session-Id, ...
Access-Control-Expose-Headers: Mcp-Session-Id, Mcp-Protocol-Version, WWW-Authenticate, Retry-After
Access-Control-Max-Age: 600
```

`Access-Control-Allow-Credentials` is **not sent**: identity travels in the
Bearer header, not in cookies.

## Preflight

`OPTIONS /mcp/` returns `204` without consuming authentication or rate limit;
real requests pass through every protection layer.

## Common errors

| Symptom | Cause |
|---|---|
| `403 origin_not_allowed` in the browser | The origin is not in the list |
| Preflight 200 but the actual request 401 | Missing Bearer key (CORS and auth are separate layers) |
| No `Access-Control-Allow-Origin` at all | No Origin header is sent, or the allowlist is empty |
| Server does not start, `ValueError` | Invalid origin format (path/wildcard/http) |

## Limits

- The origin check is for **browsers**; CLI clients skip it and rely on the
  Bearer key for security.
- DNS rebinding protection for public hosts is configured with
  `IZMIR_MCP_ALLOWED_HOSTS` (see [configuration.md](configuration.md)).
- When binding only to `localhost`/`127.0.0.1`, the Host header policy is the
  SDK default; put a reverse proxy in front when binding to a public address.
