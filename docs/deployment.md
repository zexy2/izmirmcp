# Dağıtım

Bu belge HTTP/stdio sunucusunun nasıl çalıştırılacağını, tüm ortam
değişkenlerini ve güvenlik katmanlarının gerçek davranışını koddan türetir
(`app/core/settings.py`, `app/main.py`, `app/core/*.py`, `Dockerfile`,
`docker/entrypoint.sh`). Varsayılanlar `get_settings()` ile birebirdir.

## Çalıştırma biçimleri

| Taşıma | Komut | Uç |
|---|---|---|
| Streamable HTTP | `python -m app.main` veya `izmir-mcp` | `http://127.0.0.1:8000/mcp/` |
| stdio | `python -m app.stdio` veya `izmir-mcp-stdio` | stdin/stdout |
| Konteyner (HTTP) | `docker run -p 8000:8000 -v izmir-data:/data izmir-mcp` | `http://127.0.0.1:8000/mcp/` |
| Konteyner (stdio) | `docker run --rm -i izmir-mcp python -m app.stdio` | stdin/stdout |

`app/main.py` uvicorn'u `proxy_headers=True`, `forwarded_allow_ips="127.0.0.1"` ile
başlatır. `/mcp` (sondaki eğik çizgi olmadan) `308` ile `/mcp/`'ye yönlendirilir.

Yerel kurulum:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m app.main
```

## Ortam değişkenleri

Değerler `IZMIR_MCP_*` adlarıyla okunur. Boş/ayrıştırılamayan değerler
varsayılana döner. Liste değişkenleri virgülle ayrılır (boş öğeler atılır).

### Sunucu ve limitler

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `IZMIR_MCP_HOST` | `127.0.0.1` | Bağlanma adresi. |
| `IZMIR_MCP_PORT` | `8000` | HTTP portu. |
| `IZMIR_MCP_DEFAULT_LIMIT` | `10` | `limit` verilmezse kullanılan kayıt sayısı. |
| `IZMIR_MCP_MAX_LIMIT` | `50` | İzin verilen en yüksek `limit`. |
| `IZMIR_MCP_MAX_RADIUS_M` | `5000` | `radius_m` üst sınırı. |

`Settings` alan karşılıkları `default_limit`, `max_limit`, `max_radius_m` olup
varyasyonları sırasıyla `10`, `50`, `5000`'dir. Bu değerler `/status` yanıtının
`limits` bloğunda `max_body_bytes` ile birlikte yayımlanır.

### Dış istek bütçesi

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `IZMIR_MCP_REQUEST_TIMEOUT_SECONDS` | `15.0` | Kaynak isteği zaman aşımı. |
| `IZMIR_MCP_REQUEST_ATTEMPTS` | `2` | Yeniden deneme sayısı (5xx/bağlantı hatasında). |
| `IZMIR_MCP_RESPONSE_MAX_BYTES` | `2000000` | Kaynak yanıtı byte tavanı. |

### Kaynak URL'leri ve önbellek

| Değişken | Varsayılan |
|---|---|
| `IZMIR_MCP_CKAN_BASE_URL` | `https://acikveri.bizizmir.com/api/3/action` |
| `IZMIR_MCP_OPENAPI_BASE_URL` | `https://openapi.izmir.bel.tr/api` |
| `IZMIR_MCP_IZSU_DAMS_CSV_URL` | `https://openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv` |
| `IZMIR_MCP_IZTEK_BASE_URL` | `https://openapi.izmir.bel.tr/api/iztek` |
| `IZMIR_MCP_ESHOT_GTFS_URL` | `https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip` |
| `IZMIR_MCP_ESHOT_NOTICES_CSV_URL` | `https://openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv` |
| `IZMIR_MCP_ESHOT_STOPS_RESOURCE_ID` | `0c791266-a2e4-4f14-82b8-9a9b102fbf94` |
| `IZMIR_MCP_ESHOT_ROUTES_RESOURCE_ID` | `bd6c84f8-49ba-4cf4-81f8-81a0fbb5caa3` |
| `IZMIR_MCP_IZTEK_CACHE_TTL_SECONDS` | `20` |
| `IZMIR_MCP_IZTEK_MIN_REQUEST_INTERVAL_SECONDS` | `0.5` |
| `IZMIR_MCP_ESHOT_CACHE_TTL_SECONDS` | `86400` |
| `IZMIR_MCP_ESHOT_STALE_IF_ERROR_SECONDS` | `604800` |
| `IZMIR_MCP_ESHOT_NOTICES_CACHE_TTL_SECONDS` | `1800` |
| `IZMIR_MCP_CITY_LAYER_CACHE_TTL_SECONDS` | `86400` |
| `IZMIR_MCP_CITY_LAYER_STALE_IF_ERROR_SECONDS` | `604800` |

