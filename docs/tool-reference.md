# Araç Referansı

Bu belge 35 salt okunur MCP aracının girdi/çıktı sözleşmesini gerçek koddan
(`app/mcp/server.py` ve `app/services/*`) türetir. Zarf alanları
[response-contract.md](response-contract.md) içindedir. Tüm araçlar `read_only`,
`idempotent`, `open_world` işaretlidir ve `structured_output` taşır.

Ortak varsayılanlar: `default_limit=10`, `max_limit=50`, `max_radius_m=5000`.
Limit verilmezse `default_limit` uygulanır; aşarsa `validation_error` (`limit`).

Keşif kaynakları (salt okunur, ağ çağrısı yapmaz): `izmir://coverage`,
`izmir://sources`, `izmir://schema/catalog`. İstemci iş akışları (prompt'lar):
`gunun_ozeti`, `veri_kesfi`, `toplu_ulasim`, `otobus`, `pazar_ve_duyurular`,
`sehir_hizmetleri`, `nobetci_eczane`.

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
DataStore kayıtlarını güvenli filtre, serbest metin arama ve sıralamayla getirir.
Sunucu tarafı SQL (`datastore_search_sql`) bu portalda **yoktur** (`"Action name
not known"`, 2026-10-28) ve kabul edilmez. Analitik sorgular için ayrı
`izmir_datastore_query` aracı, izin verilen kaynağın tamamını yerel kopyaya alıp
orada sınırlı SELECT çalıştırır.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `resource_id` | string | evet | DataStore aktif kaynak. |
| `filters` | object \| null | hayır | Tam eşleşme; en fazla 10 anahtar, skaler/liste değer. |
| `search` | string \| null | hayır | Sunucu tarafı serbest metin (`q`); en fazla 200 karakter, SQL değil. |
| `sort` | string \| null | hayır | `KOLON` veya `KOLON asc\|desc`; kolon şemada olmalı. |
| `limit` | int \| null | hayır | Kayıt sayısı. |

- Filtre anahtarı şemada yoksa `validation_error` (`field=filters`).
- Sıralama deseni `KOLON [asc|desc]` biçiminde değilse `validation_error`
  (`field=sort`); geçerli desen ama kolon şemada yoksa yine `validation_error`
  (`field=sort`). İkisi de ağa çıkmadan reddedilir.
- `search` boşlukları normalize edilir; 200 karakteri aşan veya kontrol
  karakteri içeren değer reddedilir (`field=search`).
- `matched` kaynağın `total` değeridir.

### `izmir_datastore_query`
İzin verilen bir DataStore kaynağının **tam** ve sınırlı yerel kopyası üzerinde tek
bir SELECT çalıştırır. Kaynak indirilmeden veya kısmi kopyayla toplam üretilmez.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `resource_id` | string | evet | `IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS` listesindeki bir kaynak. |
| `sql` | string | evet | `records` tablosu üzerinde tek SELECT; en fazla 4096 karakter. |
| `limit` | int \| null | hayır | Sonuç satırı; `max_limit` ile 100'ün küçüğü. |

- Tablo adı yalnızca `records`; JOIN, alt sorgu, CTE, UNION, pencere fonksiyonu,
  yazma ve allowlist dışı fonksiyon reddedilir (`validation_error`, `field=sql`).
- İzin listesinde olmayan kaynak ağa çıkmadan reddedilir (`field=resource_id`).
- Kaynak toplamı satır/byte bütçesini aşarsa, sayfa toplamı değişirse veya
  `_id` sırası bozulursa `source_unavailable` döner; **kısmi toplam üretilmez**.
- Motor ayrı bir bellek içi SQLite'tir; uygulama veritabanına erişemez.
- `freshness` kopyanın alınma zamanıdır, satırların yaşı değildir.
- Sonuç limiti kesilirse `result_info.truncated=true` ve uyarı eklenir.

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
| `types` | enum[] \| null | hayır | `parking`, `pharmacy`, `metro_station`, `izban_station`, `ferry_pier`, `bus_stop`, `taxi_stand`, `charging_station`. Varsayılan hepsi. |
| `radius_m` | int \| null | hayır | Yalnızca `lat/lon`/`place`; varsayılan 1500 (`place` için 5000). |
| `limit` | int \| null | hayır | |

- Yarıçap modu: `distance_m` hesaplanır, sonuçlar mesafeye göre sıralanır;
  kesilme `result_info.matched/truncated` ile bildirilir.
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

### `izmir_mobility_nearby`
Yakındaki ulaşım seçeneklerini tek zarfta cevaplar.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `lat` | number \| null | konum modu | `lon` ile birlikte. |
| `lon` | number \| null | konum modu | |
| `place` | string \| null | konum modu | Yayımlanmış ilçe/mahalle referans noktası; adres geocoding değildir. |
| `place_district` | string \| null | hayır | Yalnızca `place` ile; belirsiz adı ilçeyle çözer. |
| `radius_m` | int \| null | hayır | Varsayılan 1000, üst sınır `max_radius_m`. |
| `limit` | int \| null | hayır | Gösterilen satır sayısı; özet sayımları da bu satırlara aittir. |

`izmir_nearby` üzerine ince bir ön ayardır: aynı mekânsal indeks, aynı satır
şekli, aynı hata taksonomisi. Yalnızca ulaşım katmanlarını alır (metro, İZBAN,
vapur iskelesi, ESHOT durağı, taksi durağı, şarj istasyonu, otopark), mesafeye
göre sıralar ve `summary` içinde tür başına sayım verir. İki upstream bileşeni
**dürüstçe kapsamaz** ve `warnings`'te söyler: hava kalitesi istasyonları
(İzmir kaynağı koordinat yayımlamıyor) ve canlı trafik indeksi (`404`).
`counts_scope=shown` sınırı, sayımların `limit` sonrası gösterilen satırlara ait
olduğunu belirtir; sonuç kesildiğinde `result_info.matched` tüm eşleşmeyi,
`summary` ise "Toplam N eşleşmeden ilk M gösteriliyor" notunu verir.
Eczane/WiFi/kart/kütüphane noktaları bu özete girmez.

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
Bir durağın ya da bir nokta çevresindeki durakların yayımlanmış GTFS planlı
kalkışları; ayrıca durak adından kimlik keşfi.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `stop_id` | string \| null | modlardan biri | Yayımlanmış ESHOT durağı. |
| `stop_query` | string \| null | modlardan biri | Durak adı/kimliğiyle arama. **Kalkış değil**, durak adayları döner (`match=exact\|fuzzy`). Bu modda `at` ve `line` reddedilir. |
| `lat` | number \| null | modlardan biri | `lon` ile birlikte; çevredeki durakların kalkışları. |
| `lon` | number \| null | modlardan biri | |
| `radius_m` | int \| null | hayır | Yalnızca `lat`/`lon` ile; varsayılan 500, üst sınır `max_radius_m`. En yakın 25 durak sorgulanır. |
| `at` | string \| null | hayır | `HH:MM` (Europe/Istanbul) veya ISO-8601; varsayılan şimdi. |
| `line` | string \| null | hayır | Hat kodu filtresi; `stop_query` ile kullanılamaz. |
| `limit` | int \| null | hayır | Tek durakta o durağın, yarıçap modunda **tüm durak kümesinin** toplam sınırı. |

Tam olarak bir hedef modu verilir (`stop_id`, `stop_query` ya da `lat`+`lon`).
Planlı tarifedir; canlı kalkış/ETA değildir. Her yanıt `calendar_end` taşır ve
takvim bittiyse (2026-10-09) tarih dışı sorgular boş + uyarı döner. `pickup_type=1`
satırları elenir; `25:xx` saatleri doğru güne yerleştirilir. Yarıçap modunda
satırlar `stop_id`, `stop_name` ve kuş uçuşu `distance_m` taşır; yarıçapta hiç
durak yoksa tarife deposu hiç açılmaz (boş yanıt + uyarı). `stop_query` modu da
tarife deposunu kurmaz. İlk kalkış sorgusu yerel SQLite deposunu (~2,1M satır)
kurar.

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

### `izmir_neighborhood_profile`
Yayımlanmış nüfus ve bina sayısı katmanlarından mahalle profili.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `neighborhood` | string \| null | `district` yoksa | Mahalle adı (muhtarlık envanteri). |
| `district` | string \| null | `neighborhood` yoksa | İlçe; tek başına verilirse ilçedeki tüm mahalleleri listeler. |
| `limit` | int \| null | hayır | |

`data[]`: `district`, `district_label`, `neighborhood`, `neighborhood_label`,
`population_total`, `population_male`, `population_female`, `population_year`,
`buildings`, `other_buildings`, `building_year`, `persons_per_building`.

- Nüfus ve bina **ayrı katmanlardır** ve farklı tarihlerde yayımlanır;
  `*_year` null ise kaynak yıl vermiyor demektir.
- Bir katman okunamazsa alanlar **null** döner, sıfır değil; uyarı eklenir.
- `persons_per_building` ham bölmedir, eşzamanlı sayım değildir.
- Mahalle yayımlanmış katmanlarda yoksa `validation_error` (`field=neighborhood`).

### `izmir_traffic_history`
İzmir ana arter hız/süre **geçmişi**. Canlı trafik değildir; İzmir'de canlı
trafik indeksi yayımlanmıyor (`/api/ibb/trafikyogunluk` → 404).

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `segment` | string \| null | hayır | Başlangıç veya bitiş noktası adında arama. |
| `since` | string \| null | hayır | YYYY-MM-DD alt sınır (dahil). |
| `until` | string \| null | hayır | YYYY-MM-DD üst sınır (dahil). |
| `limit` | int \| null | hayır | |

`data[]`: `segment_from`, `segment_to`, `observed_at`, `hour`, `speed_kmh`,
`duration_minutes`. En yeni ölçüm önce gelir. Ters tarih aralığı
`validation_error` (`field=until`). Boş sonuç "trafik akıcı" kanıtı değildir.

Tazelik `freshness.source_updated_at` = kaynağın **en yeni yayımlanmış
ölçümü**; `limits` bunu `en_yeni_olcum=` ve eşiği `stale_after_hours=` ile
(girdi: `IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS`, varsayılan 72) bildirir. Eşikten
eski veri `stale`, zaman damgası çözümlenemeyen satırlar `unknown` döner.
Filtresiz küçük `limit` tek "en yeni önce" sayfası okur; `matched` yine de
kaynağın toplamıdır. `segment`/`since`/`until` filtreleri tam tarama yapar ki
`matched` ve sıralama filtresiz sonuçla aynı kalsın.

### `izmir_gtfs_status`
Yerel GTFS tarife deposunun durumu. Girdi yoktur; **ağa çıkmaz ve depoyu
yeniden kurmaz**.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| — | — | — | Girdi almaz. |

`data[0]`: `database_path`, `built_at`, `feed_published_at`, `source_url`,
`calendar_start`, `calendar_end`, `checked_on`, `calendar_expired`,
`built_age_seconds`, `zip_bytes`, `stops_rows`, `routes_rows`, `trips_rows`,
`stop_times_rows`, `skipped_stop_times`.

- Depo yoksa `source_unavailable` (boş tarife değildir).
- Takvim bitmişse `calendar_expired=true`, `freshness.status="stale"` ve uyarı.
- Depo yaşı feed'in yayım yaşı değildir; yüklü depo canlı sefer kanıtı değildir.

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

### `izmir_tram_lines`
Tramvay hatları ve yönleri (`line_id`). Girdi yoktur. Yayımlanmış veridir,
canlı tramvay konumu değildir.

### `izmir_tram_schedule`
Bir tramvay hattının istasyonları ve yayımlanan sefer sıklığı.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `line_id` | int | evet | `izmir_tram_lines` çıktısından, 1–999. |

Tarife verisidir; canlı varış süresi değildir.

### `izmir_bus_line_arrivals`
Bir hattın durağa yaklaşan otobüsleri.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `line` | string | evet | Hat numarası. |
| `stop_id` | string \| null | hayır | `izmir_bus_stops` çıktısından. Verilmezse hattın canlı konumları döner. |
| `limit` | int \| null | hayır | |

Dakika cinsinden ETA yayımlanmaz; boş sonuç sefer olmadığını kanıtlamaz.

### `izmir_bus_live_positions`
Hattaki otobüslerin canlı konumu (≤15 sn önbellek).

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `line` | string | evet | Hat numarası. |
| `limit` | int \| null | hayır | |

Koordinatlar kaynakta virgüllü ondalıkla gelir ve sayıya çevrilir.

### `izmir_dam_status`
İZSU barajlarının bir güne ait durumu.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `date` | string \| null | hayır | `YYYY-AA-GG`; varsayılan bugün, gelecek olamaz. |
| `dam_name` | string \| null | hayır | Türkçe harf/büyük-küçük duyarsız baraj adı. |
| `limit` | int \| null | hayır | |

JSON API başarısızsa CSV yedeğine düşülür. Geçmiş günler uzun, bugün kısa önbelleklidir.

### `izmir_pharmacies_all`
Tüm eczaneler (yalnız nöbetçi değil). Nöbetçi eczane için `izmir_nearby`.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `area` | string \| null | hayır | Yayımlanan bölge etiketi. |
| `query` | string \| null | hayır | Ad araması. |
| `lat` | number \| null | hayır | `lon` ile birlikte. |
| `lon` | number \| null | hayır | `lat` ile birlikte. |
| `radius_m` | int \| null | hayır | Yalnız `lat`+`lon` ile. |
| `limit` | int \| null | hayır | |

Kaynağın `LokasyonX` alanı enlem, `LokasyonY` boylamdır; sunucu düzeltir.

### `izmir_cbs_layer`
İBB CBS katmanından yerler (izinli liste, ör. `muzeler`, `hastaneler`, `plajlar`).

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `layer` | enum | evet | İzinli CBS katman adı. |
| `lat` | number \| null | hayır | `lon` ile birlikte. |
| `lon` | number \| null | hayır | `lat` ile birlikte. |
| `radius_m` | int \| null | hayır | Yalnız `lat`+`lon` ile. |
| `district` | string \| null | hayır | İlçe filtresi. |
| `limit` | int \| null | hayır | |

Konumdur; açık/kapalı durumu değildir. Sayfalama sınırlıdır ve günlük önbelleklidir.

### `izmir_events`
Kültür-sanat etkinlikleri.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `query` | string \| null | hayır | Başlık/mekân araması. |
| `free_only` | bool | hayır | Yalnız ücretsiz etkinlikler. |
| `limit` | int \| null | hayır | |

### `izmir_market_prices`
Hal (sebze-meyve/balık) fiyatları.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `kind` | enum | hayır | `sebzemeyve` (varsayılan) veya `balik`. |
| `day` | string \| null | hayır | `YYYY-AA-GG`; varsayılan bugün. |
| `query` | string \| null | hayır | Ürün araması. |
| `limit` | int \| null | hayır | |

Kaynak bir gün için içerik döndürmezse (204) önceki günlere bakılır ve gerçek bülten tarihi bildirilir.
Semt pazarı günleri için `izmir_market_schedule`.

### `izmir_fare`
İZBAN iki istasyon arası ücret (TL; tam, öğrenci, öğretmen, 60 yaş, serbest).

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `from_station` | int \| string | evet | İZBAN istasyon kimliği veya adı (Türkçe harf/büyük-küçük duyarsız). |
| `to_station` | int \| string | evet | `from_station` ile aynı olamaz. |
| `transfer` | bool | hayır | Kaynağın aktarma bayrağı (`0`/`1` olarak gönderilir). |
| `htt` | bool | hayır | Kaynağın tarife bayrağı (`true`/`false`); anlamı API'de belgelenmemiştir. |

Kimlikler yayımlanmış `izban/istasyonlar` listesine karşı doğrulanır; belirsiz
ad adaylarla birlikte `validation_error` döner. Yanıt `fares`, `refunds`,
`min_balance` ve `distance_km` içerir.

### `izmir_parking_fees`
İZELMAN otopark ücret tarifesi (39 otopark).

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `query` | string \| null | hayır | Otopark adı parçası (düz alt dize). |
| `limit` | int \| null | hayır | |

`fees_try` süre dilimlerini TL olarak verir; boş veya null kolonlar `null`.
Canlı doluluk için `izmir_nearby(types=["parking"])`.

### `izmir_traffic_cameras`
Trafik kamerası konumları (92 nokta). Görüntü/yayın bağlantısı yayımlanmaz.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `query` | string \| null | hayır | Kavşak adı parçası. |
| `lat` | number \| null | hayır | `lon` ile birlikte. |
| `lon` | number \| null | hayır | `lat` ile birlikte. |
| `radius_m` | int \| null | hayır | Yalnız `lat`+`lon` ile; varsayılan 2000, en fazla 50000. |
| `limit` | int \| null | hayır | |

### `izmir_water_production`
İZSU baraj/kuyu bazında su üretimi — son yayımlanan anlık görüntü.

| Girdi | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `name` | string \| null | hayır | Baraj/kuyu adı parçası. |
| `limit` | int \| null | hayır | |

Kaynakta tarih kolonu ve birim yoktur; "bugünkü üretim" olarak sunulmaz. Baraj
doluluğu için `izmir_dam_status`.

### `izmir_health`
Yerel hazırlık ve yayımlanan limitler. Girdi yoktur. Kaynak sağlığı ölçmez;
`freshness.status="fresh"` yalnızca yerel runtime içindir.
