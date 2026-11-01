# Güvenlik denetimi — 2026-10-28

Yöntem: canlı sunucuya karşı saldırgan bakışla 23 saldırı denemesi. Bulgular
`tests/test_security_audit.py` içinde (14 test) kalıcı hale getirildi; düzeltmeler
sonrası hepsi yeşil.

## Bulgular ve düzeltmeler

### BULGU 1 — Derin JSON ile sunucuyu 500'e düşürme (DoS) — YÜKSEK

**Saldırı:**
```bash
python3 -c "print('['*5000+']'*5000)" | curl -X POST /mcp/ --data-binary @-
```

**Önce:** `HTTP 500`, logda `RecursionError: maximum recursion depth exceeded`.
Python'un `json` okuyucusu özyinelemeli; tek istek sunucuyu hata moduna sokuyor.

**Düzeltme:** `app/core/mcp_transport.py::_exceeds_depth` — ayrıştırmadan **önce**
yapısal iç içe derinlik sayılıyor (string içindeki parantezler sayılmıyor), sınır
`MAX_JSON_DEPTH = 32`. Ayrıca `json.loads` çağrısı `RecursionError`'ı da yakalıyor.
Sonuç: `400 / -32700`.

### BULGU 2 — `/status` ve `izmir_health` ham API uçlarını sızdırıyor — ORTA

**Kanıt:**
```json
{"catalog": "https://acikveri.bizizmir.com/api/3/action",
 "open_data_api": "https://openapi.izmir.bel.tr/api"}
```

Bu, projenin kendi kuralını ihlal ediyor ("kullanıcıya API ucu gösterme") ve
çağıranı bu sunucuyu atlayıp doğrudan kaynağı kazımaya teşvik ediyor. `/status`
kimlik doğrulaması kapalıyken **anahtarsız** erişilebilir.

**Düzeltme:** `izmir_health` artık yalnızca insan sayfalarını döndürüyor
(`https://acikveri.bizizmir.com`, `https://www.izmir.bel.tr`). `/status` ham uç
yerine `configuration` özeti veriyor (auth durumu, kota, origin sayısı).

### BULGU 3 — Dış isteklerde körlemesine redirect takibi (SSRF) — YÜKSEK

**Önce:** `httpx.AsyncClient(follow_redirects=True)`.

Bir kaynak ele geçirilirse veya DNS/orta adam saldırısı olursa, `302 Location:
http://169.254.169.254/latest/meta-data/` isteği **iç ağa** yönlendirilirdi.
Bulut ortamında bu, bulut metadata kimlik bilgilerine erişim demektir.

**Düzeltme:** `app/connectors/http.py::_get_same_origin` — en fazla 3 redirect,
yalnızca **aynı şema + aynı host** kalırsa takip edilir; farklı origin
`SourceError` fırlatır. `follow_redirects=False` + elle takip.

**Regresyon:** canlı smoke 30/30 geçmeye devam ediyor (gerçek kaynaklarda
cross-origin redirect yok).

### BULGU 4 — Boolean, sayı doğrulamasından geçiyor — ORTA

**Saldırı:**
```json
{"name": "izmir_nearby", "arguments": {"lat": true, "lon": 27.1}}
```

**Önce:** `ok: true`, boş sonuç. Python'da `True` bir `int` olduğu için
`-90 <= True <= 90` geçiyor; pydantic `float | None` da `True`'yu **`1.0`'a
çeviriyor**, yani hata izlenebilirliği kayboluyor.

**Etki:** kullanıcı "İzmir'de otopark yok" sanıyor; `freshness: fresh`,
`result_info.matched: null` — tutarsız ve yanıltıcı.

**Düzeltme (iki katman):**
1. `app/core/types.py` — `Number`/`Count` tipleri `BeforeValidator` ile boolean'ı
   şema seviyesinde reddediyor (string→sayı dönüşümü korunuyor).
2. `app/core/validation.py::_require_number` — `validate_lat_lon`,
   `validate_radius`, `validate_limit` boolean'ı reddediyor.
3. İzmir dışı koordinatta (ör. `lat=1.0`) sonuç boş dönse bile açık uyarı
   eklendi: "boş sonuç 'İzmir'de hizmet yok' kanıtı değildir".

## Savuşturulan saldırılar (bulgu değil)

| # | Saldırı | Sonuç |
|---|---|---|
| 1 | Path traversal (`/mcp/../../etc/passwd`, `%2e%2e%2f`) | 404 |
| 2 | Metot kaçağı (PUT/PATCH/TRACE/DELETE/HEAD) | 405 |
| 3 | Command injection (`; cat /etc/passwd`) | veri olarak ele alındı, 0 sonuç |
| 4 | SQL injection (`sort: "ADI; DROP TABLE"`) | `validation_error` |
| 5 | 5 MB gövde | 413 |
| 6 | `/status` yol sızıntısı (`/Users/`, `.sqlite3`, `.data`) | temiz |
| 7 | Hata mesajında traceback/yol | temiz |
| 8 | Bilinmeyen metod (`admin/shutdown`) | `-32601` |
| 9 | Kaynak metni prompt injection | veri olarak döndü, warnings korundu |
| 10 | ZIP bomb | üye başına byte bütçesi |
| 11 | Eşzamanlı indeks yazımı (8 paralel) | SQLite kilidi, tutarlı |
| 12 | 100k karakter query | 0.01 sn, sınır yok ama zarar yok |
| 13 | 5000 filtre anahtarı | reddedildi (10 anahtar sınırı) |
| 14 | 1000 mesajlık batch | 400 |
| 15 | `text/plain` gövde | 400 |
| 16 | `limit=999999`, `radius_m=999999999` | `validation_error` |
| 17 | `limit=1e400` (overflow) | şema reddi |
| 18 | Dışarıdan `eval`/`exec`/`pickle`/`os.system` | kodda yok (testle kilitli) |

## Kalan riskler (kabul edilen)

| Risk | Not |
|---|---|
| Hız sınırı süreç içi | Çok işçili dağıtımda işçi başına bütçe; reverse proxy gerekir |
| `/readyz` ve `/healthz` anahtarsız | Probe'lar için gerekli; yol/detay sızdırmıyor |
| Kaynak metni sanitize edilmiyor | JSON çıktısı olduğu için XSS riski düşük; tüketici ajanın talimat olarak yorumlamaması gerekir (`instructions` bunu söylüyor) |
| DNS rebinding koruması | SDK'nın taşıma güvenliğine bırakılmış; loopback dışı bağlanmada reverse proxy önerilir |
| Statik API anahtarı | OAuth/döner anahtar yok; rotasyon yeniden başlatma gerektirir |

## Doğrulama

- `pytest`: **518 passed** (14 güvenlik testi)
- Protokol smoke: 32/32
- Resmî conformance: 5/5
- Canlı smoke: exit 0 (redirect düzeltmesi gerçek kaynakları bozmadı)
