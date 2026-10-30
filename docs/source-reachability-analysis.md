# Kaynak erişilebilirlik analizi

Hangi uçların gerçekten çalıştığını, hangilerinin **kapalı** olduğunu ve bunun
kodda nasıl temsil edildiğini tek yerde toplar. Tüm ölçümler doğrudan HTTP ile
yapıldı; kapalı uçlar **2026-10-29**'da yeniden denendi ve aynı sonuçlar alındı
(ilk ölçüm 2026-10-28).

Bu belge bir "yapılacaklar" listesi değil, **kanıt kaydıdır**: kapalı bir kaynak
için veri üretilmez, araç açıkça `source_unavailable` döner.

## Çalışan kaynaklar

| Uç / dosya | Ölçüm | Kullanan araç |
|---|---|---|
| `acikveri.bizizmir.com/api/3/action/*` (CKAN) | 200 | katalog (4), tüm katmanlar |
| `openapi.izmir.bel.tr/api/ibb/izum/otoparklar` | 200 | `izmir_nearby` |
| `openapi.izmir.bel.tr/api/ibb/nobetcieczaneler` | 200 | `izmir_nearby` |
| `openapi.izmir.bel.tr/api/ibb/cevre/havadegerleri/{tarih}` | 200 | `izmir_air_quality` |
| `openapi.izmir.bel.tr/api/metro/istasyonlar` + `/metro/sefersaatleri` | 200 | `izmir_transit_*` |
| `openapi.izmir.bel.tr/api/izban/istasyonlar` + `/izban/sefersaatleri/{a}/{b}` | 200 | `izmir_transit_*` |
| `openapi.izmir.bel.tr/api/izdeniz/iskeleler` + sefer uçları | 200 | `izmir_transit_*` |
| `openapi.izmir.bel.tr/api/iztek/duragayaklasanotobusler/{durak}` | 200 | `izmir_bus_arrivals` |
| `openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/{hat}` | 200 | (doğrulandı, bağlanmadı) |
| `metrotramapi.iztek.tr/api/v1/announcements` | 200 (boş liste) | `izmir_transport_disruptions` |
| `metrotramapi.iztek.tr/api/v1/lines`, `/day-types` | 200 | (doğrulandı, bağlanmadı) |
| `coreapi.izdeniz.com.tr/api/v1/announcements` | 200 | `izmir_transport_disruptions` |
| `openfiles.izmir.bel.tr/.../izsu-baraj-doluluk-oranlari.csv` | 200 | `izmir_water_status` |
| `openfiles.izmir.bel.tr/211488/docs/eshot-otobus-duraklari.csv` | 200 | (DataStore tercih edildi) |
| `openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv` | 200 | `izmir_transport_disruptions` |
| `www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip` | 200, geçerli ZIP, 18,4 MB; **2026-10-29'da yeniden indirildi**, `calendar.txt` hâlâ 2026-08-05 → 2026-10-09 | `izmir_bus_departures`, `izmir_bus_routes`, `izmir_gtfs_status` |
| `www.izmirmetro.com.tr/gtfs/rail-metro-gtfs.zip` | 200, geçerli ZIP | (doğrulandı, bağlanmadı) |
| `www.tramizmir.com/gtfs/rail-tramizmir-gtfs.zip` | 200, geçerli ZIP | (doğrulandı, bağlanmadı) |
| `www.izban.com.tr/gtfs/rail-izban-gtfs.zip` | 200, geçerli ZIP | (bağlanmadı: takvim 2025-01-01'de bitti) |

## Kapalı kaynaklar (kanıtlı)

| Uç | Sonuç | Kodda nasıl temsil edilir |
|---|---|---|
| `openapi.izmir.bel.tr/api/izsu/arizakaynaklisukesintileri` | **500** | `izmir_water_status(kind="faults")` → `source_unavailable` |
| `openapi.izmir.bel.tr/api/izsu/barajdurum` | **500** | kullanılmıyor; CSV tercih edildi |
| `openapi.izmir.bel.tr/api/ibb/trafikyogunluk`, `/ibb/trafik` | **404** | araç yok (trafik indeksi yayımlanmıyor) |
| `openapi.izmir.bel.tr/api/metro/ekipmanlar` | **404** | araç yok |
| `openapi.izmir.bel.tr/api/metro/arizalar` | **404** | araç yok |
| `openapi.izmir.bel.tr/api/ibb/cbs/adres*` | **404** | serbest adres geocoding yok |
| `www.izdeniz.com.tr/gtfs/ship-izdeniz-gtfs.zip` | 200 ama **`text/html`** | İZDENİZ GTFS yok |
| `www.izban.com.tr/Rss.aspx?MenuId=45` | **302** → `FileNotFound.htm` | `operator="izban"` → `source_unavailable` |
| `www.izban.com.tr/Sayfalar/Single.aspx?MenuId=*` | **302** → `FileNotFound.htm` | aynı |
| `metrotramapi.iztek.tr/api/v1/izbanannouncements` | **404** | aynı |
| `acikveri.bizizmir.com/api/3/action/datastore_search_sql` | **"Action name not known"** | SQL yüzeyi açılmadı |
| Belgesiz `/api/eshot/...`, `/api/iztek/hatlar`, `/api/duraklar` | **404** | hiç bağlanmadı (tahmini yol) |

## Tuzaklar (bağlarken karşılaşılan gerçek davranışlar)

| Davranış | Etkisi | Çözüm |
|---|---|---|
| `www.eshot.gov.tr` açık `Accept: application/zip` başlığına **406** | GTFS indirilemiyor | `Accept: */*` |
| İZTEK ardışık isteklerde **429** | varış sorguları düşüyor | yumuşak hız sınırı + 20 sn önbellek |
| Geçersiz durak kimliği **200 + boş dizi** | "sefer yok" sanılabilir | boş yanıt uyarıyla sunulur |
| ESHOT GTFS takvimi **2026-10-09'da bitti** | bugünkü kalkış yok | `calendar_end` + eskime uyarısı |
| Koordinatlar Türkçe ondalık virgülle (`"38,45"`) | ayrıştırma hatası | yalnız ondalık biçim kabul edilir |
| Adlar BÜYÜK harf ve yazım hatalı (`"Kurulmnaktadır"`) | gün ayrıştırma | açık gün adı eşleşmesi, aksi `unknown` |
| WizmirNET aynı konumu çok satırla yayımlıyor | yinelenen sonuç | konum/adres bazlı tekilleştirme |
| Kütüphane katmanında **koordinat yok** | yarıçap uygulanamaz | ilçe/adres listesi, `distance_m` null |
| İzmirim Kart verisi **2023-08-21** | eskimiş | statik/eskimiş uyarısı |

## Yeniden doğrulama (2026-10-29)

Kapalı uçlar bugün tekrar denendi; hiçbiri açılmadı:

| Uç | 2026-10-29 sonucu |
|---|---|
| `/api/izsu/arizakaynaklisukesintileri` | **500** (JSON) |
| `/api/izsu/barajdurum` | **500** (JSON) |
| `/api/ibb/trafikyogunluk`, `/api/ibb/trafik` | **404** |
| `/api/metro/ekipmanlar`, `/api/metro/arizalar` | **404** |
| `/api/ibb/cbs/adres` | **404** |
| `swagger/v1/swagger.json` (her iki kök) | **404** — makine-okunur uç listesi yayımlanmıyor |
| `izdeniz.com.tr/gtfs/ship-izdeniz-gtfs.zip` | 200, `text/html` |
| `izban.com.tr/Rss.aspx?MenuId=45` | **302** |
| `metrotramapi.iztek.tr/api/v1/izbanannouncements` | **404** |

İkinci bulgu: canlı ESHOT arşivi bugün de **2026-10-09**'da biten aynı takvimi
yayımlıyor. Yani eskime uyarısı bir kurulum hatası değil, kaynağın durumu;
yeniden indirmek bir şeyi düzeltmez.

```bash
.venv/bin/python scripts/smoke_live.py     # tüm canlı kaynaklar, exit 0 beklenir
```

Bu betik 35 kontrol yapar; `disruptions_izban_unavailable` bilerek
`source_unavailable` bekler ve **geçer** sayılır.
