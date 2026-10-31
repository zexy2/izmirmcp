# Yanıt Sözleşmesi

Bu belge her MCP aracının döndürdüğü zarfın **tek doğru** tanımıdır. Kaynağı
`app/core/envelope.py` ve `app/core/validation.py` dosyalarıdır; davranış
değişirse önce kod, sonra bu belge güncellenir. `tests/test_docs.py` bu belgeyi
koda karşı kilitler.

## Zarf

Her araç çıktısı aynı Pydantic modeline (`ResponseEnvelope`) göre doğrulanır ve
MCP `structured_output` olarak döner. Düz Python işleyicileri sözlük döndürür;
`app/mcp/structured.py` bunu modele çevirir. Aşağıdaki alanlar **her zaman**
mevcuttur:

| Alan | Tip | Anlamı |
|---|---|---|
| `ok` | bool | Araç başarıyla veri döndürdüyse `true`; hata zarfında `false`. |
| `summary` | string | İnsan için tek satırlık özet. Sayılar ve kapsam buradadır. |
| `data` | list[object] | Kayıt listesi. Hata zarfında genelde boş. |
| `freshness` | object | Verinin tazeliği ve kaynak zaman damgası (aşağıda). |
| `sources` | list[object] | Kanıt kaynakları; atıf ve kamuya açık URL (aşağıda). |
| `limits` | list[string] | Bu yanıtta uygulanan sınırlar (`limit=10`, `realtime=false`…). |
| `warnings` | list[string] | Dürüstlük uyarıları; boş sonucun "hiç yok" olmadığı burada söylenir. |
| `next_queries` | list[string] | Önerilen sonraki araç çağrıları. |
| `error` | object \| null | Hata taksonomisi (aşağıda). Başarılı yanıtta `null`. |
| `result_info` | object | Dönen/eşleşen/kesilme bilgisi (aşağıda). |
| `disclaimer` | string \| null | Sabit iki dilli uyarı: veri resmî değildir, İBB açık verisinden gelir, gecikmeli/hatalı olabilir. |

### `freshness`

| Alan | Tip | Anlamı |
|---|---|---|
| `status` | `fresh` \| `stale` \| `unknown` \| `broken` | Verinin tazelik sınıfı. |
| `retrieved_at` | ISO-8601 UTC | Bu sunucunun veriyi aldığı an. |
| `source_updated_at` | string \| null | Kaynağın kendi zaman damgası. GTFS'te `calendar_end` taşır. |
| `ttl_seconds` | int \| null | Bu verinin uygulama içi önbellek ömrü. |

