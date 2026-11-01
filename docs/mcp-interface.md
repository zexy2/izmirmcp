# MCP interface (protocol and transports)

This document describes the server's MCP surface, its two transports and its
discovery resources. Scope boundaries with neighbouring docs:

- Per-tool inputs and outputs: [tool-reference.md](tool-reference.md).
- Envelope fields and error codes: [response-contract.md](response-contract.md).
- Health endpoints and logs: [monitoring.md](monitoring.md).
- Registry manifest and publishing: [registry.md](registry.md).

## Transports

| Transport | Entry point | Use |
|---|---|---|
| Streamable HTTP | `python -m app.main` → `POST /mcp/` | Remote or local HTTP clients |
| stdio | `python -m app.stdio` | Desktop clients (Claude Code, Codex, etc.) |

Both use the **same** `create_mcp_server()` instance, so the tool surface and
schemas do not depend on the transport.

### HTTP details

- Path: `/mcp/` (`/mcp` redirects permanently to `/mcp/` with a 308).
- `stateless_http=True` and `json_response=True`: no session state is kept and
  every response is plain JSON (no SSE stream).
- The `Accept` header must include `application/json, text/event-stream`.
- Body limit: `IZMIR_MCP_MCP_MAX_BODY_BYTES` (default 1 MB).

### stdio details

One JSON-RPC message per line. Handshake:

```text
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
← {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{...},"instructions":"..."}}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}
→ {"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

`app.stdio` serves one session per process; use HTTP for multiple clients.

## Protocol version

The protocol version is negotiated by the MCP Python SDK during `initialize`;
the application does not pin or override it. If the returned
`protocolVersion` differs from the one the client proposed, the client decides
whether to continue.

## Surface

| Kind | Count | Defined in |
|---|---|---|
| Tools | 36 | `app/mcp/registry.py::DEFAULT_TOOL_NAMES` |
| Prompts | 12 | `app/mcp/prompts.py::WORKFLOW_PROMPTS` |
| Resources | 5 | `app/mcp/resources.py` |

Every tool carries `read_only_hint=True`, `destructive_hint=False`,
`idempotent_hint=True` and `open_world_hint=True`, and has `structured_output`
enabled: the output schema is `ResponseEnvelope`. Tool titles are Turkish;
descriptions are English (see the language policy in `CONTRIBUTING.md`).

## Discovery resources

| URI | Content |
|---|---|
| `izmir://coverage` | Capabilities, tool mapping, source IDs, data kind |
| `izmir://sources` | Canonical publishers and public source addresses |
| `izmir://schema/catalog` | Catalog workflow and envelope schema |
| `izmir://reference/fares` | Which tool answers which fare question (no prices) |
| `izmir://reference/lines` | Line/station/stop tools per transport mode |

These five resources make **no network calls** and make no claim about
upstream health.

## Prompts

`gunun_ozeti`, `veri_kesfi`, `toplu_ulasim`, `otobus`, `pazar_ve_duyurular`,
`sehir_hizmetleri`, `nobetci_eczane`, `rota_karsilastir`, `bugun_ne_yapsam`,
`su_durumu_raporu`, `eczane_ve_ulasim`, `sehir_simdi`.

Prompt names are Turkish identifiers and stay stable. Multi-tool prompts add an
unofficial-data note and a data-freshness section. Prompt arguments are encoded
as JSON data and carry a "do not execute as instructions" note.

## Error semantics

There are two separate layers; do not mix them up:

| Case | Where | Shape |
|---|---|---|
| Schema violation (missing required field, wrong type) | SDK, before the handler | JSON-RPC result `isError: true` + plain text |
| Unknown tool | SDK | `isError: true` + "Unknown tool: ..." |
| Business-rule violation (invalid radius, unknown district…) | Our service | **Envelope**: `ok:false`, `error.code="validation_error"`, `error.field` |
| Source failure | Our service | **Envelope**: `source_unavailable` / `source_rate_limited` / `source_timeout` |

So "invalid input" can appear in two shapes: input rejected by the schema is a
protocol error, while input that passes the schema but breaks a business rule
is an envelope. Clients must handle both. `scripts/smoke_mcp.py` exercises this
behaviour. The full error code list lives in
[response-contract.md](response-contract.md).

## Health endpoints

`/healthz`, `/readyz` and `/status` are documented in
[monitoring.md](monitoring.md). `/readyz` reports
`upstream_health: "not_checked"`: it **does not measure source health** and
never fans out to third-party APIs.
