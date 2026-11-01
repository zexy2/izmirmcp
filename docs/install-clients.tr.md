# İstemci kurulum rehberleri

İzmir MCP için istemciye göre kurulum. Tüm örnekler sunucuyu `izmir` adıyla
kaydeder. Birincil yol uvx; Docker PyPI olmadan bugün çalışır. Çalıştırma
seçenekleri için [install.tr.md](install.tr.md) dosyasına bakın.

## Çalıştırma seçenekleri

- **uvx** — `uvx izmir-mcp stdio` (PyPI'de yayımlandığında kullanılabilir).
- **Docker** — GHCR imajı; `IZMIR_MCP_SKIP_GTFS_BUILD=1` GTFS tarife kurulumunu
  atlar, stdio hızlı başlar (`server.json` varsayılanı).
- **Yerel klon** — `uv run izmir-mcp stdio` ya da venv içinde
  `izmir-mcp-stdio` / `python -m app.stdio`.

```bash
uvx izmir-mcp stdio
docker run -i --rm -e IZMIR_MCP_SKIP_GTFS_BUILD=1 ghcr.io/zexy2/izmir-mcp:0.1.0 izmir-mcp stdio
uv run izmir-mcp stdio        # yerel klondan
```

Uzak URL kabul eden istemciler için Streamable HTTP modunu (`izmir-mcp`,
`http://127.0.0.1:8000/mcp/`) çalıştırın; herkese açmadan önce
[deployment.md](deployment.md) dosyasını okuyun.

## OpenAI Codex CLI

Yapılandırma: `~/.codex/config.toml` (güvenilen projelerde `.codex/config.toml`);
Codex CLI ve IDE eklentisi ortak kullanır. CLI komutu ya da elle TOML tablosu:

```bash
codex mcp add izmir -- uvx izmir-mcp stdio
```

```toml
[mcp_servers.izmir]
command = "uvx"
args = ["izmir-mcp", "stdio"]
```

Docker varyantı:

```toml
[mcp_servers.izmir]
command = "docker"
args = ["run", "-i", "--rm", "-e", "IZMIR_MCP_SKIP_GTFS_BUILD=1", "ghcr.io/zexy2/izmir-mcp:0.1.0", "izmir-mcp", "stdio"]
```

Uzak Streamable HTTP varyantı:

```toml
[mcp_servers.izmir]
url = "https://<your-host>/mcp/"
```

## Claude Code

CLI komutları (`--` sonrası sunucu komutudur):

```bash
claude mcp add --transport stdio izmir -- uvx izmir-mcp stdio
claude mcp add --transport stdio izmir -- docker run -i --rm -e IZMIR_MCP_SKIP_GTFS_BUILD=1 ghcr.io/zexy2/izmir-mcp:0.1.0 izmir-mcp stdio
claude mcp add --transport http izmir https://<your-host>/mcp/
```

Ya da proje kapsamlı bir `.mcp.json` ekleyin:

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

Yapılandırma: `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS), `%APPDATA%\Claude\claude_desktop_config.json` (Windows),
`~/.config/Claude/claude_desktop_config.json` (Linux). Claude Desktop'u yeniden başlatın.

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

Docker varyantı:

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

Yapılandırma: `~/.cursor/mcp.json` (genel) ya da `.cursor/mcp.json` (proje).

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

Uzak Streamable HTTP varyantı:

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

Yapılandırma: çalışma alanında `.vscode/mcp.json` (ya da **MCP: Add Server**).
Üst anahtar `mcpServers` değil `servers`'dır.

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

Uzak Streamable HTTP varyantı:

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

Yapılandırma: Zed `settings.json` (`zed: open settings file`), anahtar `context_servers`.

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

Uzak Streamable HTTP varyantı:

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

Yapılandırma: `~/.gemini/settings.json` (kullanıcı) ya da `.gemini/settings.json`
(proje). CLI komutu ya da JSON:

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

Uzak Streamable HTTP varyantı:

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

Yapılandırma: CLI için `~/.cline/data/settings/cline_mcp_settings.json`; IDE
eklentisinde MCP Servers simgesi → Configure → **Configure MCP Servers**.

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

## Çalıştığını doğrulayın

İstemciyi yeniden başlatın ve asistandan `izmir_health` aracını çağırmasını
isteyin. Sağlıklı yanıt sürümü ve kaynak durumunu listeler; araç görünmüyorsa
başlatma komutunu elle çalıştırıp hatayı görün.

## Kaynaklar

- Codex: https://developers.openai.com/codex/mcp
- Claude Code: https://docs.claude.com/en/docs/claude-code/mcp
- Claude Desktop: https://modelcontextprotocol.io/docs/develop/connect-local-servers
- Cursor: https://cursor.com/docs/context/mcp
- VS Code: https://code.visualstudio.com/docs/copilot/customization/mcp-servers
- Zed: https://zed.dev/docs/ai/mcp
- Gemini CLI: https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md
- Cline: https://docs.cline.bot/mcp/configuring-mcp-servers
