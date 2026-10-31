# Limits / Sınırlar

This page collects the detailed behavioural limits of izmirmcp that are too long
for the README. The detailed notes are in Turkish; an English summary comes first.

## English summary

- Location tools (`izmir_nearby`, `izmir_city_services_nearby`, `izmir_mobility_nearby`)
  accept mutually exclusive modes: `lat/lon` or `place` + `radius_m`, `bbox`, or `district`.
  `bbox` results have `distance_m = null`; `district` is meaningful only for pharmacies.
- Truncation is always reported through `result_info.returned/matched/truncated`.
- There is **no live city-wide traffic index** (upstream returns 404); `izmir_traffic_history`
  is historical data only.
- There is **no reachable İZBAN announcements feed**; İZSU fault/outage endpoints often
  return HTTP 500 and are reported as typed `source_unavailable` errors, never empty data.
- `izmir_bus_departures` is a published GTFS schedule, not a live ETA; the ESHOT GTFS
  calendar can expire and is surfaced as a warning.
- `izmir_datastore_query` is not server-side SQL: one safe SELECT over a local copy of an
  allowlisted resource, with copy budgets.
- HTTP guards (body cap, rate limit, concurrency, API keys, Origin allowlist) are in-process;
  use a reverse proxy for multi-worker global limits. See [security](security.md).

## HTTP yüzeyi sertleştirmesi

| Koruma | Varsayılan | Ayar |
|---|---|---|
| Gövde tavanı | 1 MB | `IZMIR_MCP_CLIENT_MAX_BODY_BYTES` |
| İstemci başına hız sınırı | 60 istek, 1/sn dolum | `IZMIR_MCP_CLIENT_RATE_LIMIT_CAPACITY`, `..._REFILL_PER_SECOND` |
| Eşzamanlılık sınırı | 32 | `IZMIR_MCP_CLIENT_MAX_CONCURRENT_REQUESTS` |
| Bearer API anahtarı | kapalı | `IZMIR_MCP_API_KEYS` |
| Tarayıcı Origin allowlist | boş (Origin gönderen reddedilir) | `IZMIR_MCP_CORS_ALLOWED_ORIGINS` |
| Yapısal erişim logu | açık | `IZMIR_MCP_ACCESS_LOG_ENABLED` |

Aşım durumları zarfla değil, HTTP durum koduyla döner: `413 payload_too_large`,
`429 rate_limited` (+`Retry-After`), `503 server_busy`, `403 origin_not_allowed`,
`401 unauthorized` (+`WWW-Authenticate`).

Sınırlar ve dürüst notlar:

- Hız sınırı ve sayaçlar **süreç içi** ve uçucudur. Çok işçili (multi-worker)
  dağıtımda her işçi kendi bütçesini uygular; toplam sınırı için önüne bir
  reverse proxy koyun.
- `X-Forwarded-For` yalnızca sunucu loopback'e bağlıyken, tek başlık ve tek
  bare değer taşıdığında dikkate alınır. Virgüllü liste, yinelenen başlık veya
  boşluk içeren değer güvenilmez; o durumda istemci kimliği soket eşidir. Böylece
  tek bağlantıdan istek başına sahte kimlik üretip hız sınırı atlatılamaz.
- Erişim logu yöntem, yol, durum ve süre yazar; sorgu dizesi, gövde, başlık ve
  API anahtarı **hiçbir zaman** loglanmaz.
- Origin allowlist boşken tarayıcı istekleri reddedilir; CLI/stdio MCP
  istemcileri (Origin başlığı göndermeyenler) etkilenmez.
- Bu katman bir yetkilendirme sunucusu değildir; statik anahtar karşılaştırması
  yapar, OAuth/döner anahtar yoktur.

Yerel GTFS tarife deposu varsayılan olarak `.data/izmir_mcp.sqlite3` altında
tutulur; `IZMIR_MCP_DATABASE_PATH` ile değiştirilebilir ve git dışındadır.

## Sınırlar (ayrıntılı)

- `izmir_nearby` üç konum modu kabul eder: `lat/lon` veya `place` + `radius_m`,
  `bbox=[min_lon, min_lat, max_lon, max_lat]` ve `district`. Modlar birbirini
  dışlar; `bbox`/`district` ile `radius_m` birlikte kullanılamaz. Üç modun
  hepsi `result_info.returned/matched/truncated` döndürür; sonuç `limit` ile
  kesilirse `matched` tüm eşleşmeyi bildirir ve özet "İlk sonuçlar
  gösteriliyor." der. `izmir_mobility_nearby` aynı sözleşmeyi devralır.
