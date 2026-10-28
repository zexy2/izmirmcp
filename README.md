# İzmir MCP

İzmir'e dair açık şehir verilerini MCP destekleyen ajanlara ve geliştirici
araçlarına tek bir sunucu üzerinden açan, salt okunur bir Model Context Protocol
sunucusu.

Bu proje [istanbulmcp](https://github.com/Batu1-1an/istanbulmcp) mimarisi ve
yanıt sözleşmesi örnek alınarak İzmir için yeniden kurulmuştur. İstanbul'a özgü
İBB/İETT/İSKİ/İSPARK konnektörleri yerine yalnızca doğrulanmış İzmir kaynakları
kullanılır; İzmir'de karşılığı olmayan yetenekler (şehir geneli trafik indeksi,
İBB mahalle profili, İstanbulkart) bilinçli olarak yoktur.

## Kapsam

Varsayılan yüzey **17 salt okunur araçtır**:

| Araç | İşlev |
|---|---|
| `izmir_health` | Yerel hazırlık ve yayımlanan limitler. Kaynak sağlığı ölçmez. |
| `izmir_search_datasets` | İzmir Açık Veri (CKAN) kataloğunda arama. |
| `izmir_get_dataset` | Veri seti metadata'sı ve kaynak listesi. |
| `izmir_get_resource_schema` | DataStore resource kolonları. |
| `izmir_query_resource` | DataStore kayıtlarını güvenli filtre ve limitle getirir. |
| `izmir_nearby` | Otopark, nöbetçi eczane, metro/İZBAN istasyonu, vapur iskelesi ve ESHOT durağı; yarıçap, `bbox` veya ilçe geneli. |
| `izmir_water_status` | İZSU baraj dolulukları; arıza akışı için açık `source_unavailable`. |
| `izmir_air_quality` | Tarih ve istasyon filtreli hava kalitesi ölçümleri. |
| `izmir_transit_stations` | Metro, İZBAN ve İZDENİZ istasyon/iskele listesi. |
| `izmir_transit_schedule` | Yayımlanmış tarife: metro sıklığı, İZBAN ve İZDENİZ seferleri. |
| `izmir_bus_stops` | ESHOT duraklarını ada göre ara; koordinat + yarıçap ile yakındaki durakları listele. |
| `izmir_bus_arrivals` | Bir durağa yaklaşan otobüslerin anlık konumu ve kalan durak sayısı. |
| `izmir_bus_departures` | Bir durağın yayımlanmış GTFS planlı kalkışları; canlı ETA değildir. |
| `izmir_bus_routes` | ESHOT GTFS hat özeti; `detail=true` ile hattın yönleri, sıralı durakları ve durak varyantları. |
| `izmir_market_schedule` | Semt pazarı takvimi: gün, ilçe veya koordinat + yarıçap filtresi. |
| `izmir_transport_disruptions` | ESHOT, Metro ve İZDENİZ duyuruları; operatör filtresi. |
| `izmir_city_services_nearby` | WizmirNET WiFi, İzmirim Kart dolum noktası ve kütüphaneler; yarıçap, `bbox` veya ilçe geneli. |

Her sonuç ortak zarfı taşır: `ok`, `summary`, `data`, `freshness`, `sources`,
`limits`, `warnings`, `next_queries`, `error`, `result_info`.

## Veri kaynakları

