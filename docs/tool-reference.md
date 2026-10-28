# Araç Referansı

Bu belge 17 salt okunur MCP aracının girdi/çıktı sözleşmesini gerçek koddan
(`app/mcp/server.py` ve `app/services/*`) türetir. Zarf alanları
[response-contract.md](response-contract.md) içindedir. Tüm araçlar `read_only`,
`idempotent`, `open_world` işaretlidir ve `structured_output` taşır.

Ortak varsayılanlar: `default_limit=10`, `max_limit=50`, `max_radius_m=5000`.
Limit verilmezse `default_limit` uygulanır; aşarsa `validation_error` (`limit`).

Keşif kaynakları (salt okunur, ağ çağrısı yapmaz): `izmir://coverage`,
`izmir://sources`, `izmir://schema/catalog`. İstemci iş akışları (prompt'lar):
`gunun_ozeti`, `veri_kesfi`, `toplu_ulasim`, `otobus`, `pazar_ve_duyurular`,
`sehir_hizmetleri`.

## Katalog (CKAN)

### `izmir_search_datasets`
İzmir Açık Veri kataloğunda konu araması.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `query` | string | evet | Aranacak konu. |
| `formats` | string[] \| null | hayır | En fazla 10 format filtresi (örn. `CSV`). |
| `limit` | int \| null | hayır | Dönen veri seti sayısı. |

Çıktı: her veri seti için özet + `relevance` (eşleşen terimler, `has_datastore`).
`matched` kaynağın toplam sayısıdır. Katalog metadata'sı kaynağın sorgulanabilir
olduğunun kanıtı değildir.

### `izmir_get_dataset`
Bir veri setinin metadata'sı ve kaynak listesi.

| Girdi | Tip | Zorunlu |
|---|---|---|
| `dataset_id` | string | evet |

Bilinmeyen id → `not_found` (`field=dataset_id`).

### `izmir_get_resource_schema`
DataStore kaynağının kolon şeması.

| Girdi | Tip | Zorunlu |
|---|---|---|
| `resource_id` | string | evet |

Bilinmeyen id → `not_found` (`field=resource_id`). `izmir_query_resource`'tan
önce çağrılmalıdır.

### `izmir_query_resource`
DataStore kayıtlarını güvenli filtre + limitle getirir. SQL (`datastore_search_sql`)
bilinçli olarak yoktur.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `resource_id` | string | evet | DataStore aktif kaynak. |
| `filters` | object \| null | hayır | En fazla 10 anahtar; değerler skaler/liste. |
| `limit` | int \| null | hayır | Kayıt sayısı. |

Filtre anahtarı şemadaki kolonlarda yoksa `validation_error` (`field=filters`).
`matched` kaynağın `total` değeridir.

## Yakınlık ve hizmetler

### `izmir_nearby`
Otopark, nöbetçi eczane, metro/İZBAN istasyonu, vapur iskelesi ve ESHOT durağı.
**Tek** konum modu: `lat`+`lon` veya `place`, ya da `bbox`, ya da `district`.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `lat`/`lon` | number \| null | birlikte | Yarıçap modu; `place` ile birlikte kullanılamaz. |
| `place` | string \| null | hayır | Yayımlanmış ilçe/mahalle referans noktası (örn. `Konak`, `Abdi İpekçi`). Varsayılan yarıçap `max_radius_m`. |
| `place_district` | string \| null | hayır | Aynı adı taşıyan mahalleleri ayırmak için ilçe ipucu (örn. `Atatürk` + `Bornova`). Yalnızca `place` ile geçerli. |
| `bbox` | number[] \| null | hayır | `[min_lon, min_lat, max_lon, max_lat]`; kenarlar dahil. |
| `district` | string \| null | hayır | İlçe geneli; pratikte yalnızca eczane eşleşir. |
| `types` | enum[] \| null | hayır | `parking`, `pharmacy`, `metro_station`, `izban_station`, `ferry_pier`, `bus_stop`. Varsayılan hepsi. |
| `radius_m` | int \| null | hayır | Yalnızca `lat/lon`/`place`; varsayılan 1500 (`place` için 5000). |
| `limit` | int \| null | hayır | |

- Yarıçap modu: `distance_m` hesaplanır, sonuçlar mesafeye göre sıralanır.
- `bbox` modu: `distance_m` null; sıralama tür + ad; kesilme `result_info`'da.
- `district` modu: `distance_m` null; eşleşme kaynağın bölge metniyle, idari
  sınır değildir. İlçe etiketi yayımlamayan türler uyarıyla atlanır; tüm
  seçili türler elenirse `validation_error` (`field=types`).
- `place` çözümlenemezse `validation_error` (`field=place`). Referans noktası
  yaklaşıktır; uyarı eklenir.
- Mahalle adları 1.219 kayıtlık yayımlanmış muhtarlık envanterinden gelir.
  Aynı ad birden çok ilçede geçiyorsa (`Atatürk` 17 ilçede) `place_district`
  zorunludur; aksi halde `validation_error` adayları listeler.

### `izmir_city_services_nearby`
WizmirNET WiFi, İzmirim Kart dolum noktası ve kütüphaneler. `izmir_nearby` ile
aynı üç konum modu.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `kinds` | enum[] \| null | hayır | `wifi`, `izmirim_card`, `library`. Varsayılan hepsi. |
| `kinds`, `lat`, `lon`, `place`, `place_district`, `bbox`, `district`, `radius_m`, `limit` | — | — | `izmir_nearby` ile aynı konum kuralları. |

Kapsam farkı: `bbox` modunda **yalnızca** WiFi ve İzmirim Kart aranır; kütüphane
katmanı koordinat yayımlamadığı için dikdörtgene hiç girmez. `district`
eşleşmesi kaynağın ilçe alanı ya da adres metniyledir. Yinelenen kayıtlar
tekilleştirilir ve sayısı uyarıda bildirilir. Tüm katmanlar statik snapshot'tır.

## Su ve hava

### `izmir_water_status`
İZSU baraj dolulukları ya da arıza akışının kullanılamaz olduğunun bildirimi.

| Girdi | Tip | Zorunlu | Değerler |
|---|---|---|---|
| `kind` | string | hayır | `dams` (varsayılan) \| `faults` |
| `limit` | int \| null | hayır | |

`kind="faults"` **her zaman** `source_unavailable` döner (İZSU ucu HTTP 500,
2026-10-28). `dams` yayımlanmış CSV'den okunur, doluluk yüzdesine göre azalan
sıralanır ve gecikebilir.

### `izmir_air_quality`
Tarih/istasyon filtreli hava kalitesi ölçümleri.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `date` | string \| null | hayır | `YYYY-MM-DD`; varsayılan bugün. |
| `station` | string \| null | hayır | İstasyon adı (normalize eşleşme). |
| `limit` | int \| null | hayır | |

Kaynak koordinat ve birim yayımlamaz (`unit` null); `observed_at` istenen
tarihten bir gün geride olabilir. AQI hesabı yapılmaz.

## Toplu taşıma tarifeleri

### `izmir_transit_stations`
Metro istasyonu, İZBAN istasyonu veya İZDENİZ iskelesi listesi.

| Girdi | Tip | Zorunlu | Değerler |
|---|---|---|---|
| `mode` | string | evet | `metro` \| `izban` \| `izdeniz` |
| `limit` | int \| null | hayır | |

### `izmir_transit_schedule`
Yayımlanmış tarife: metro sıklığı, İZBAN/İZDENİZ seferleri.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `mode` | string | evet | `metro` \| `izban` \| `izdeniz` |
| `from_id` | int \| null | moda göre | İZBAN zorunlu; İZDENİZ `pier_id` yerine. |
| `to_id` | int \| null | moda göre | İZBAN zorunlu; İZDENİZ `pier_id` yerine. |
| `pier_id` | int \| null | moda göre | Yalnızca İZDENİZ; `from_id`/`to_id` ile birleşmez. |
| `day` | int | hayır | 1–7; **kaynağın kendi gün kimliği**, haftanın günü varsayılmaz. |

- `metro`: istasyon çifti kabul etmez; saat aralığı + sefer sıklığı tablosudur.
- `izban`: `from_id` ve `to_id` zorunlu.
- `izdeniz`: `pier_id` ya da `from_id`+`to_id` zorunlu.

Tarifeler canlı kalkış/gecikme/ETA değildir.

## ESHOT otobüsleri

### `izmir_bus_stops`
Durakları ada göre ara veya koordinat çevresinde listele.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `query` | string \| null | biri | Durak adı veya id; aksan/büyük-küçük harf duyarsız. `lat/lon` ile birleşmez. |
| `lat`/`lon` | number \| null | biri | Birlikte; `query` ile birleşmez. |
| `radius_m` | int \| null | hayır | Yalnızca `lat/lon`; varsayılan 1000. |
| `limit` | int \| null | hayır | |

İkisi de yoksa `validation_error` (`field=query`).

### `izmir_bus_arrivals`
Bir durağa yaklaşan otobüslerin anlık konumu ve kalan durak sayısı.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `stop_id` | string | evet | Yayımlanmış durak listesinden. |
| `limit` | int \| null | hayır | |

Bilinmeyen `stop_id` → `validation_error` (`field=stop_id`); bilinen ama GTFS'te
olmayan durak `departures`'ta ayrıca reddedilir. Kaynak **ETA/dakika
yayımlamaz**. Boş yanıt "sefer yok" kanıtı sayılmaz; uyarı eklenir.

### `izmir_bus_departures`
Bir durağın yayımlanmış GTFS planlı kalkışları.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `stop_id` | string | evet | Yayımlanmış ESHOT durağı. |
| `at` | string \| null | hayır | `HH:MM` (Europe/Istanbul) veya ISO-8601; varsayılan şimdi. |
| `line` | string \| null | hayır | Hat kodu filtresi. |
| `limit` | int \| null | hayır | |

Planlı tarifedir; canlı kalkış/ETA değildir. Her yanıt `calendar_end` taşır ve
takvim bittiyse (2026-10-09) tarih dışı sorgular boş + uyarı döner. `pickup_type=1`
satırları elenir; `25:xx` saatleri doğru güne yerleştirilir. İlk çağrı yerel
SQLite deposunu (~2,1M satır) kurar.

### `izmir_bus_routes`
ESHOT GTFS hat özeti; `detail=true` ile hattın yönleri, sıralı durakları ve
durak varyantları.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `query` | string \| null | `detail` için evet | Hat kodu/adı; `detail` modunda tam kod/route_id. |
| `detail` | bool | hayır | `true` → durak desenleri. |
| `direction` | string \| null | hayır | `0`/`1`; yalnızca `detail=true`. |
| `limit` | int \| null | hayır | `detail` modunda uygulanmaz. |

`detail=false`: hat listesi + `calendar_end` ve eskime uyarısı.
`detail=true`: her `direction_id` için yayımlanmış **tüm** desenler ayrı tutulur
(halka hatları ve kısa turlar birleştirilmez); `headsign` yoksa yön adı
uydurulmaz. Birden çok GTFS rotası eşleşirse route_id ile ayrıştırma istenir.
Canlı kalkış değildir.

## Şehir katmanları

### `izmir_market_schedule`
Semt pazarı takvimi.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `day` | string \| null | hayır | `pazartesi..pazar`, `bugun`, `yarin`. |
| `district` | string \| null | hayır | İlçe adı (kaynağın ilçe alanında). |
| `lat`/`lon` | number \| null | birlikte | Yarıçap modu. |
| `radius_m` | int \| null | hayır | Yarıçap modunda; varsayılan 1500. |
| `limit` | int \| null | hayır | |

Kurulma günü yalnızca serbest metinden (`ACIKLAMA`) çıkarılır; gün
çıkmayanlar `day_confidence="unknown"` ile listelenir ve uydurulmaz.
Açılış saati/durumu yayımlanmaz.

### `izmir_transport_disruptions`
EShot, Metro ve İZDENİZ duyuruları.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `operator` | enum \| null | hayır | `eshot`, `metro`, `izdeniz`, `izban`. Verilmezse ilk üçü birleşir. |
| `line` | string \| null | hayır | Hat filtresi. |
| `active_only` | bool | hayır | `active` hesaplanabilen satırlara göre filtre. |
| `limit` | int \| null | hayır | |

`active` **yalnızca ESHOT** satırlarında hesaplanır (geçerlilik penceresi
yayımlar); Metro/İZDENİZ'de null ("bilinmiyor"). `operator="izban"` her zaman
`source_unavailable` döner (erişilebilir duyuru akışı yok). Okunamayan operatör
sonuçtan düşer ve uyarı eklenir; "aksaklık yok" sonucu çıkarılmaz. Bunlar
duyurudur, canlı gecikme/araç telemetrisi değildir.

### `izmir_health`
Yerel hazırlık ve yayımlanan limitler. Girdi yoktur. Kaynak sağlığı ölçmez;
`freshness.status="fresh"` yalnızca yerel runtime içindir.
