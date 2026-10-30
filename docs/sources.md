# Kaynaklar

Bu belge İzmir MCP'nin bağlı olduğu dış kaynakları, kullanım biçimlerini ve
kanıtlı sınırlarını `app/services/sources.py`, `app/core/settings.py` ve
`reports/` altındaki doğrulamalardan türetir. Kaynak sağlığı bu belgenin
değil, araç yanıtlarının `freshness`/`warnings` alanlarının konusudur.

Hiçbir kaynak uydurulmaz. Erişilemeyen uçlar `source_unavailable` döner; veri
üretilmez.

## Kanonik kaynak adları (`Source.name`)

Zarf `sources[].name` değerleri `app/services/sources.py` içindeki sabitlerdir.
Atıf bu adlarla yapılır:

| `Source.name` | Yayıncı | `scope` |
|---|---|---|
| İZELMAN / İZUM otopark doluluk servisi | İzmir Büyükşehir Belediyesi | `parking_occupancy` |
| İzmir nöbetçi eczane listesi | İzmir Büyükşehir Belediyesi | `on_duty_roster` |
| İzmir Metro istasyonları | İzmir Metro A.Ş. | `stations` |
| İZBAN istasyonları | İZBAN A.Ş. | `stations` |
| İZDENİZ iskeleleri | İZDENİZ A.Ş. | `piers` |
| İZSU baraj doluluk oranları | İzmir Su ve Kanalizasyon İdaresi (İZSU) | `dam_levels` |
| İzmir hava kalitesi ölçüm değerleri | İzmir Büyükşehir Belediyesi | `station_readings` |
| İzmir Metro sefer sıklığı | İzmir Metro A.Ş. | `published_timetable` |
| İZBAN sefer saatleri | İZBAN A.Ş. | `published_timetable` |
| İZDENİZ vapur sefer saatleri | İZDENİZ A.Ş. | `published_timetable` |
| İzmir Tramvay hatları, istasyonları ve sefer sıklığı | İzmir Metro A.Ş. | `published_timetable` |
| EShot otobüs durakları | İzmir Büyükşehir Belediyesi / EShot | `stops` |
| EShot durağa yaklaşan otobüsler | İzmir İnovasyon ve Teknoloji A.Ş. (İZTEK) | `live_vehicle_positions` |
| EShot hat otobüs konumları | İzmir İnovasyon ve Teknoloji A.Ş. (İZTEK) | `live_vehicle_positions` |
| İzmir Büyükşehir CBS önemli yer katmanları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmir Büyükşehir kültür sanat etkinlikleri | İzmir Büyükşehir Belediyesi | `published_events` |
| İzmir hal fiyatları (sebze-meyve ve balık) | İzmir Büyükşehir Belediyesi | `wholesale_price_bulletin` |
| İzmir eczane listesi | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| EShot GTFS toplu ulaşım verisi | İzmir Büyükşehir Belediyesi / EShot | `published_timetable` |
| İzmir semt pazar yerleri | İzmir Büyükşehir Belediyesi | `static_market_locations` |
| WizmirNET ücretsiz kablosuz internet noktaları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmirim Kart dolum noktaları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmir Büyükşehir Belediyesi kütüphaneleri | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| EShot hat duyuruları | İzmir Büyükşehir Belediyesi / EShot | `published_line_notices` |
| İzmir Metro duyuruları | İzmir Metro A.Ş. / İZTEK | `published_operator_notices` |
| İZDENİZ duyuruları | İZDENİZ A.Ş. | `published_operator_notices` |
| İZBAN duyuruları (erişilemiyor) | İZBAN A.Ş. | `published_operator_notices` |
| İzmir mahalle nüfusu (cinsiyete göre) | İzmir Büyükşehir Belediyesi | `published_neighborhood_demographics` |
| İzmir mahalle bazlı bina sayıları | İzmir Büyükşehir Belediyesi | `published_building_stock` |
| İzmir taksi durakları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmir ana arter hız ve süre verileri | İzmir Büyükşehir Belediyesi | `historical_segment_speed` |
| İzmir engelli şarj istasyonları | İzmir Büyükşehir Belediyesi | `static_service_locations` |

## Katalog ve DataStore

| Kaynak | Uç / veri seti | Kullanım | Durum |
|---|---|---|---|
| İzmir Açık Veri Portalı (CKAN) | `https://acikveri.bizizmir.com/api/3/action` | `package_search`, `package_show`, `datastore_search` | Çalışıyor (2026-10-28) |

Yalnızca `datastore_search` kullanılır; serbest SQL (`datastore_search_sql`)
bilinçli olarak yoktur. Katalog CTL 21600 sn, resource TTL 300 sn önbelleklenir.