| Kaynak | Kullanım | Durum |
|---|---|---|
| `acikveri.bizizmir.com` (CKAN) | Katalog, metadata, DataStore | Çalışıyor (2026-10-28) |
| `openapi.izmir.bel.tr/api/ibb/izum/otoparklar` | İZELMAN/İZUM otopark doluluğu | Çalışıyor |
| `openapi.izmir.bel.tr/api/ibb/nobetcieczaneler` | Nöbetçi eczane listesi | Çalışıyor |
| `openapi.izmir.bel.tr/api/ibb/cevre/havadegerleri/{tarih}` | Hava kalitesi | Çalışıyor |
| `openapi.izmir.bel.tr/api/metro/istasyonlar` + `/metro/sefersaatleri` | Metro | Çalışıyor |
| `openapi.izmir.bel.tr/api/izban/istasyonlar` + `/izban/sefersaatleri/{from}/{to}` | İZBAN | Çalışıyor |
| `openapi.izmir.bel.tr/api/izdeniz/iskeleler` + sefer uçları | İZDENİZ | Çalışıyor |
| `openfiles.izmir.bel.tr/.../izsu-baraj-doluluk-oranlari.csv` | Baraj doluluğu | Çalışıyor |
| `openapi.izmir.bel.tr/api/izsu/barajdurum` | Baraj JSON | **HTTP 500** — kullanılmıyor |
| `openapi.izmir.bel.tr/api/izsu/arizakaynaklisukesintileri` | Su kesintisi | **HTTP 500** — açıkça `unavailable` |
| CKAN `eshot-otobus-duraklari` (`0c791266-…`, DataStore) | 11.965 ESHOT durağı | Çalışıyor |
| `openapi.izmir.bel.tr/api/iztek/duragayaklasanotobusler/{durakId}` | Canlı yaklaşan otobüs | Çalışıyor (ETA yok, hız sınırlı) |
| `www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip` | ESHOT GTFS (hat/sefer + planlı durak kalkışları) | Çalışıyor — **takvim 2026-10-09'da bitiyor**; `stop_times` yerel SQLite'a alınır |
| `www.izdeniz.com.tr/gtfs/ship-izdeniz-gtfs.zip` | İZDENİZ GTFS | **HTML dönüyor** — kullanılmıyor |
| CKAN `semt-pazar-yerleri` (`3e63e16e-…`) | 186 pazar yeri, koordinat + serbest metin gün notu | Çalışıyor |
| `openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv` | 124 ESHOT hat duyurusu | Çalışıyor |
| CKAN `kablosuz-internet-baglanti-noktalari` (`60ca8451-…`) | 857 WizmirNET noktası | Çalışıyor (yinelenen satırlar var) |
| CKAN `izmirim-kart-dolum-noktalari` (`7a3efbec-…`) | 1.120 dolum noktası | Çalışıyor (**2023 tarihli**) |
| CKAN `izmir-buyuksehir-belediyesi-kutuphaneleri-bilgileri` (`0c1b15b9-…`) | 10 kütüphane | Çalışıyor (**koordinat yok**) |
| `metrotramapi.iztek.tr/api/v1/announcements` | İzmir Metro duyuruları | Çalışıyor (doğrulamada boş liste) |
| `coreapi.izdeniz.com.tr/api/v1/announcements` | İZDENİZ duyuruları | Çalışıyor (gerçek duyurular) |
| `izban.com.tr` duyuru sayfaları / RSS | İZBAN duyuruları | **302 → FileNotFound** — `unavailable` |
| OpenStreetMap Nominatim | İlçe/mahalle referans noktaları | 2026-10-28'de alındı, ODbL |

İlçe ve mahalle konumları yaklaşık referans noktalarıdır; adres çözümleme değildir.
Eczane listesi günlüktür ve telefonla teyit gerektirir. Otopark boş yer sayıları
anlık bildirimdir. İstasyon ve durak konumları statiktir; canlı sefer durumu değildir.
ESHot kaynak araştırmasının tam kanıtı:
[reports/eshot-ulasim-kaynak-arastirmasi.md](reports/eshot-ulasim-kaynak-arastirmasi.md).

