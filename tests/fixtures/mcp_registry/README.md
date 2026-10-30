# MCP Registry schema

`server-2025-12-11.schema.json` is the unmodified official MCP Registry schema
from https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json
(copied from the istanbul-mcp reference fixture, which pinned it 2026-10-23).

SHA-256: `3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0`.
Upstream: https://github.com/modelcontextprotocol/registry (MIT).
Used for deterministic, offline manifest validation; no network in unit tests.
Updating the pinned manifest schema requires updating this fixture explicitly.