- `bbox` modu dört kenarı da **dahil** eder ve koordinatı yayımlanan altı türün
  tümünde çalışır. Referans nokta olmadığı için `distance_m` **null** döner ve
  sonuçlar mesafeye göre sıralanmaz. Kaynakta koordinatı olmayan satırlar
  dikdörtgene alınamaz; eşleşme sayısı ve kesilme `result_info` içinde bildirilir.
- `district` modu **yalnızca eczanede** anlamlıdır. Kaynak `Bolge` alanı idari
  ilçe değil nöbet bölgesidir (`KARŞIYAKA 4`, `BORNOVA 3` gibi); eşleşme bu
  bölge/bölge açıklaması metnine dayanır, sınır doğrulaması değildir ve mesafe
  gösterilmez. Yalnızca bölge metninde ilçe adı geçen satırlar eşleşir; bu tam
  ilçe envanteri değildir. Otopark kaynağı ilçe **ve adres yayımlamaz** (doğrulamada 7
  kaydın tamamı `null`), metro/İZBAN/iskele/durak katmanlarında da ilçe alanı
  yoktur; bu türler ilçe modunda atlanır ve uyarı döner. Eşleşme yoksa bu "ilçede
  eczane yok" kanıtı sayılmaz.
- `izmir_city_services_nearby` da `izmir_nearby` ile aynı üç konum modunu kabul
  eder: `lat/lon` veya `place` + `radius_m`, `bbox`, `district`. Modlar birbirini
  dışlar; `bbox`/`district` ile `radius_m` birlikte kullanılamaz. Bu araçta
  modlar arasında **kapsam farkı vardır**:
  - `bbox` dört kenarı da dahil eder ve yalnızca koordinat yayımlayan WiFi ve
    İzmirim Kart katmanlarında çalışır. **Kütüphane katmanı koordinat
    yayımlamadığı için dikdörtgen sorgusuna hiçbir zaman girmez**; `distance_m`
    null döner.
  - `district` ilçe geneli listeler ve mesafe göstermez. Eşleşme kaynağın kendi
    ilçe alanı ya da adres metniyle yapılır (`published_district_field`), idari
    sınır doğrulaması değildir. WizmirNET ve İzmirim Kart kayıtları adres/ilçe
    metninden, kütüphaneler ilçe alanından eşleşir. Eşleşme yoksa bu "o ilçede
    hizmet yok" kanıtı değildir.
  Eşleşme sayısı ve kesilme `result_info` içinde bildirilir.
- `izmir_transport_disruptions` dört operatör tanır: `eshot`, `metro`,
  `izdeniz`, `izban`. `operator` verilmezse ilk üçü birleştirilir. Bunlar
  **duyurudur**; canlı gecikme, araç konumu veya arıza telemetrisi değildir.
- Yalnızca ESHOT makine-okunur geçerlilik penceresi (başlangıç/bitiş) yayımlar;
  bu yüzden `active` **yalnızca ESHOT satırlarında** hesaplanır. Metro ve
  İZDENİZ'de `active` **null** döner — "etkin değil" değil, "bilinmiyor".
- **İZBAN için erişilebilir duyuru akışı yoktur.** `Rss.aspx` ve
  `Sayfalar/Single.aspx` sayfaları HTTP 302 ile `FileNotFound.htm`'e
  yönlendiriyor, `metrotramapi`'de İZBAN duyuru yolu 404. Bu yüzden
  `operator="izban"` her zaman `source_unavailable` döner; duyuru yok sayılmaz.
- Erişilemeyen veya boş dönen operatör sonuçtan düşer ve `warnings` içinde açıkça
  bildirilir; "o operatörde aksaklık yok" sonucu çıkarılmaz. Toplam eşleşme ve
  kesilme `result_info` ile raporlanır.
- Mahalle çözümlemesi İzmir Büyükşehir Belediyesi'nin muhtarlık envanterine
  dayanır (1.292 kayıt → 1.219 benzersiz mahalle, 30 ilçe). Nokta, muhtarlık
  konumunun **mahalle başına ortalamasıdır**; mahalle sınırı veya kapı adresi
  değildir.