## Kurulum

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m app.main
```

Yerel uçlar:

- `GET /healthz` — süreç ayakta mı (kimlik doğrulaması istemez).
- `GET /readyz` — yerel hazırlık: araç yüzeyi kuruldu mu. **Kaynak sağlığı
  ölçmez**; `upstream_health: "not_checked"` döner ve yalnızca yerel durumu
  bildirir. Hazır değilse `503`.
- `GET /status` — araç listesi, limitler, hız sınırı/sayaç telemetrisi.
  API anahtarı yapılandırıldıysa korumalıdır.
- `POST /mcp/` (Streamable HTTP MCP)

### HTTP yüzeyi sertleştirmesi

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
- `X-Forwarded-For` yalnızca sunucu loopback'e bağlıyken dikkate alınır;
  aksi halde istemci kimliği doğrudan bağlantı adresidir.
- Erişim logu yöntem, yol, durum ve süre yazar; sorgu dizesi, gövde, başlık ve
  API anahtarı **hiçbir zaman** loglanmaz.
- Origin allowlist boşken tarayıcı istekleri reddedilir; CLI/stdio MCP
  istemcileri (Origin başlığı göndermeyenler) etkilenmez.
- Bu katman bir yetkilendirme sunucusu değildir; statik anahtar karşılaştırması
  yapar, OAuth/döner anahtar yoktur.

Yerel GTFS tarife deposu varsayılan olarak `.data/izmir_mcp.sqlite3` altında
tutulur; `IZMIR_MCP_DATABASE_PATH` ile değiştirilebilir ve git dışındadır.

## Docker

```bash
docker build -t izmir-mcp .
docker run -p 8000:8000 -v izmir-data:/data izmir-mcp
curl -s http://127.0.0.1:8000/readyz
```

İmaj `python:3.11-slim` (digest pinli), root olmayan `izmir` kullanıcısı ve
`/data` hacmi kullanır. `.data/` ve `.venv/` imaja **girmez**; GTFS deposu
konteyner ilk açılışta `docker/entrypoint.sh` ile yayımlanmış arşivden yeniden
kurulur. Kurulum başarısız olursa konteyner durmaz: tarife araçları dürüst
`source_unavailable` döner, diğer araçlar çalışmaya devam eder. Kurulumu
atlamak için `IZMIR_MCP_SKIP_GTFS_BUILD=1`.

stdio için aynı imaj: `docker run --rm -i izmir-mcp python -m app.stdio`.

### CI ve registry

- `.github/workflows/ci.yml`: pytest, canlı smoke (bloklamaz), import ve araç
  yüzeyi kontrolü, sunucuyu başlatıp `/healthz`+`/readyz` probe'u, ardından
  imaj derleme ve konteyner içinde healthz kontrolü.
- `server.json`: MCP registry manifesti (pypi stdio paketi + OCI imaj).
- `CHANGELOG.md`: sürüm geçmişi.

## MCP istemcisine ekleme

Yerel stdio kaydı (Freebuff/Codex/Claude Code benzeri istemciler):

```json
{
  "mcpServers": {
    "izmir": {
      "command": "/mutlak/yol/izmirmcp/.venv/bin/python",
      "args": ["-m", "app.stdio"]
    }
  }
}
```

`app.stdio` masaüstü istemciler için stdio taşıması açar; `app.main` ise
Streamable HTTP sunucusunu çalıştırır:

```text
http://127.0.0.1:8000/mcp/
```

## Testler

```bash
.venv/bin/python -m pytest -q
```

Testler dış kaynağa bağlanmaz; konnektörler sahte istemcilerle değiştirilir.
Canlı kaynak doğrulaması isteğe bağlıdır:

```bash
.venv/bin/python scripts/smoke_live.py
```

## REA ile doğrulama

Katalog katmanı kurulmadan önce portal, REA 6.8.0 ile CDP üzerinden statik
olarak incelendi. Kanıt dosyası ve bulgular:

- [REA inceleme raporu](reports/rea-open-data-portal.md)
- [REA kanıt paketi](reports/rea-open-data-portal-evidence.json)

REA portalın 11 script'ini ve 239.183 AST düğümünü analiz etti; statik pakette
sabit CKAN yolu bulunmadı. Bu nedenle uçlar ayrıca doğrudan HTTP ile doğrulandı.
Ayrıntı ve sınırlar raporda.

## Sınırlar

- `izmir_nearby` üç konum modu kabul eder: `lat/lon` veya `place` + `radius_m`,
  `bbox=[min_lon, min_lat, max_lon, max_lat]` ve `district`. Modlar birbirini
  dışlar; `bbox`/`district` ile `radius_m` birlikte kullanılamaz.
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
- Şehir geneli trafik indeksi, kaza/olay verisi ve rota planlayıcı yoktur.
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
- `izmir_bus_departures` ilk çağrıda ESHOT GTFS `stop_times.txt` (~2,1M satır,
  85 MB) dosyasını yerel SQLite deposuna alır (doğrulanan: ~4 sn, ~141 MB);
  sonraki sorgular indeksten okunur. `at` verilmezse bugünkü İstanbul saati
  kullanılır. Bu **planlı tarife**dir; canlı kalkış, gecikme veya ETA değildir.
  `pickup_type=1` (binilemeyen) satırlar elenir ve `25:xx` biçimindeki GTFS
  saatleri doğru takvim gününe yerleştirilir.
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
- Serbest SQL (`datastore_query`) bilinçli olarak yoktur; yalnızca güvenli
  `filters` ve limit kullanılır.

## Kaynak ve lisans

Bu proje, [istanbulmcp](https://github.com/Batu1-1an/istanbulmcp) deposunun
mimarisinden ve yanıt sözleşmesinden esinlenir. Zarf, doğrulama, önbellek ve MCP
kayıt katmanındaki bazı yardımcılar o projedeki yaklaşımdan uyarlanmıştır;
İBB/İETT/İSKİ/İSPARK konnektörlerinden kod alınmamıştır.

Upstream depoda bir LICENSE dosyası bulunmadığı için yeniden kullanım koşulları
belirsizdir. Bu projeyi yayımlamadan veya dağıtmadan önce upstream sahibinden izin
alınmalı ya da ortak çekirdek modüller yeniden yazılmalıdır.

Şehir verilerinin lisansları yayıncı kurumlara aittir; açık erişim lisans izni
anlamına gelmez. İlçe/mahalle referans noktaları OpenStreetMap katkıcılarına aittir
(ODbL 1.0).
