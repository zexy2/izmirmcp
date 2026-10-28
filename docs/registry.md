# MCP registry yayını

`server.json` MCP Registry manifestidir. İçeriği paket sürümüyle **senkron**
olmak zorundadır; `tests/test_packaging.py` bunu kilitler.

## Manifest yapısı

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json",
  "name": "io.github.zexy2/izmir-mcp",
  "version": "<pyproject sürümü>",
  "packages": [
    {"registryType": "pypi", "identifier": "izmir-mcp",
     "transport": {"type": "stdio"}},
    {"registryType": "oci", "identifier": "ghcr.io/zexy2/izmir-mcp:<sürüm>",
     "transport": {"type": "streamable-http", "url": "http://127.0.0.1:8000/mcp/"}}
  ]
}
```

Kurallar (testle doğrulanır):

- `$schema` yukarıdaki adres olmalı.
- `name` `io.github.<sahip>/<depo>` biçiminde olmalı.
- `version` **`pyproject.toml` ile birebir aynı** olmalı.
- `packages` en az bir `stdio` ve bir `oci` girdisi içermeli.
- OCI girdisinin imaj adı Dockerfile'ın ürettiği `izmir-mcp` imajıyla eşleşmeli.

## Yayın adımları

Sürüm çıkarken:

1. `pyproject.toml` sürümünü yükselt.
2. `server.json` içindeki **iki** `version` alanını ve OCI imaj etiketini aynı
   değere getir.
3. `CHANGELOG.md`'ye sürüm başlığı ekle.
4. `pytest -q tests/test_packaging.py` yeşil olmalı.
5. İmajı derle ve yayımla: `docker build -t izmir-mcp:<sürüm> .` ardından
   `docker push ghcr.io/zexy2/izmir-mcp:<sürüm>`.
6. `server.json`'u registry'ye gönder.

## Bilinen durum

- İmaj 2026-10-28'de **yerelde** derlenip çalıştırıldı (`izmir-mcp:local`,
  276 MB, arm64): konteyner `healthy`, 19 araç, GTFS deposu açılışta kuruldu.
- `ghcr.io`'ya **push yapılmadı**; `server.json`'daki OCI girdisi henüz
  yayımlanmış bir imajı göstermiyor.
- PyPI'ye yayın yapılmadı.
- Depoda `LICENSE` yok; yayımdan önce lisans kararı gerekir (bkz. README
  "Kaynak ve lisans").