- Aynı mahalle adı birden çok ilçede geçebilir (`Atatürk` 17 ilçede). Bu
  durumda `place` tek başına `validation_error` döner ve adayları listeler;
  `place_district` ile ilçe verilmelidir. Sessizce ilk eşleşme seçilmez.
- İlçe adıyla aynı adı taşıyan mahallelerde ilçe yorumu kazanır (`Konak`
  mahallesi değil, Konak ilçesi).
- **Canlı trafik indeksi yoktur** (`/api/ibb/trafikyogunluk` → 404).
  `izmir_traffic_history` yalnızca **geçmiş** segment ölçümlerini verir
  (8 sabit koridor, 2020-06 → 2026-10); anlık yoğunluk veya ETA değildir.
  `freshness.source_updated_at` kaynağın **en yeni yayımlanmış ölçümüdür** ve
  `limits` bunu `en_yeni_olcum=` ile, tazelik eşiğini `stale_after_hours=` ile
  söyler (`IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS`, varsayılan 72). Eşikten eski
  veri `stale` döner — tazelik yeniden indirme zamanına göre iddia edilmez.
  Filtresiz küçük `limit` tek sayfalık "en yeni önce" okuması yapar ve toplamı
  kaynağın `total` alanından alır; `segment`/`since`/`until` filtreleri tam
  tarama gerektirir çünkü eşleşme veri setinin herhangi bir yerinde olabilir.
- Kaza/olay verisi ve rota planlayıcı yoktur.
- İZSU arıza/kesinti akışı kaynakta 500 döndüğü için veri üretilmez.
- Hava kalitesi kaynağı koordinat ve birim yayımlamaz; AQI hesabı yapılmaz.
- Metro tarifesi istasyon çifti değil, saat aralığı ve sefer sıklığıdır.
- İZDENİZ `day` değeri kaynağın kendi gün kimliğidir; haftanın günü olduğu
  varsayılmaz.
- ESHOT varış akışı **ETA/dakika yayımlamaz**; yalnızca kalan durak sayısı ve
  anlık araç konumu döner. Yaklaşan otobüs uçları geçersiz durakta da `200` +
  boş dizi döndüğü için boş yanıt "sefer yok" kanıtı sayılmaz; zarf uyarı taşır.
- İZTEK ardışık yoğun isteklerde `429` döndürdü; bağlantı bu nedenle yumuşak bir
  hız sınırıyla ve 20 saniyelik önbellekle çalışır.
- ESHOT GTFS `calendar.txt`'teki servis penceresi **2026-10-09'da bitmiş**
  durumdadır (doğrulama: 2026-10-28). `izmir_bus_routes` ve
  `izmir_bus_departures` her yanıtta `calendar_end` ile "tarife güncel
  olmayabilir" uyarısını döndürür; takvim dışı tarihlerde kalkış üretilmez.
- `izmir_bus_routes(detail=true)` bir hattın yayımlanmış **tüm durak
  varyantlarını** `direction_id` bazında döndürür. Aynı yönde kısa tur veya
  farklı güzergâh varsa desenler birleştirilmez; `stop_sequence` sırası ve
  yinelenen duraklar (halka hatları) korunur. `limit` bu modda uygulanmaz.
  Kaynak `trip_headsign` yayımlamadığı için yön adı uydurulmaz; yalnızca
  `direction_id` ve varsa kaynak başlığı verilir. Bu da yayımlanmış tarifedir,
  canlı kalkış veya ETA değildir.
- `izmir_bus_departures` ilk kalkış sorgusunda ESHOT GTFS `stop_times.txt`
  (~2,1M satır, 85 MB) dosyasını yerel SQLite deposuna alır (doğrulanan: ~4 sn,
  ~141 MB); sonraki sorgular indeksten okunur. `at` verilmezse bugünkü İstanbul
  saati kullanılır. Bu **planlı tarife**dir; canlı kalkış, gecikme veya ETA
  değildir. `pickup_type=1` (binilemeyen) satırlar elenir ve `25:xx` biçimindeki
  GTFS saatleri doğru takvim gününe yerleştirilir.
