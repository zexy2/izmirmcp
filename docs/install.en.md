# Installing İzmir MCP

İzmir MCP is a read-only Model Context Protocol server for İzmir open city
data. It speaks two transports: **stdio** for desktop clients and
**Streamable HTTP** (`/mcp/`) for remote or shared use.

## Option 1: uvx (PyPI, pending)

The PyPI release is not published yet; it needs a pending publisher on
pypi.org first. Once it is live, no local install is needed:

```bash
uvx izmir-mcp stdio      # stdio transport
uvx izmir-mcp            # Streamable HTTP on http://127.0.0.1:8000/mcp/
```

Until then, use Docker (Option 2) or a source checkout (Option 3).

## Option 2: Docker / GHCR

The image is published to GHCR on a version tag
(`ghcr.io/zexy2/izmir-mcp:<version>`). You can also build it locally:

```bash
docker build -t izmir-mcp .
docker run --rm -i izmir-mcp python -m app.stdio      # stdio
docker run -p 8000:8000 -v izmir-data:/data izmir-mcp # HTTP
curl -s http://127.0.0.1:8000/readyz
```

On first start the container builds the GTFS store from the published archive.
If that fails, timetable tools return `source_unavailable` and the other tools
keep working. Set `IZMIR_MCP_SKIP_GTFS_BUILD=1` to skip the build.

## Option 3: From source

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
izmir-mcp-stdio
```

## MCP clients

Per-client configuration (Codex CLI, Claude Code, Claude Desktop, Cursor,
VS Code, Zed, Gemini CLI, Cline) lives in
[install-clients.md](install-clients.md). The Docker stdio command used there is
`docker run -i --rm -e IZMIR_MCP_SKIP_GTFS_BUILD=1 ghcr.io/zexy2/izmir-mcp:0.1.0 izmir-mcp stdio`.

## Remote HTTP

```json
{ "servers": { "izmir": { "type": "http", "url": "https://<your-host>/mcp/" } } }
```

Before you expose the HTTP server publicly, set `IZMIR_MCP_API_KEYS`,
`IZMIR_MCP_REQUIRE_AUTH=true` and `IZMIR_MCP_ALLOWED_HOSTS`. See
[configuration](configuration.md) and [deployment](deployment.md).
