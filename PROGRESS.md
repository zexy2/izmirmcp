# PROGRESS — İzmir MCP

Son güncelleme: 2026-10-30
Durum: **22 araç**, 613 test yeşil, canlı smoke 37/37, UAT 24/24, protokol smoke
32/32. Mission: upstream istanbulmcp parity (İzmir'in gerçekten yayımladığı veri
kadarıyla).

Bu dosya döngünün hafızasıdır. Her pass sonunda güncellenir.

## Bitti

| Pass | Çıktı | Commit |
|---|---|---|
| v1 temel | 10 araç: katalog, nearby, su, hava, transit | `8a4efed` |
| ESHOT ulaşım | duraklar, canlı yaklaşan varış, GTFS hat özeti | aynı |
| Şehir katmanları | pazar takvimi, hat duyuruları, WiFi/kart/kütüphane | aynı |
| GTFS tarifesi | `izmir_bus_departures` (SQLite stop_times), `izmir_bus_routes(detail=true)` | `0db0421` |
| Alan modları | `izmir_nearby` ve `izmir_city_services_nearby` bbox + ilçe | `0db0421` |
| HTTP sertleştirme | gövde tavanı, hız sınırı, eşzamanlılık, auth, CORS, log, gerçek `/readyz` | `27f1177` |
| P1 operatör duyuruları | Metro + İZDENİZ duyuruları; İZBAN kanıtla unavailable | `be740c0` |
| P2 paketleme | Dockerfile, server.json, CI, CHANGELOG, console script | `5097c3d` |
| P3 dokümantasyon | `docs/` belge seti + `tests/test_docs.py` kilitleri | `ca18f3f` |
| P4 sözleşme + güvenlik | zarf conformance, keşif yüzeyi, auth/origin/gövde/XFF testleri | `e2c89fb` |
| P5 mahalle envanteri | 24 → 1.219 mahalle; `place_district` belirsizlik çözümü | `e2c89fb` |
| P6–P9 | GTFS durumu, mahalle profili, query search/sort, taksi durakları | `e2c89fb` |
| P10 protokol smoke | `scripts/smoke_mcp.py` 32+ kontrol, CI'da bloklayan | `710b64f` |
| P11 altyapı parity | RTree, kalıcı kota, resmî conformance, 404/500 kanıt raporu | `e2c89fb` |
| P12 core parity | telemetri, gerçek readiness, JSON-RPC kapısı, repair, kaynak limitleri | `1e2557f` |
| P13 sertleştirme | güvenlik ve kırmızı takım bulguları, sınır probe'ları | `8a539bb` |
| P14 trafik/şarj/bulanık arama | `izmir_traffic_history`, `charging_station`, fuzzy durak, Retry-After | bu pass |
| P15 yerel SQL | `izmir_datastore_query`: tam kopya + izole SQLite + deny-by-default guard | bu pass |
| P16 kalkış modları | `izmir_bus_departures`: `stop_query` keşfi + `lat`/`lon` yarıçap birleştirmesi | bu pass |
| P17 ulaşım özeti | `izmir_mobility_nearby`: tek zarfta tür başına sayımlı ulaşım noktaları | bu pass |
| P18 sahiplik + kesilme | `GeoIndex` depolama katmanında; üç mod tek zarf yolunda; yarıçap/mobility `matched` bildirir | bu pass |
| P19 trafik tazeliği + hacim | `source_updated_at` en yeni ölçümden; filtresiz küçük `limit` tek sayfa | bu pass |

## P19 — Trafik tazeliği ve okuma hacmi ✅ TAMAMLANDI

Denetim iki kusur ölçtü: tazelik yeniden indirme zamanından "fresh" diyordu
(`source_updated_at=null`, en yeni ölçüm 8 günlük) ve filtresiz `limit=2`
soğuk çağrısı 18.731 satırı 19 sayfada indirip 6,87 sn sürüyordu.

- `freshness.source_updated_at` artık kaynağın en yeni yayımlanmış ölçümü;
  `limits` içinde `en_yeni_olcum=`, `tazelik_kaynagi=`, `veri_yasi_saat=` ve
  `stale_after_hours=` var. Eşik `IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS`
  (varsayılan 72 saat); eski veri `stale`, çözümlenemeyen zaman `unknown`.