CKAN TTL'leri (`catalog` 21600 sn, `resource` 300 sn), OpenAPI TTL'i (120 sn /
900 sn stale) ve İZSU TTL'i (3600 sn / 86400 sn stale) `Settings` alanıdır ama
ortam değişkeniyle açılmaz; değiştirmek için kod gerekir.

### GTFS deposu

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `IZMIR_MCP_DATABASE_PATH` | `.data/izmir_mcp.sqlite3` | Yerel GTFS SQLite yolu (`/data/...` konteynerde). |
| `IZMIR_MCP_ESHOT_GTFS_MAX_BYTES` | `67108864` | ZIP tavani (64 MB). |
| `IZMIR_MCP_ESHOT_GTFS_MEMBER_MAX_BYTES` | `8388608` | Üye dosya tavanı (8 MB). |
| `IZMIR_MCP_ESHOT_GTFS_STOP_TIMES_MAX_BYTES` | `134217728` | `stop_times.txt` tavanı (128 MB). |
| `IZMIR_MCP_ESHOT_GTFS_MAX_ROWS` | `2500000` | Satır tavanı. |
| `IZMIR_MCP_ESHOT_GTFS_CACHE_TTL_SECONDS` | `86400` | Yeniden kurulum eşiği. |
| `IZMIR_MCP_ESHOT_GTFS_STALE_IF_ERROR_SECONDS` | `604800` | Yenilenemezse eski depoyu kullanma süresi. |

### HTTP güvenliği

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `IZMIR_MCP_CLIENT_MAX_BODY_BYTES` | `1000000` | `/mcp` gövde tavanı; aşılırsa `413`. |
| `IZMIR_MCP_CLIENT_RATE_LIMIT_CAPACITY` | `60` | İstemci başına token kovası. |
| `IZMIR_MCP_CLIENT_RATE_LIMIT_REFILL_PER_SECOND` | `1.0` | Saniyede token dolumu. |
| `IZMIR_MCP_CLIENT_RATE_LIMIT_MAX_CLIENTS` | `10000` | İzlenen istemci üst sınırı (LRU budama). |
| `IZMIR_MCP_CLIENT_MAX_CONCURRENT_REQUESTS` | `32` | Eşzamanlı `/mcp` isteği. |
| `IZMIR_MCP_API_KEYS` | boş | Bearer anahtarları; boşsa kimlik doğrulama kapalı. |
| `IZMIR_MCP_CORS_ALLOWED_ORIGINS` | boş | Tarayıcı Origin allowlist'i. |
| `IZMIR_MCP_ACCESS_LOG_ENABLED` | `true` | Yapısal erişim logu. |

Not: `IZMIR_MCP_MCP_MAX_BODY_BYTES` kodu MCP SDK'nın kendi gövde sınırını
`mcp_max_body_bytes` alanından (varsayılan 1 MB) alır; ortamla ayrı açılmaz,
`CLIENT_MAX_BODY_BYTES` ile aynı yönde tutulmalıdır.

## Kimlik doğrulama

`IZMIR_MCP_API_KEYS` boşsa kapalıdır. Doluysa `/status` ve `/mcp`/`/mcp/*`
`Authorization: Bearer <anahtar>` ister; eksik/yanlış → `401` +
`WWW-Authenticate: Bearer realm="izmir-mcp"`. Anahtarlar SHA-256 özetiyle
karşılaştırılır (`hmac.compare_digest`) ve loglanmaz. Doğrulama: 1–100 benzersiz,
32–256 karakter, `[A-Za-z0-9._~-]`. Aksi halde süreç başlamaz (`ValueError`).
`/healthz` ve `/readyz` **her zaman** açıktır.

## Origin allowlist ve CORS

Tarayıcı `Origin` gönderirse değer allowlist'te olmalıdır; yoksa `403`
`origin_not_allowed`. `Origin` göndermeyen CLI/MCP istemcileri etkilenmez.
Allowlist boşken.tüm tarayıcı Origin'leri reddedilir (fail-closed).

