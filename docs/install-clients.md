# Client setup guides

Per-client setup for İzmir MCP. Every snippet registers the server under the
name `izmir`. The uvx variant is primary; Docker works today without PyPI.
See [install.en.md](install.en.md) for the run options themselves.

## Run options

- **uvx** — `uvx izmir-mcp stdio` (available once published to PyPI).
- **Docker** — the GHCR image; `IZMIR_MCP_SKIP_GTFS_BUILD=1` skips the GTFS
  timetable build so stdio starts fast (the default in `server.json`).
- **Local clone** — `uv run izmir-mcp stdio`, or `izmir-mcp-stdio` /
  `python -m app.stdio` inside the venv.

```bash
uvx izmir-mcp stdio
docker run -i --rm -e IZMIR_MCP_SKIP_GTFS_BUILD=1 ghcr.io/zexy2/izmir-mcp:0.1.0 izmir-mcp stdio
uv run izmir-mcp stdio        # from a local clone
```

For clients that accept a remote URL, run the Streamable HTTP mode
(`izmir-mcp`, served at `http://127.0.0.1:8000/mcp/`) and see
[deployment.md](deployment.md) before exposing it publicly.

## OpenAI Codex CLI

Config: `~/.codex/config.toml` (or project `.codex/config.toml` for trusted
projects); shared by the Codex CLI and IDE extension. CLI one-liner, or add the
TOML table by hand:

```bash
codex mcp add izmir -- uvx izmir-mcp stdio
```

```toml
[mcp_servers.izmir]
command = "uvx"
args = ["izmir-mcp", "stdio"]
```

Docker variant:

```toml
[mcp_servers.izmir]
command = "docker"
args = ["run", "-i", "--rm", "-e", "IZMIR_MCP_SKIP_GTFS_BUILD=1", "ghcr.io/zexy2/izmir-mcp:0.1.0", "izmir-mcp", "stdio"]
```

Remote Streamable HTTP variant:

```toml
[mcp_servers.izmir]
url = "https://<your-host>/mcp/"
```

## Claude Code

CLI one-liners (everything after `--` is the server command):

```bash
claude mcp add --transport stdio izmir -- uvx izmir-mcp stdio
claude mcp add --transport stdio izmir -- docker run -i --rm -e IZMIR_MCP_SKIP_GTFS_BUILD=1 ghcr.io/zexy2/izmir-mcp:0.1.0 izmir-mcp stdio
claude mcp add --transport http izmir https://<your-host>/mcp/
```

Or commit a project-scoped `.mcp.json`:

```json
{
  "mcpServers": {
    "izmir": {
      "command": "uvx",
      "args": [
        "izmir-mcp",
        "stdio"
      ]
    }
  }
}
```

## Claude Desktop

Config: `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS), `%APPDATA%\Claude\claude_desktop_config.json` (Windows),
`~/.config/Claude/claude_desktop_config.json` (Linux). Restart Claude Desktop.

```json
{
  "mcpServers": {
    "izmir": {
      "command": "uvx",
      "args": [
        "izmir-mcp",
        "stdio"
      ]
    }
  }
}
```

Docker variant:

```json
{
  "mcpServers": {
    "izmir": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "IZMIR_MCP_SKIP_GTFS_BUILD=1",
        "ghcr.io/zexy2/izmir-mcp:0.1.0",
        "izmir-mcp",
        "stdio"
      ]
    }
  }
}
```

## Cursor

Config: `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project).

```json
{
  "mcpServers": {
    "izmir": {
      "command": "uvx",
      "args": [
        "izmir-mcp",
        "stdio"
      ]
    }
  }
}
```

Remote Streamable HTTP variant:

```json
{
  "mcpServers": {
    "izmir": {
      "url": "https://<your-host>/mcp/"
    }
  }
}
```

## VS Code / GitHub Copilot

Config: `.vscode/mcp.json` in the workspace (or run **MCP: Add Server**).
Note the top-level key is `servers`, not `mcpServers`.

```json
{
  "servers": {
    "izmir": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "izmir-mcp",
        "stdio"
      ]
    }
  }
}
```

Remote Streamable HTTP variant:

```json
{
  "servers": {
    "izmir": {
      "type": "http",
      "url": "https://<your-host>/mcp/"
    }
  }
}
```

## Zed

Config: Zed `settings.json` (`zed: open settings file`), key `context_servers`.

```json
{
  "context_servers": {
    "izmir": {
      "command": "uvx",
      "args": [
        "izmir-mcp",
        "stdio"
      ],
      "env": {}
    }
  }
}
```

Remote Streamable HTTP variant:

```json
{
  "context_servers": {
    "izmir": {
      "url": "https://<your-host>/mcp/"
    }
  }
}
```

## Gemini CLI

Config: `~/.gemini/settings.json` (user) or `.gemini/settings.json`
(project). CLI one-liner or JSON:

```bash
gemini mcp add izmir uvx izmir-mcp stdio
```

```json
{
  "mcpServers": {
    "izmir": {
      "command": "uvx",
      "args": [
        "izmir-mcp",
        "stdio"
      ]
    }
  }
}
```

Remote Streamable HTTP variant:

```json
{
  "mcpServers": {
    "izmir": {
      "httpUrl": "https://<your-host>/mcp/"
    }
  }
}
```

## Cline

Config: CLI `~/.cline/data/settings/cline_mcp_settings.json`; IDE extension
via the MCP Servers icon → Configure → **Configure MCP Servers**.

```json
{
  "mcpServers": {
    "izmir": {
      "command": "uvx",
      "args": [
        "izmir-mcp",
        "stdio"
      ],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

## Verify it works

Restart the client, then ask the assistant to call `izmir_health`. A healthy
reply lists the server version and source status; if the tool is missing, run
the launch command by hand to see the error.

## Sources

- Codex: https://developers.openai.com/codex/mcp
- Claude Code: https://docs.claude.com/en/docs/claude-code/mcp
- Claude Desktop: https://modelcontextprotocol.io/docs/develop/connect-local-servers
- Cursor: https://cursor.com/docs/context/mcp
- VS Code: https://code.visualstudio.com/docs/copilot/customization/mcp-servers
- Zed: https://zed.dev/docs/ai/mcp
- Gemini CLI: https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md
- Cline: https://docs.cline.bot/mcp/configuring-mcp-servers