- `izmir_bus_departures` iki ek mod sunar ve **ikisi de tarife deposunu
  kurmaz**: `stop_query` yalnızca durak adayları döndürür (kalkış değil;
  `match=exact|fuzzy`), `lat`+`lon` ise yarıçaptaki (varsayılan 500 m, en yakın
  25 durak) kalkışları tek zaman sırasında birleştirir. Yarıçapta yayımlanmış
  durak yoksa boş yanıt + uyarı döner; `distance_m` kuş uçuşudur ve `limit`
  tüm durak kümesi için toplamdır, durak başına değildir.
- İZDENİZ GTFS ZIP bağlantısı `text/html` döndürdüğü için vapur GTFS kapsamı
  yoktur; mevcut İZDENİZ sefer araçları openapi kaynaklarını kullanır.
- Metro, tramvay ve İZBAN GTFS'leri indirilip doğrulandı ancak bağlanmadı:
  İZBAN feed'i 2023 tarihli ve takvimi 2025-01-01'de bittiği için güncel
  değildir.
- Belgesiz `/api/eshot/...`, `/api/iztek/hatlar` gibi tahmini yollar `404`
  döndüğü için kullanılmaz. `ibb/cbs/noktayayakinduraklar` projeksiyon
  parametreleri doğrulanamadığı için bağlanmadı.
- Semt pazarı kurulma günü yalnızca kaynağın serbest metninden (`ACIKLAMA`)
  çıkarılır. Metinden gün çıkmayan kayıtlar `day_confidence="unknown"` ile
  listelenir; gün uydurulmaz ve "o gün pazar yok" sonucu kanıt sayılmaz.
- ESHOT hat duyuruları canlı gecikme/araç durumu değildir. `active` alanı
  yalnızca duyurunun kendi başlangıç/bitiş tarihini sistem tarihiyle
  karşılaştırır.
- Kütüphane katmanı **koordinat yayımlamaz**; bu nedenle `distance_m` ve
  `maps_url` null döner, yarıçap filtresi uygulanamaz. Adres ve ilçe verilir.
- WizmirNET ve İzmirim Kart katmanlarında kaynak aynı konumu birden çok satırla
  yayımlıyor; aynı konum/adres tekilleştirilir ve yinelenen satır sayısı uyarıda
  bildirilir.
- İzmirim Kart dolum noktaları **2023-08-21** tarihli statik yayımdır; nokta
  kapanmış olabilir.
- **Canlı trafik indeksi İzmir'de yok**: `openapi.izmir.bel.tr/api/ibb/trafikyogunluk`
  `404` döner. Yalnızca geçmişe dönük `ana-arterler-gunluk-hiz-ve-sure-verileri`
  (XLSX) ve 2023 tarihli `trafik-kameralari` vardır; ikisi de bağlanmadı.
- **Metro ekipman/arıza verisi yok**: `metro/ekipmanlar` ve `metro/arizalar`
  `404` döner. İstanbul'daki `metro_accessibility_status` aracının karşılığı yok.
- "Sosyal tesis" adıyla yayımlanmış bir veri seti bulunmadı; upstream'deki
  `sosyal_tesis_nearby` aracının birebir karşılığı yoktur.
- `izmir_datastore_query` sunucu tarafı SQL değildir: yalnızca
  `IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS` ile açıkça izin verilen bir kaynağın
  **tamamı** yerel SQLite kopyasına alındıktan sonra tek SELECT çalışır. Liste
  varsayılan olarak boştur; kaynak toplamı satır/byte bütçesini aşarsa veya
  sayfalar arasında değişirse `source_unavailable` döner ve kısmi toplam
  üretilmez. JOIN, alt sorgu, CTE, UNION, pencere fonksiyonu ve yazma yoktur.
  Ayrıntı: [docs/datastore-sql.md](docs/datastore-sql.md).
- Kaynak hatası etiketleri tek yerden üretilir (`source_failure_envelope`):
  HTTP 429 `source_rate_limited`, zaman aşımı `source_timeout`, diğer kaynak
  arızaları `source_unavailable`. Hiçbiri exception olarak sızmaz.
- Zarf conformance testi kaynak yanıtlarını yeniden oynatır; bu, alan şeklini ve
  hata taksonomisini doğrular, canlı kaynağın bugün aynı şemayı döndürdüğünü
  değil. Canlı doğrulama `scripts/smoke_live.py`'nin işidir.