## İzmir Büyükşehir Belediyesi açık API

| Kaynak | Uç | Kullanım |
|---|---|---|
| İZELMAN / İZUM otopark doluluk servisi | `openapi.izmir.bel.tr/api/ibb/izum/otoparklar` | Anlık boş yer snapshot'ı |
| İzmir nöbetçi eczane listesi | `openapi.izmir.bel.tr/api/ibb/nobetcieczaneler` | Günlük nöbet listesi |
| İzmir hava kalitesi ölçüm değerleri | `openapi.izmir.bel.tr/api/ibb/cevre/havadegerleri/{tarih}` | İstasyon + kirletici değerleri |
| İzmir Metro istasyonları | `openapi.izmir.bel.tr/api/metro/istasyonlar` | İstasyon + koordinat |
| İzmir Metro sefer sıklığı | `openapi.izmir.bel.tr/api/metro/sefersaatleri` | Saat aralığı tablosu |
| İZBAN istasyonları | `openapi.izmir.bel.tr/api/izban/istasyonlar` | İstasyon + koordinat |
| İZBAN sefer saatleri | `openapi.izmir.bel.tr/api/izban/sefersaatleri/{from}/{to}` | Yayımlanmış tarife |
| İZDENİZ iskeleleri | `openapi.izmir.bel.tr/api/izdeniz/iskeleler` | İskele + koordinat |
| İZDENİZ seferleri | openapi İZDENİZ kalkış/hat uçları | Yayımlanmış tarife |

OpenAPI TTL 120 sn, hata halinde 900 sn stale kullanımı. Hava kalitesinde
koordinat ve birim yayımlanmaz (`unit=null`); AQI hesaplanmaz.

## Su

| Kaynak | Uç | Durum |
|---|---|---|
| İZSU baraj doluluk oranları | `openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv` | Çalışıyor; TTL 3600 sn, 86400 sn stale |
| İZSU baraj JSON | `openapi.izmir.bel.tr/api/izsu/barajdurum` | **HTTP 500** — kullanılmıyor |
| İZSU arıza/su kesintisi | `openapi.izmir.bel.tr/api/izsu/arizakaynaklisukesintileri` | **HTTP 500** — `kind=faults` açık `source_unavailable` |

Baraj CSV okunurken doluluk yüzdesi olmayan satırlar elenir; doluluk azalan
sıralanır ve "gecikebilir" uyarısı eklenir. Arıza ucu düzelmeden arıza verisi
üretilmez (kanıt: `reports/izmir-sehir-katmanlari.md`).

## ESHOT / İZTEK ulaşım

| Kaynak | Uç / veri seti | Kullanım |
|---|---|---|
| ESHOT otobüs durakları | CKAN `eshot-otobus-duraklari` (`0c791266-…`) | 11.965 durak, DataStore |
| ESHOT durağa yaklaşan otobüsler | `openapi.izmir.bel.tr/api/iztek/duragayaklasanotobusler/{durakId}` | Anlık konum + kalan durak (**ETA yok**) |
| ESHOT GTFS | `www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip` | Hat/sefer + `stop_times.txt` → yerel SQLite |
| ESHOT hat duyuruları | `openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv` | 124 planlı duyuru |

- Durak listesi TTL 86400 sn / 604800 sn stale; İZTEK TTL 20 sn ve ardışık
  isteklerde `0.5` sn aralık (kaynak 429 verdiği için).
- ESHOT GTFS ZIP açık `Accept: application/zip` başlığına `406` döner;
  `*/*` ile indirilir (2026-10-28). `stop_times.txt` ~2,1M satır / ~85 MB,
  depo ~141 MB.
- **GTFS servis takvimi 2026-10-09'da bitti** (doğrulama 2026-10-28). Her
  yanıt `calendar_end` + eskime uyarısı taşır; takvim dışı tarihte kalkış
  üretilmez.
- Varış ucu geçersiz durakta da `200` + boş dizi döner; boş yanıt "sefer yok"
  kanıtı sayılmaz.

## Şehir katmanları (CKAN)

| Kaynak | Veri seti | Kullanım |
|---|---|---|
| İzmir semt pazar yerleri | `semt-pazar-yerleri` (`3e63e16e-…`) | 186 pazar yeri; gün serbest metinden |
| WizmirNET WiFi noktaları | `kablosuz-internet-baglanti-noktalari` (`60ca8451-…`) | 857 nokta (yinelenen satırlar tekilleştirilir) |
| İzmirim Kart dolum noktaları | `izmirim-kart-dolum-noktalari` (`7a3efbec-…`) | 1.120 nokta; **2023-08-21 tarihli** |
| İBB kütüphaneleri | `izmir-buyuksehir-belediyesi-kutuphaneleri-bilgileri` (`0c1b15b9-…`) | 10 kütüphane; **koordinat yok** |

