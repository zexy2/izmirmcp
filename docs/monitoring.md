# İzleme

Bu belge HTTP yüzeyinin gözlemlenebilirlik sözleşmesini koddan türetir:
`app/main.py` (uçlar), `app/core/http_logging.py` (log), `app/core/rate_limit.py`
(telemetri) ve `app/core/abuse_guard.py` (reddetme kodları).

Temel ilke: **hiçbir sağlık ucu üçüncü taraf kaynakları yoklamaz.** Kaynak
sağlığı yalnızca araç yanıtlarının `freshness`/`warnings` alanlarından okunur.
Bu, probe fırtınasının İZTEK/CKAN gibi kaynakları hız sınırına takmasını önler.

## Uçlar

| Uç | Yöntem | Amaç | Auth | Durum kodu |
|---|---|---|---|---|
| `/healthz` | GET | Süreç ayakta mı? | Kapalı | Her zaman `200` |
| `/readyz` | GET | Yerel hazırlık (araç yüzeyi kuruldu mu?) | Kapalı | Hazır `200`, değil `503` |
| `/status` | GET | Araç listesi, limitler, hız/eşzamanlılık telemetrisi | `API_KEYS` doluysa açık | `200` / `401` |
| `/mcp` | GET/POST/… | `308` yönlendirme → `/mcp/` | `API_KEYS` doluysa açık | `308` |
| `/mcp/` | POST | Streamable HTTP MCP | `API_KEYS` doluysa açık | `200` / guard kodları |

### `/healthz`

```json
{"ok": true, "service": "izmir-mcp"}
```

Yalnızca süreç canlılığıdır. Docker `HEALTHCHECK` bunu yoklar.

### `/readyz`

```json
{
  "ok": true,
  "service": "izmir-mcp",
  "ready": true,
  "upstream_health": "not_checked",
  "checks": {"tool_surface": "ok", "tool_count": 17}
}
```

`upstream_health` **her zaman** `"not_checked"`'tır. Araç yüzeyi kurulamazsa
`checks.tool_surface="error:<Tip>"` veya `"empty"`, `ready=false`, HTTP `503`.
Lifespan sırasında MCP oturum yöneticisi çalışmalıdır; aksi halde probe yanıt
vermez.

### `/status`

```json
{
  "service": "izmir-mcp",
  "tools": ["izmir_health", "…"],
  "tool_count": 17,
  "limits": {"default_limit": 10, "max_limit": 50, "max_radius_m": 5000, "max_body_bytes": 1000000},
  "rate_limit": {"tracked_clients": 0, "capacity": 60, "refill_per_second": 1.0, "max_clients": 10000, "allowed": 0, "rejected": 0},
  "concurrency": {"current": 0, "max_concurrent": 32, "rejected": 0},
  "auth": "disabled",
  "upstream_health": "not_checked"
}
```

`auth` `"enabled"`/`"disabled"` değeri `IZMIR_MCP_API_KEYS` durumunu yansıtır.

## Guard reddetmeleri

`/mcp` yolundaki guard katmanları HTTP kodu + minimal gövde döner. Yapısal
olarak:

```json
{"ok": false, "error_code": "rate_limited", "summary": "Too many requests from this client."}
```

| `error_code` | HTTP | Başlık |
|---|---|---|
| `payload_too_large` | 413 | — |
| `rate_limited` | 429 | `Retry-After: <sn>` |
| `server_busy` | 503 | `Retry-After: 1` |
| `unauthorized` | 401 | `WWW-Authenticate: Bearer realm="izmir-mcp"` |
| `origin_not_allowed` | 403 | `Vary: Origin` |

Bu reddetmeler zarf taşımaz (bkz. [response-contract.md](response-contract.md)).
Uyarı eşikleri: `rate_limit.rejected` ve `concurrency.rejected` artıyorsa önüne
reverse proxy veya daha yüksek kapasite gerekir. Sayaçlar süreç içidir; çok
işçili dağıtımda işçi başına okunur.

## Erişim logu

`izmir_mcp.access` logger'ı, `IZMIR_MCP_ACCESS_LOG_ENABLED=true` iken her HTTP
isteği için **tek satır JSON** yazar:

```json
{"event": "http_request", "method": "POST", "path": "/mcp/", "status": 200, "duration_ms": 42.7}
```

Alanlar:

| Alan | Anlamı |
|---|---|
| `event` | Sabit `http_request`. |
| `method` | HTTP yöntemi. |
| `path` | Yol (sorgu dizesi hariç). |
| `status` | Yanıt durum kodu (yanıt yoksa `500`). |
| `duration_ms` | Süre, milisaniye (1 ondalık). |

**Loglanmayanlar:** sorgu dizesi, gövde, başlıklar ve API anahtarı. Bu, paylaşılan
logların çağıran içeriğini veya kimlik bilgisini sızdırmasını engeller.
`IZMIR_MCP_ACCESS_LOG_ENABLED=false` ile tamamen kapatılabilir.

## Probe önerileri

- Liveness: `GET /healthz` her 15–30 sn.
- Readiness: `GET /readyz` başlangıçta ve dağıtım sonrası; `503` trafiği
  yönlendirmeyi durdurur.
- Uyarı: `/status` içinde `rate_limit.rejected`, `concurrency.rejected` ve
  `tool_count != 17` (beklenmedik yüzey değişimi).
- Kaynak sağlığını probe ile değil, örnek araç çağrılarının
  `freshness.status` ve `warnings` çıktısıyla izleyin. Canlı duman testi:
  `python scripts/smoke_live.py` (ağa çıkar, CI'da bloklamaz).

## Log/routing notları

- `X-Forwarded-For` yalnızca sunucu loopback'e bağlıyken dikkate alınır; aksi
  halde yoksayılır, bu yüzden dışarıdan sahte XFF istemci kimliğini değiştirmez.
- uvicorn `proxy_headers=True`, `forwarded_allow_ips="127.0.0.1"` ile başlar;
  reverse proxy localhost üzerinden bağlanmalıdır.
- Hız/eşzamanlılık sayaçları uçucudur; yeniden başlatmada sıfırlanır. Kalıcı
  metrik backendi yoktur.
