# Geliştirme

## Kurulum

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Bağımlılıklar `uv.lock` (3.11–3.13 için evrensel kilit) ve hash'li
`requirements.lock` (Docker imajı) ile sabitlenir. Kilidi yenilemek için
`uv lock` çalıştırın, sonra `requirements.lock`'u yeniden üretin.

## Testler

```bash
.venv/bin/python -m pytest -q          # çevrimdışı, ağ yok
IZMIR_LIVE=1 .venv/bin/python -m pytest -q tests/live   # canlı İzmir kaynakları
.venv/bin/python scripts/smoke_mcp.py --verbose          # MCP protokol smoke
.venv/bin/python scripts/eval_tools.py                   # araç seçimi eval'leri
```

Önemli kilit testleri:

- `tests/test_tool_compatibility.py` — mevcut araç adları ve girdi şemaları
  `tests/fixtures/tool_compatibility_snapshot.json` ile eşleşmeli; bkz.
  [Araç geçişi](tool-migration.md).
- `tests/test_docs.py` — belgeler koda karşı kilitlidir (araç sayısı, ortam
  değişkenleri, hata kodları).
- `tests/test_uptime_check.py` — uptime probe'u ve workflow'ların SHA ile
  sabitlenmiş action kullandığı.

## Lint

```bash
uvx ruff check app scripts tests   # ruff.toml; CI'da bloklayıcı
uvx mypy app --ignore-missing-imports   # CI'da şimdilik yalnızca rapor
```

`ruff.toml` doğruluk ve güvenlik kurallarıyla başlar; kullanılmayan import
(`F401`) ve pyupgrade (`UP`) temizliği sonrası açılacaktır.

## CI

`.github/workflows/ci.yml` işleri: `lint`, `test` (3.11/3.12/3.13 matrisi),
`conformance` (raporlar artifact olarak yüklenir), `docker` (build, `/healthz`,
Trivy taraması, syft SBOM), `audit` (`pip-audit`) ve bloklamayan `live`.
Tüm action'lar commit SHA'sıyla sabitlenir; Dependabot (`.github/dependabot.yml`)
günceller. Yerelde `act` ile çalıştırma: [Dağıtım](deployment.md#cicyı-yerelde-çalıştırma).

## Yeni araç eklerken

1. Konnektör `app/connectors/http.py` üzerinden gitmeli (SSRF, boyut, süre
   sınırları) ve kaynak önbelleğini kullanmalı.
2. Aracı `app/mcp/registry.py`'ye ekleyin; mevcut şemaları değiştirmeyin.
3. `docs/tool-reference.md` ve README araç tablosunu güncelleyin.
4. Kaynak gerçekten açık ve lisansı belli değilse aracı eklemeyin.