- `fresh` — kaynaktan yeni okundu (veya TTL içinde önbellekte).
- `stale` — önbellekteki eski kopya kullanıldı ya da kaynak penceresi geçmiş
  (örn. ESHOT GTFS takvimi 2026-10-09'da bitti).
- `unknown` — araç yerel metadata döndürür, kaynak tazeliği iddia edilmez.
- `broken` — hata zarfı; veri okunamadı.

`izmir_health` ve `izmir://*` kaynakları **`fresh`** döner ama bu yalnızca yerel
hazırlık metadata'sıdır; kaynak sağlığı değildir (`upstream_health:
"not_checked"`).

### `sources[]`

| Alan | Tip | Anlamı |
|---|---|---|
| `name` | string | Kaynak adı. |
| `publisher` | string | Yayıncı kurum (varsayılan İzmir Büyükşehir Belediyesi). |
| `url` | string \| null | **Yalnızca kamuya açık sayfa**. API uçları ve dosya uzantılı adresler `null`'a indirilir. |
| `license` | string \| null | Biliniyorsa lisans. Çoğu şehir kaynağında `null`: açık erişim lisans izni değildir. |
| `dataset_id` / `resource_id` | string \| null | CKAN kimlikleri. |
| `scope` | string \| null | Veri türü (`stops`, `published_timetable`, `live_vehicle_positions`…). |
| `source_updated_at` | string \| null | Kaynağın bildirdiği güncelleme. |

`url` serileştirilirken `public_page_url()` uygulanır: `http://`, `api.*`/`*.api`
host'ları, `/api/`, `/download/`, `/docs/` yolları ve `.csv`/`.json`/`.zip` gibi
dosya uzantıları `null` döner. Bu, ajanların kullanıcıya API ucu göstermesini
engeller. Atıf daima `name` + `publisher` ile yapılır.

### `result_info`

| Alan | Tip | Anlamı |
|---|---|---|
| `returned` | int | `data` içindeki kayıt sayısı. |
| `matched` | int \| null | Filtreye uyan toplam (kaynağın bildirdiği). Bilinmiyorsa `null`. |
| `truncated` | bool \| null | `matched > returned` ise `true`. Kesilme bilinmiyorsa `null`. |
| `scope` | string | Sorgu modu (aşağıdaki tablo). |
| `next_step` | string \| null | Kesilme varsa limiti artırma/daraltma önerisi. |

`scope` değerleri (koddan):

| `scope` | Üreten araç/mode |
|---|---|
| `data` | Varsayılan (eşleşme sayısı verilmeyen araçlar). |
| `error_details` | Her hata zarfı. |
| `bbox` | `izmir_nearby` ve `izmir_city_services_nearby` `bbox` modu. |
| `district` | `izmir_nearby` ve `izmir_city_services_nearby` `district` modu. |
| `radius` | `izmir_nearby` ve `izmir_city_services_nearby` yarıçap modu. |
| `mobility_nearby` | `izmir_mobility_nearby` ulaşım özeti; sayımlar gösterilen satırlara aittir (`counts_scope=shown`). |
| `route_detail` | `izmir_bus_routes(detail=true)`. |
| `published_departures` | `izmir_bus_departures` (`stop_id` modu). |
| `published_departures_near` | `izmir_bus_departures` `lat`/`lon` yarıçap modu. |
| `stop_candidates` | `izmir_bus_departures(stop_query=...)` durak keşfi; kalkış değildir. |
| `operator_notices` | `izmir_transport_disruptions`. |
| `traffic_history` | `izmir_traffic_history`. |
| `sql` | `izmir_datastore_query`. |
| `outside_coverage` | `izmir_nearby`/`izmir_mobility_nearby` koordinatı İzmir il sınırları dışında. |

`truncated` **bilinmiyorsa** `result_info` "tam toplam değil" notu bırakır;
kesilmişse "limit içinde artır veya filtreyi daralt, bu tam toplam değil"
notu bırakır. Boş `data` tek başına yokluk kanıtı değildir; `warnings` okunur.

## Hata taksonomisi

Hata zarfları exceptionsızmaz. `ok=false`, `error` dolu, `freshness.status`
genelde `broken` (kaynak erişimi) veya `stale` (yerel/geçersiz girdi ayrımı için
`fresh` kalabilir) olur.

| `error.code` | Ne zaman | `temporary` | `error.field` |
|---|---|---|---|
| `validation_error` | Girdi geçersiz (tür, aralık, birbirini dışlayan mod). | `false` | Hatalı alan adı. |
| `not_found` | CKAN `dataset_id`/`resource_id` yok. | `false` | `dataset_id` veya `resource_id`. |
| `source_unavailable` | Kaynak HTTP hatası/500, bozuk gövde, erişilemeyen uç. | `true` | `null`. |
| `source_timeout` | Kaynak zaman aşımına uğradı. | `true` | `null`. |
| `source_rate_limited` | Kaynak HTTP 429 döndü. | `true` | `null`. |
| `request_failed` | Kod verilmemiş genel hata (iç varsayılan). | `false` | `null`. |

`temporary=true` ise `error.next_step` "retry later" önerir; aksi halde
"girdileri ve yayımlanan limitleri gözden geçir" der. Bir kaynağın **kasıtlı
olarak kullanılamaz** olduğu durumlar (İZSU arıza: HTTP 500; İZBAN duyuruları:
302→FileNotFound/404) uydurma veri yerine açık `source_unavailable` döner.

### Doğrulama hatalarının kuralları

`InputValidationError` alan adı taşır. En sık alanlar:

- `lat`/`lon` — birlikte verilmelidir; `lat` ∈ [-90, 90], `lon` ∈ [-180, 180].
- `bbox` — `[min_lon, min_lat, max_lon, max_lat]`, sonlu, dört eleman,
  `min < max`; sıfır genişlik/yükseklik reddedilir.
- `radius_m` — pozitif ve `max_radius_m` (varsayılan 5000) sınırında; yalnızca
  `lat/lon` veya `place` moduyla.
- `limit` — pozitif ve `max_limit` (varsayılan 50) sınırında.
- `types`/`kinds` — boş olmayan, tanımlı alt küme.
- `filters` — nesne; en fazla 10 anahtar; anahtar `[\w .:-]+`; değer skaler veya
  en fazla 20 skaler liste; metin 200 karaktere kırpılır. Bilinmeyen sütun adı
  `validation_error` + `filters` döner.
- `place` — yayımlanmış referans noktası olmalı; `lat/lon` ile birleştirilemez.
- `at` — `HH:MM` (Europe/Istanbul) veya ISO-8601.
- `date` — `YYYY-MM-DD`.
- `direction` — `0` veya `1`, yalnızca `detail=true` ile.

## HTTP yüzeyi hataları (zarf dışı)

`/mcp` üzerindeki koruma katmanları zarf **değil** HTTP durum kodu ve küçük bir
gövde döner: `{"ok": false, "error_code": "<kod>", "summary": "<metin>"}`.
Ayrıntı ve varsayılanlar [deployment.md](deployment.md) içindedir. Zarf
sözleşmesi yalnızca **araç çağrıları** için geçerlidir.

## Sözleşme testleri (P4)

Zarf sözleşmesi tahmin değil, test edilir:

| Test | Neyi kilitler |
|---|---|
| `tests/test_contract_conformance.py` | 22 aracın her biri için `set(payload) == ResponseEnvelope.model_fields`; `result_info.returned == len(data)`; `ok=true` iken `error=null`; `ok=false` iken `scope="error_details"`. |
| aynı dosya, hata parametreleri | Geçersiz girdi ağa çıkmadan `validation_error` + `error.field` + `temporary=false` döner. |
| aynı dosya, yeniden oynatma | Kaydedilmiş kaynak yanıtı 503/500 olarak tekrar oynatıldığında her araç ya tipli `source_*` hatası ya da `warnings` taşıyan kısmi sonuç döner; asla exception sızmaz. |
| `tests/test_discovery_surface.py` | `output_schema` `ResponseEnvelope` şemasıyla aynı alanları ve aynı `required` kümesini taşır; resources/prompts şemaları geçerlidir. |

Testler konnektörü `httpx.MockTransport` ile değiştirir; ağ yoktur. Bu, **alan
şeklinin ve hata taksonomisinin** doğrulamasıdır, kaynağın bugün aynı veriyi
yayımladığının kanıtı değildir — o kanıt `scripts/smoke_live.py`'den gelir.

### 429 etiketi

Tüm servisler kaynak arızalarını ortak `source_failure_envelope` yardımcısıyla
çevirir: HTTP 429 `source_rate_limited`, zaman aşımı `source_timeout`, diğer
arızalar `source_unavailable`. Üçü de `temporary=true` taşır. Bu etiket
`tests/test_contract_conformance.py` ile kilitlidir.