Doğrulama: en fazla 32 benzersiz origin; `https` zorunlu (`http` yalnızca
`localhost`, `127.0.0.1`, `[::1]`); joker, kimlik bilgisi, yol, sorgu, parça
yasak; küçük harf host. CORS yanıt başlıkları: izin verilen yöntemler
`GET, POST, DELETE, OPTIONS`; açığa çıkarılan başlıklar `Mcp-Session-Id`,
`Mcp-Protocol-Version`, `WWW-Authenticate`, `Retry-After`; `max-age=600`.
Preflight `OPTIONS` → `204`.

## Abuse koruma katmanları

Sıra (içten dışa): abuse guard → auth → access log → CORS. Aşım durumları zarf
değil **HTTP kodu** + `{"ok": false, "error_code", "summary"}` döner:

| Durum | Kod | Başlık |
|---|---|---|
| Gövde tavanı | `413 payload_too_large` | — |
| Hız sınırı | `429 rate_limited` | `Retry-After` |
| Eşzamanlılık | `503 server_busy` | `Retry-After: 1` |
| Kimlik doğrulama | `401 unauthorized` | `WWW-Authenticate` |
| Origin | `403 origin_not_allowed` | `Vary: Origin` |

- Hız sınırı ve sayaçlar **süreç içi ve uçucudur**. Çok işçili dağıtımda her
  işçi kendi bütçesini uygular; toplam sınır için önüne reverse proxy koyun.
- İstemci kimliği doğrudan bağlantı adresidir. `X-Forwarded-For` **yalnızca**
  sunucu loopback'e bağlıyken, **tek** başlık ve **tek bare değer** (virgül ve
  boşluk yok) taşıdığında dikkate alınır. Liste, yinelenen başlık veya boş değer
  güvenilmez; soket eşi kullanılır. Böylece tek bağlantıdan istek başına sahte
  kimlik üretilerek hız sınırı atlatılamaz (`tests/test_http_security.py`).
- Güvenlik testleri: `tests/test_http_security.py` kimlik doğrulama bypass
  varyantlarını (şema, uzunluk, çift başlık, yol kodlaması), origin bypass'ı
  (şema, port, alt alan adı, çift başlık, `null`, `*`), gövde tavanını
  (Content-Length, chunked, sahte uzunluk) ve log hijyenini doğrular.
- Erişim logu yöntem, yol, durum ve süre yazar; sorgu dizesi, gövde, başlık ve
  API anahtarı **hiçbir zaman** loglanmaz. Ayrıntı: [monitoring.md](monitoring.md).
- Bu katman yetkilendirme sunucusu değildir; statik anahtar karşılaştırması
  yapar, OAuth/döner anahtar yoktur.

## Konteyner imajı

`Dockerfile` `python:3.11-slim` tabanlıdır (digest pinli, çok aşamalı değil),
root olmayan `izmir` kullanıcısı (uid 10001) ve `/data` hacmi kullanır.
`PYTHONUNBUFFERED=1`, `IZMIR_MCP_HOST=0.0.0.0`, `IZMIR_MCP_PORT=8000`,
`IZMIR_MCP_DATABASE_PATH=/data/izmir_mcp.sqlite3` derleme anında sabitlenir.
`HEALTHCHECK` `/healthz`'i yoklar (kaynak sağlığı ölçmez).

`.data/`, `.venv/`, `tests/`, `reports/`, `scripts/`, `docs/` imaja girmez
(`.dockerignore`); `app/data/places.json` girer.

`docker/entrypoint.sh` açılışta GTFS deposunu önceden kurar
(`python -m app.storage.gtfs_schedule`). Başarısız olursa konteyner **durmaz**:
tarife araçları dürüst `source_unavailable` döner, diğerleri çalışmaya devam
eder. Kurulumu atlamak için `IZMIR_MCP_SKIP_GTFS_BUILD=1` (yalnızca konteyner
giriş betiği tarafından okunur, Python kodu tarafından değil).

GTFS deposunu elle kurmak:

```bash
python -m app.storage.gtfs_schedule --database .data/izmir_mcp.sqlite3
```

Başarı `0`, herhangi bir hata `2` döner; geçersiz arşivde hiçbir şey yazılmaz.

## CI

`.github/workflows/ci.yml`: `pytest`, import + 19 araç yüzeyi kontrolü, çevrimdışı
protokol smoke'u (`scripts/smoke_mcp.py`), canlı smoke (bloklamaz), sunucuyu başlatıp `/healthz`+`/readyz`+`/status` probe'u, ve
imaj derleyip konteynerde `/healthz` doğrulaması (`IZMIR_MCP_SKIP_GTFS_BUILD=1`).