Bu katmanların CTL 86400 sn / 604800 sn stale önbelleği vardır. Hepsi statik
snapshot'tır; açık/kapalı durum yayımlanmaz. Kütüphanedeki koordinat eksikliği
yarıçap ve `bbox` modlarında dışlanmasına yol açar.

## Operatör duyuruları

| Kaynak | Uç | Durum |
|---|---|---|
| İzmir Metro duyuruları | `metrotramapi.iztek.tr/api/v1/announcements` | Çalışıyor (doğrulamada boş liste) |
| İZDENİZ duyuruları | `coreapi.izdeniz.com.tr/api/v1/announcements` | Çalışıyor (gerçek duyurular) |
| İZBAN duyuruları | `izban.com.tr` RSS / `Sayfalar/Single.aspx` | **302 → FileNotFound**; `unavailable` |

İZBAN için erişilebilir makine-okunur akış yok; `metrotramapi`'de İZBAN yolu
`404`. `operator="izban"` her zaman `source_unavailable` döner (kanıt:
`reports/operator-duyuru-kaynaklari.md`). Yalnızca ESHOT makine-okunur geçerlilik
penceresi yayımlar; `active` bu yüzden yalnızca ESHOT'ta hesaplanır.

## Referans noktaları

| Kaynak | Kullanım | Lisans |
|---|---|---|
| OpenStreetMap Nominatim | 30 ilçe + 24 seçili simge yer (`app/data/places.json`) | ODbL 1.0 (© OpenStreetMap contributors) |
| CKAN `muhtarliklar` (`7d0b7f55-…`) | 1.219 mahalle referans noktası (`app/data/neighborhoods.json`) | Izmir Metropolitan Municipality Open Data License |
| CKAN `cinsiyete-gore-mahalle-nufus-bilgileri` (`7ef10678-…`) | 1.297 mahalle nüfusu (kadın/erkek) | Izmir Metropolitan Municipality Open Data License |
| CKAN `ilcelere-ait-mahalle-bazli-bina-sayilari` (`54af6862-…`) | 1.295 mahalle bina sayısı | Izmir Metropolitan Municipality Open Data License |

Retrieved 2026-10-28. Bunlar yaklaşık alan merkezleridir, **adres geocoding
değildir**; araçlar `place` modunda bunu uyarı olarak bildirir.

## Kullanılmayan / reddedilen kaynaklar

- İZDENİZ GTFS ZIP (`www.izdeniz.com.tr/gtfs/...`) `text/html` döndürüyor;
  vapur GTFS kapsamı yok, openapi sefer uçları kullanılıyor.
- İZBAN GTFS 2023 feed'i; takvim 2025-01-01'de bitti, güncel değil.
- Metro/tramvay GTFS indirilip doğrulandı ama bağlanmadı.
- `openapi.izmir.bel.tr/api/ibb/trafikyogunluk` → `404`; şehir geneli canlı
  trafik indeksi yok. Yalnızca geçmiş XLSX ve 2023 kamera listesi var.
- `metro/ekipmanlar`, `metro/arizalar` → `404`; ekipman/erişilebilirlik yok.
- Tahmini `/api/eshot/...`, `/api/iztek/hatlar` yolları `404`.
  `ibb/cbs/noktayayakinduraklar` projeksiyonu doğrulanamadı.
- "Sosyal tesis" adıyla yayımlanmış veri seti yok.

## Lisans durumu

- Şehir verilerinin lisansları yayıncı kurumlara aittir; **açık erişim lisans
  izni değildir**. `Source.license` bu yüzden çoğu kaynakta `null`'dur.
- OpenStreetMap referans noktaları ODbL 1.0 altındadır; atıf zorunludur.
- Bu depoda `LICENSE` dosyası yoktur; upstream'de de yok. Yayımlamadan önce
  lisans kararı verilmelidir (README "Kaynak ve lisans").

## Kanıt raporları

- [EShot/ulaşım kaynak araştırması](../reports/eshot-ulasim-kaynak-arastirmasi.md)
- [Şehir katmanları ve İZSU arızası](../reports/izmir-sehir-katmanlari.md)
- [Operatör duyuruları](../reports/operator-duyuru-kaynaklari.md)
- [REA açık veri portalı incelemesi](../reports/rea-open-data-portal.md)