- `CityLayerConnector.traffic_recent(limit)`: CKAN'da `TARIH desc, SAAT desc`
  sıralı tek sayfa + `include_total=true`. Filtresiz küçük `limit` artık 0,34 sn
  (ölçüldü), `matched` kaynağın `total` alanından (18.731) geliyor.
- `segment`/`since`/`until` filtreleri tam taramada kaldı: eşleşme veri setinin
  herhangi bir yerinde olabilir ve CKAN substring/aralık filtresi ifade
  edemiyor; bu yüzden filtrelenmiş `matched` ve sıralama değişmedi.

## P18 — Alan sorgusu sahipliği ve kesilme sözleşmesi ✅ TAMAMLANDI

Denetim üç kusuru kanıtladı: yarıçap modu `rows[:limit]` ile sessizce
kesiyordu (`result_info.matched = null`), üç mod aynı zarf bloğunu kopyalıyordu
ve RTree yaşam döngüsü serviste, SQLite ise depolamadaydı.

- `GeoIndex` (`app/storage/geo.py`): indeksin kapsamı, yaşı, `built_at` damgası
  ve yeniden kurma politikası artık depolama katmanında. Yükleyiciler servis
  tarafından enjekte edilir; depolama konnektör veya kullanıcı metni import
  etmez. `NearbyService._layers` yalnızca sonucu kaynak/uyarıya çevirir.
- Üç mod tek `_cut` + `_envelope` yolunda: kesilme tek sahip. Yarıçap ve
  `izmir_mobility_nearby` artık `matched`/`truncated` bildirir; özet kesilince
  "İlk sonuçlar gösteriliyor." der. Mobility ayrıca "Toplam N eşleşmeden ilk M".
- Soğuk indekste çift fetch kaldırıldı: eski yol `_collect` ile bir kez, sonra
  `refresh_index` ile aynı katmanı ikinci kez okuyordu. Yeni yol tek okuma.
- `_maps_url` dört kopyadan `app.core.geo.maps_url`'e taşındı; `NearbyType`
  `SUPPORTED_TYPES`'tan türetiliyor; ölü `_ensure_index` silindi.

## P17 — `izmir_mobility_nearby` ✅ TAMAMLANDI

Upstream `istanbul_mobility_nearby` kompozit cevabının İzmir karşılığı.
Uydurma yok, kopya yok: `NearbyService.mobility()` `nearby()` üzerine ince bir
ön ayardır — aynı mekânsal indeks, aynı satır şekli, aynı hata taksonomisi.

- Katmanlar: metro, İZBAN, vapur iskelesi, ESHOT durağı, taksi durağı, şarj
  istasyonu, otopark (`MOBILITY_TYPES`). Eczane/WiFi/kart/kütüphane bu sorunun
  cevabı değil, dışarıda.
- `summary` tür başına sayım verir ("3 otobüs durağı, 1 metro istasyonu…");
  `counts_scope=shown` sayımların `limit` sonrası gösterilen satırlara ait
  olduğunu söyler (ilçe toplamı değil).
- En yakın otobüs durağı varsa `next_queries` doğrudan
  `izmir_bus_departures(stop_id=…)` ve `izmir_bus_arrivals(stop_id=…)` önerir.
- Kapsam dışı bileşenler `warnings`'te açıkça yazılır: hava kalitesi istasyonları
  (İzmir kaynağı koordinat yayımlamıyor) ve canlı trafik indeksi (404).
- İl sınırı dışı koordinat `outside_coverage` olarak, kaynağa hiç gidilmeden döner.

Testler: `tests/test_mobility.py` (7 test: mod gruplaması, özet etiketleri,
ulaşım dışı katmanların dışlanması, dürüst kapsam uyarıları, kalkış önerisi, il
dışı, hepsi başarısız → `source_unavailable`), `tests/test_mcp_surface.py` şema
ve `place`+`lat` reddi. `izmir://coverage` kaynağına `mobility` yeteneği eklendi.

## P16 — `izmir_bus_departures` keşif ve yarıçap modları ✅ TAMAMLANDI

Upstream `istanbul_next_departures` üç hedef modu destekliyor; İzmir karşılığı
artık aynı yüzeye sahip:

- `stop_id`: tek durak (önceki davranış **değişmedi**).
- `stop_query`: durak adından kimlik keşfi. Kalkış **döndürmez**; adaylar
  `match=exact|fuzzy` ile etiketlenir, tarife deposu hiç açılmaz. Aynı ada sahip
  duraklar ayrı satır kalır, ilki otomatik seçilmez.
