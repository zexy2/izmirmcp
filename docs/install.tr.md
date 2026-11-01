# İzmir MCP kurulumu

İzmir MCP, İzmir açık şehir verileri için salt okunur bir Model Context
Protocol sunucusudur. İki taşıma sunar: masaüstü istemciler için **stdio**,
uzak veya paylaşımlı kullanım için **Streamable HTTP** (`/mcp/`).

## Seçenek 1: uvx (PyPI, beklemede)

PyPI sürümü henüz yayımlanmadı; önce pypi.org üzerinde bekleyen yayıncı
(pending publisher) tanımlanmalı. Yayımlandığında yerel kurulum gerekmez:

```bash
uvx izmir-mcp stdio      # stdio taşıması
uvx izmir-mcp            # http://127.0.0.1:8000/mcp/ üzerinde Streamable HTTP
```

O zamana kadar Docker (Seçenek 2) veya kaynak kurulumu (Seçenek 3) kullanın.

## Seçenek 2: Docker / GHCR

İmaj sürüm etiketiyle GHCR'a yayımlanır
(`ghcr.io/zexy2/izmir-mcp:<sürüm>`). Yerelde de derlenebilir:

```bash
docker build -t izmir-mcp .
docker run --rm -i izmir-mcp python -m app.stdio      # stdio
docker run -p 8000:8000 -v izmir-data:/data izmir-mcp # HTTP
curl -s http://127.0.0.1:8000/readyz
```

Konteyner ilk açılışta GTFS deposunu yayımlanmış arşivden kurar. Kurulum
başarısız olursa tarife araçları `source_unavailable` döner, diğer araçlar
çalışmaya devam eder. Atlamak için `IZMIR_MCP_SKIP_GTFS_BUILD=1`.

## Seçenek 3: Kaynaktan

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
izmir-mcp-stdio
```

## MCP istemcileri

İstemciye göre yapılandırma (Codex CLI, Claude Code, Claude Desktop, Cursor,
VS Code, Zed, Gemini CLI, Cline) [install-clients.tr.md](install-clients.tr.md)
dosyasındadır. Oradaki Docker stdio komutu:
`docker run -i --rm -e IZMIR_MCP_SKIP_GTFS_BUILD=1 ghcr.io/zexy2/izmir-mcp:0.1.0 izmir-mcp stdio`.

## Uzak HTTP

```json
{ "servers": { "izmir": { "type": "http", "url": "https://<sunucunuz>/mcp/" } } }
```

HTTP sunucusunu herkese açmadan önce `IZMIR_MCP_API_KEYS`,
`IZMIR_MCP_REQUIRE_AUTH=true` ve `IZMIR_MCP_ALLOWED_HOSTS` ayarlayın. Bkz.
[yapılandırma](configuration.md) ve [dağıtım](deployment.md).
