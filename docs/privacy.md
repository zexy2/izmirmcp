# Gizlilik ve veri işleme

Bu sunucu **salt okunurdur** ve kullanıcı hesabı tutmaz. Yine de hangi verinin
işlendiğini açıkça yazmak gerekir; aşağıdaki tablo koddan türetilmiştir
(`app/core/http_logging.py`, `app/core/api_auth.py`, `app/core/rate_limit.py`).

## Ne saklanır

| Veri | Nerede | Süre |
|---|---|---|
| İstemci başına hız sınırı sayacı | Süreç belleği (`ClientRateLimiter`) | Süreç ömrü |
| Eşzamanlılık sayacı | Süreç belleği | Süreç ömrü |
| API anahtarı **özeti** (SHA-256) | Süreç belleği | Süreç ömrü |
| GTFS tarife deposu | `IZMIR_MCP_DATABASE_PATH` (SQLite) | Sen silene kadar |
| Kaynak yanıt önbelleği | Süreç belleği | TTL (kaynak başına) |

Sunucu **hiçbir yere yazmaz**: veritabanı yok, kullanıcı tablosu yok, çerez yok,
oturum saklama yok.

## Ne saklanmaz

Erişim logu yalnızca şu alanları yazar:

```json
{"event": "http_request", "method": "POST", "path": "/mcp/",
 "status": 200, "duration_ms": 2.9}
```

- **Sorgu dizesi yazılmaz.** `?resource_id=...` gibi değerler loglanmaz.
- **Gövde yazılmaz.** Araç girdileri, koordinatlar ve adres aramaları loglanmaz.
- **Başlık yazılmaz.** `Authorization`, `Cookie`, `Mcp-Session-Id` görünmez.
- **API anahtarı hiçbir koşulda yazılmaz**; yalnızca SHA-256 özeti bellekte
  karşılaştırılır.

Logu tamamen kapatmak için: `IZMIR_MCP_ACCESS_LOG_ENABLED=false`.

## Üçüncü taraflara giden veri

Sunucu, yalnızca kullanıcının aradığı şehir verisini almak için yayıncı
kurumların uçlarına istek yapar. Bu isteklerde:

- kullanıcı kimliği, anahtarı veya oturumu **gönderilmez**;
- yalnızca arama parametreleri (koordinat, durak kimliği, tarih) gider;
- `User-Agent` sabittir: `izmir-mcp/0.1 (+https://github.com/; read-only city data client)`.

Yani yayıncı kurum, hangi IP'den hangi durağın sorulduğunu görebilir. Bu, her
açık veri istemcisinde kaçınılmazdır ve bu proje bir proxy/anonimleştirici
değildir.

## İstemci kimliği

Hız sınırı için istemci kimliği:

- Sunucu loopback'e bağlıysa **tek** `X-Forwarded-For` değeri (yerel reverse
  proxy beklenir);
- aksi halde doğrudan TCP bağlantı adresi.

`X-Real-IP`, `Forwarded`, `CF-Connecting-IP` **dikkate alınmaz**; virgüllü liste
ve yinelenen başlık reddedilir (spoofing testleri: `tests/test_http_security.py`).

## Veri kaynaklarının kendi politikaları

Bu belge yalnızca bu sunucunun davranışını tanımlar. Şehir verisinin tabi olduğu
lisans ve kullanım koşulları yayıncı kurumlara aittir; bkz.
[sources.md](sources.md).