- `lat`+`lon` (+`radius_m`, varsayılan 500 m, en yakın 25 durak): yarıçaptaki
  durakların kalkışları **tek zaman sırasında** birleşir. Satırlar `stop_id`,
  `stop_name`, kuş uçuşu `distance_m` taşır; `limit` tüm küme için toplamdır.
  Yarıçapta durak yoksa tarife deposu açılmaz (boş `data` + uyarı).
- Modlar birbirini dışlar; `line` yalnızca kalkış modlarında, `at` yalnızca
  kalkış modlarında geçerlidir (`stop_query` ile reddedilir).

Depo tarafında tek SQL, `stop_id IN (...)` ile gün başına `departure_sec`
sırasında okur (`GtfsScheduleStore.departures_at_stops`). Tek duraklı
`departures()` bu metodun ince sarmalayıcısıdır; böylece GTFS SQL sahibi tek
modül kalır. Durak adı eşleştirme (`_match_stop_query`) `izmir_bus_stops` ile
ortaktır.

Testler: `tests/test_bus_departures.py` (+11 test: birleşik sıralama, boş liste
reddi, keşif modu, fuzzy etiketi, ad sıralaması, yarıçap birleştirmesi, duraksız
yarıçap, mod çakışmaları, `at`/`line` reddi, koordinat/yarıçap doğrulaması) ve
`tests/test_mcp_surface.py` şema kilidi. Canlı: `scripts/smoke_live.py` iki yeni
kontrol, `scripts/live_mcp_uat.py` iki yeni kullanıcı sorusu (bugün: smoke 36/36,
UAT 24/24).

Ad araması artık birebir eşleşmeyi öne alır: `Konak` sorgusu "Güzel Konak"
arkasında kalmaz; sıra (birebir, önek, iç geçiş) ve `izmir_bus_stops` ile
ortaktır.

## P15 — `izmir_datastore_query` ✅ TAMAMLANDI

Upstream'in `istanbul_datastore_query` aracının İzmir karşılığı. Bu portalda
`datastore_search_sql` yok (`"Action name not known"`); bu yüzden araç sunucu
tarafı SQL **değildir**:

- Yalnızca `IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS` listesindeki kaynaklar.
- Kaynak tam olarak sayfalanır (`_id asc`, `include_total`); toplam, şema ve
  `_id` sırası her sayfada doğrulanır.
- Kopya `ckan_sql_max_rows` (50.000) ve `ckan_sql_max_bytes` (20 MiB) ile sınırlı.
  Aşım/oynama → `source_unavailable`; **kısmi toplam yok**.
- Sorgu ayrı bellek içi SQLite'ta; yalnızca `records` tablosu, tek SELECT, JOIN /
  alt sorgu / CTE / UNION / pencere / yazma / allowlist dışı fonksiyon yok.
- SQLite authorizer deny-by-default; `sqlite_master`, `ATTACH`, `PRAGMA`,
  `load_extension`, `readfile` reddedilir.
- Sonuç 256 KiB, 2.000.000 VM adımı ve 0,5 sn ile sınırlı.
- `tests/test_guarded_sql.py` (17 test) ve `tests/test_datastore_sql.py` (9 test).

Canlı doğrulama (2026-10-29): ESHOT durak kaynağı **11.965 satır**, 12 sayfa,
**1.690.495 wire byte**; `SELECT COUNT(*)` → `11965`. Kısmi kopya yok.

## P14 — Trafik geçmişi, şarj istasyonu, bulanık durak, Retry-After ✅

- `izmir_traffic_history`: 18.731 ana arter ölçümü (2020-06 → 2026-10).
  **Geçmiş** veridir; canlı trafik indeksi yoktur (`/api/ibb/trafikyogunluk` 404).
- `izmir_nearby(types=["charging_station"])`: 48 engelli şarj istasyonu.
- `izmir_bus_stops(query=...)`: tek harf yazım hatasında fuzzy eşleşme; sonuç
  `match="exact"|"fuzzy"` ile etiketlenir, uydurma durak yok.
- HTTP 429 `Retry-After` başlığı `SourceRateLimitedError.retry_after_seconds`
  içinde korunur; hemen yeniden denenmez.
- `scripts/live_mcp_uat.py`: 23 gerçek kullanıcı sorusu, MCP üzerinden.

