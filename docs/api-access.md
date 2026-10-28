# API erişimi ve anahtar yönetimi

Varsayılan kurulum **açıktır**: kimlik doğrulama kapalıdır, yalnızca istemci
başına hız sınırı uygulanır. Bu belge korumalı bir dağıtım için anahtar
üretimini, rotasyonunu ve kotayı açıklar.

## Anahtar üretimi

Anahtar 32–256 karakter, URL-güvenli (`A-Z a-z 0-9 . _ ~ -`) olmalıdır.
Önerilen üretim:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Anahtarları virgülle `IZMIR_MCP_API_KEYS` değişkenine verin:

```bash
export IZMIR_MCP_API_KEYS="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
```

Sunucu anahtarları **yalnızca SHA-256 özeti** olarak bellekte tutar; düz metin
hiçbir yerde saklanmaz veya loglanmaz (bkz. [privacy.md](privacy.md)).

## İstemci tarafı

```http
Authorization: Bearer <anahtar>
```

Eksik veya yanlış anahtar:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="izmir-mcp"
```

## Korumalı yollar

| Yol | Anahtar gerekir |
|---|---|
| `GET /healthz` | ❌ (liveness probe'ları için açık) |
| `GET /readyz` | ❌ (readiness probe'ları için açık) |
| `GET /status` | ✅ (sayaçlar ve yapılandırma sızdırmasın) |
| `/mcp`, `/mcp/*` | ✅ |

## Günlük kota

`IZMIR_MCP_API_KEY_DAILY_QUOTA` > 0 ise her anahtar için günlük istek kotası
uygulanır ve **SQLite'ta kalıcıdır**: sunucu yeniden başlasa da sayaç sıfırlanmaz.

```http
HTTP/1.1 429 Too Many Requests
Retry-After: <gece yarısına kalan saniye>
{"ok": false, "error_code": "quota_exceeded", ...}
```

Kota deposu okunamazsa **fail closed**: `503 quota_unavailable`. Böylece bozuk
bir disk sınırsız erişime dönüşmez.

Kota, bellek içi hız sınırından farklıdır:

| Koruma | Depolama | Amaç |
|---|---|---|
| Hız sınırı (60/sn) | Bellek | Ani patlamalar |
| Günlük kota | SQLite | Toplam kullanım bütçesi |

## Rotasyon

1. Yeni anahtarı listeye ekle, eskisini listede bırak.
2. İstemcileri yeni anahtara geçir.
3. Eski anahtarı listeden çıkar ve sunucuyu yeniden başlat.

Kota kayıtları anahtar **özetine** bağlıdır; rotasyon yeni bir sayaç başlatır
(beklenen davranış).

## Sınırlar

- Anahtar başına rol/izin yoktur: tüm araçlar salt okunurdur, her geçerli
  anahtar aynı yüzeye erişir.
- OAuth, döner token, iptal listesi yoktur; statik anahtar karşılaştırması.
- Anahtarlar yalnızca bellekte olduğu için değişiklik yeniden başlatma gerektirir.