## Parity tablosu (upstream → izmirmcp)

Son durum: **22 araç**. Upstream'in 16 aracından İzmir'de gerçek veri karşılığı
olanların tamamı karşılandı.

| Upstream aracı | izmirmcp karşılığı | Durum |
|---|---|---|
| `health` | `izmir_health` | ✅ |
| `search_datasets` / `get_dataset` / `get_resource_schema` | aynı adlar | ✅ |
| `query_resource` | `izmir_query_resource` (+ `search`, `sort`) | ✅ daha geniş |
| `datastore_query` (SQL) | `izmir_datastore_query` (tam yerel kopya) | ✅ |
| `nearby` | `izmir_nearby` (+ bbox/ilçe/şarj/taksi) | ✅ daha geniş |
| `mobility_nearby` | `izmir_mobility_nearby` (7 ulaşım katmanı, tür sayımlı) | ✅ hava kalitesi/canlı trafik kapsam dışı |
| `city_services_nearby` | `izmir_city_services_nearby` (+ bbox/ilçe) | ✅ daha geniş |
| `neighborhood_profile` | `izmir_neighborhood_profile` | ✅ farklı katmanlar |
| `market_schedule` | `izmir_market_schedule` | ✅ |
| `water_status` | `izmir_water_status` | ✅ (arıza kanıtlı 500) |
| `transport_disruptions` | `izmir_transport_disruptions` (4 operatör) | ✅ |
| `transit_line` | `izmir_bus_routes(detail=true)` | ✅ otobüs; metro/İZBAN hat detayı yok |
| `next_departures` (stop_id + ad keşfi + koordinat) | `izmir_bus_departures` (`stop_id`/`stop_query`/`lat`+`lon`) | ✅ |
| `traffic_status` | `izmir_traffic_history` | ✅ geçmiş; canlı yok |
| `metro_accessibility_status` | — | ❌ `metro/ekipmanlar` 404 |
| — | `izmir_air_quality`, `izmir_transit_stations`, `izmir_transit_schedule`, `izmir_bus_stops`, `izmir_bus_arrivals`, `izmir_bus_departures`, `izmir_bus_routes`, `izmir_gtfs_status`, `izmir_traffic_history`, `izmir_datastore_query` | yalnız bizde |

## Bilinçli boşluklar (yapılmayacak, kanıtlı)

| Upstream yeteneği | İzmir durumu |
|---|---|
| Şehir geneli canlı trafik indeksi | `ibb/trafikyogunluk` → 404. Yalnız geçmiş segment verisi var. |
| Metro ekipman/erişilebilirlik | `metro/ekipmanlar`, `metro/arizalar` → 404. |
| İZSU arıza akışı | `izsu/arizakaynaklisukesintileri` → 500. `kind=faults` unavailable. |
| Sosyal tesis nearby | "Sosyal tesis" adıyla yayımlanmış veri seti yok. |
| İZBAN duyuruları | RSS/Single sayfaları 302→FileNotFound; yol 404. |
| İZBAN GTFS | 2023 feed; takvim 2025-01-01'de bitti. |
| İZDENİZ GTFS | ZIP `text/html` dönüyor. |
| Serbest metin adres geocoding | Resmî makine-okunur uç yok; yayımlanmış 30 ilçe + 1.219 mahalle kullanılıyor. |
| Metro/İZBAN hat detayı | Yayımlanmış hat-üstü durak sırası yok; istasyon listesi ve tarife var. |
| `city_feature` birleşik türü | Ayrı araçlar ve `types` seçimiyle karşılanıyor; ayrı alias açılmadı. |

## Bilinen riskler

- GTFS SQLite deposu (`.data/`, ~141 MB) git dışında; ilk kalkış sorgusu birkaç
  saniye sürer. `.data/` yoksa yeniden kurulur.
- Hız sınırı ve sayaçlar süreç içi; çok işçili dağıtımda işçi başına bütçe.
- Lisans: depoda LICENSE yok. Upstream'de de yok. Yayımlamadan önce karar gerekli.
- Docker imajı yerelde derlenip çalıştırıldı; `ghcr.io` push'u yapılmadı.
- GitHub Actions bulut CI'sı kullanıcı hesabındaki ödeme hatası nedeniyle
  başlamıyor; CI yerelde `act` ile iki job için de geçti.
