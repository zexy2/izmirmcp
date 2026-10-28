# PROGRESS — İzmir MCP

Son güncelleme: 2026-10-28
Durum: **17 araç, 333 test (+1 bilinçli xfail), canlı smoke yeşil.** Mission:
upstream parity (olabildiğince, İzmir verisi olan kadarıyla).

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
| P1 operatör duyuruları | Metro + İZDENİZ duyuruları bağlandı; İZBAN kanıtla unavailable | `be740c0` |
| P2 paketleme | Dockerfile + .dockerignore + entrypoint, server.json, CI, CHANGELOG, console script | `5097c3d` |
| P3 dokümantasyon | `docs/` beş belge + `tests/test_docs.py` kilit testleri | `ca18f3f` |
| P5 mahalle envanteri | 24 → 1.219 mahalle referansı (muhtarlıklar), `place_district` ile belirsizlik çözümü | bu pass |
| P4 sözleşme + güvenlik | zarf conformance (17 araç), keşif yüzeyi şeması, auth/origin/gövde/XFF testleri; 3 serviste sızan kaynak hatası ve XFF liste atlatması düzeltildi; tüm servislerde 429→`source_rate_limited` | bu pass |

## Sırada (öncelik sırasıyla)

### P1 — Çok operatörlü ulaşım aksaklıkları ✅ TAMAMLANDI
Metro (`metrotramapi.iztek.tr/api/v1/announcements`) ve İZDENİZ
(`coreapi.izdeniz.com.tr/api/v1/announcements`) bağlandı. İZBAN'ın erişilebilir
akışı yok (302→FileNotFound, 404); `operator="izban"` açık `source_unavailable`.
Kanıt: `reports/operator-duyuru-kaynaklari.md`.

### P2 — Paketleme ve yayın hazırlığı ✅ TAMAMLANDI
Dockerfile (digest pinli slim, root olmayan kullanıcı, `/data` hacmi, çalışma
anında GTFS kurulumu), `.dockerignore`, `docker/entrypoint.sh`, `server.json`,
`.github/workflows/ci.yml`, `CHANGELOG.md`, `izmir-mcp` / `izmir-mcp-stdio`
console script'leri.

**Doğrulandı (2026-10-28):** imaj gerçekten derlendi ve çalıştırıldı
(`izmir-mcp:local`, 276 MB, arm64). Konteyner `healthy`; 19 araç; `/healthz`,
`/readyz`, `/status` 200; `/mcp/` Streamable HTTP çalışıyor; GTFS deposu
konteyner içinde kuruldu (2.108.736 stop_times); non-root `uid=10001`; `/data`
hacmi yazılabilir; stdio transport konteyner içinde el sıkışıyor; auth açıkken
`401/200` doğru.

**Bu doğrulamada bulunan gerçek hata:** `pyproject.toml` hem `packages = ["app"]`
hem `force-include "app/data"` içeriyordu. Editable kurulum bunu gizliyordu ama
gerçek wheel üretimi `ValueError: A second file is being added to the wheel
archive: app/data/neighborhoods.json` ile ölüyordu — yani `pip install .`
(Dockerfile'ın tek kurulum adımı) her ortamda bozuktu. `force-include` kaldırıldı
ve `tests/test_packaging.py::test_wheel_can_actually_be_built` bu sınıf hatayı
statik olarak kilitliyor.

### P3 — Dokümantasyon seti (`docs/`) ✅ TAMAMLANDI
- `response-contract.md` — zarf alanları, hata taksonomisi, `result_info` scope'ları.
- `tool-reference.md` — 17 aracın girdi şeması (canlı `input_schema`'dan) ve
  davranış sözleşmesi.
- `deployment.md` — 38 env değişkeni, auth, CORS, guard kodları, Docker, CLI.
- `sources.md` — kanonik `Source.name` tablosu, uçlar, durum, lisans (ODbL).
- `monitoring.md` — `/healthz`, `/readyz`, `/status`, guard kodları, log formatı.
- `tests/test_docs.py` — belgeleri koda karşı kilitler: zarf alanları, hata
  kodları, scope'lar, araç girdileri, env değişkenleri, kaynak adları, uçlar ve
  log alanları koddan türetilir. Doc drift'i testi kırar.

### P4 — Sözleşme ve güvenlik testleri ✅ TAMAMLANDI
- `tests/test_contract_conformance.py` — 17 aracın her biri için zarf alan
  kümesi/tipi ve `result_info` tutarlılığı. Konnektör `httpx.MockTransport` ile
  değiştirilir: ilk koşum gerçek yanıtı kaydeder, ikinci koşum onu yeniden
  oynatır. Geçersiz girdi ağa hiç çıkmaz. Kaydedilen yanıt 503/500'e çevrilerek
  her araç için hata taksonomisi sınanır. Sağlık aracı yereldir (ağ yok).
- `tests/test_discovery_surface.py` — tools/resources/prompts şema geçerliliği,
  çıktı şeması = `ResponseEnvelope`, `required` kümesi eşleşmesi, handler
  varsayılanları, kaynak listesinin gizli bilgi/API ucu sızdırmaması, prompt
  argümanlarının JSON verisi olarak kodlanması ve güvensiz değerlerin reddi.
- `tests/test_http_security.py` — auth (10 şema/uzunluk/çift başlık varyantı, üç
  korumalı yol, 10 yol kodlama varyantı), origin (8 bypass varyantı, çift başlık,
  auth'tan önce 403, preflight), gövde tavanı (Content-Length, chunked, sahte
  uzunluk, tüm guard'lı metotlar), XFF spoofing (public bind, liste, yinelenen
  başlık, `X-Real-IP`/`Forwarded`/`CF-Connecting-IP`) ve log hijyeni.
- `tests/test_service_source_errors.py` — servis katmanı kaynak hatasını yutar,
  programlama hatasını yutmaz.
- Katalog, pazar ve duyuru servisleri de artık ortak `source_failure_envelope`
  kullanıyor: HTTP 429 her yerde `source_rate_limited`. P4 turunda açık kalan
  tek boşluk buydu; kapatıldı ve `xfail` gerçek iddiaya çevrildi.

**Bu pass'te bulunan ve düzeltilen iki gerçek hata:**
1. `izmir_air_quality`, `izmir_transit_stations`/`izmir_transit_schedule` ve
   `izmir_water_status(kind="dams")` konnektör hatasını zarfa çevirmiyordu;
   MCP `UnexpectedToolError` sızıyordu (AGENTS kural 2 ihlali). Düzeltme:
   `app/services/sources.py` içine `source_failure_envelope` +
   `is_source_failure`; üç servis bu sarmalayıcıyı kullanır.
2. `_client_id` loopback bind'de virgüllü `X-Forwarded-For` listesinin ilk öğesini
   güveniyordu; tek bağlantıdan istek başına yeni kimlik üretip hız sınırı
   atlatılabiliyordu. Düzeltme: yalnızca tek başlık + tek bare değer güvenilir.

**P4'te açık kalan boşluk kapatıldı:** katalog, pazar ve duyuru servisleri HTTP
429'u `source_unavailable` diye etiketliyordu. Artık üçü de ortak
`source_failure_envelope` kullanıyor; strict `xfail` gerçek iddiaya çevrildi.

### P9 — Taksi durakları (`izmir_nearby`) ✅ TAMAMLANDI
Upstream'in `mobility_nearby` aracı bizde yoktu; İzmir'de moto-taksi/kültür
merkezi katmanı doğrulanamadı ama **taksi durakları** gerçek ve koordinatlı.
Yeni araç açmak yerine `izmir_nearby`'ye `taxi_stand` tipi eklendi (upstream de
mobiliteyi ayrı bir nearby aracında topluyor). `types` üst sınırı 6 → 7.

### P8 — `izmir_query_resource` arama + sıralama ✅ TAMAMLANDI
Sunucu `q` ve `sort` destekliyordu ama araç yalnızca `filters` kullanıyordu.
Artık `search` (serbest metin, SQL değil) ve `sort` (`KOLON [asc|desc]`) var;
ikisi de ağa çıkmadan doğrulanır ve kolon adı şemaya karşı kontrol edilir.
Canlı ölçüm: pazar yerlerinde `search=Konak` 14 eşleşme (filtre 13).

Yan bulgu: kaynak önbelleği süreç-global olduğu için testler sıraya bağımlıydı;
`conftest.py`'ye autouse cache izolasyonu eklendi.

### P7 — `izmir_neighborhood_profile` (parity) ✅ TAMAMLANDI
Upstream'in `istanbul_neighborhood_profile` karşılığı. İzmir'de birebir aynı üç
katman (sosyal yardım / bina stok / deprem senaryosu) yok; bunun yerine
yayımlanmış **nüfus** (1.297) ve **bina sayısı** (1.295) katmanları birleştirildi.
Eksik katman null döner (sıfır değil). Yıllar ayrı yayımlandığı için `*_year`
null bırakılır, uydurulmaz.

### P6 — `izmir_gtfs_status` (parity) ✅ TAMAMLANDI
Upstream'in `istanbul_gtfs_snapshot_status` karşılığı. Yerel depoyu ağa
çıkmadan raporlar; takvim eskimesini, satır sayılarını ve kurulum zamanını
açıkça döndürür. Depo yoksa `source_unavailable`, boş tarife değil.

### P5 — Yer çözümleme derinleştirme ✅ KISMEN TAMAMLANDI
Mahalle envanteri 24 → 1.219 (muhtarlıklar), `place_district` ile belirsizlik
çözümü, Türkçe'ye duyarlı ad normalizasyonu. Lanetli boşluk kapatıldı.

**Serbest metin adres geocoding yapılmayacak (karar):** İzmir'de resmî
makine-okunur geocoding ucu yok (`ibb/cbs/adres*` → 404), upstream'de de yok.
Nominatim'i birincil geocoder yapmak kullanım politikası, önbellek ve hız
sınırı yükü getirir; yayımlanmış envanter (30 ilçe + 1.219 mahalle) İzmir
sorgularının çoğunu karşılıyor. Bu bilinçli bir sınır, eksik değil.

## Parity tablosu (upstream → izmirmcp)

Son durum: **19 araç**, upstream'in 16 aracından gerçek veri karşılığı olanların
tamamı karşılandı.

| Upstream aracı | izmirmcp karşılığı | Durum |
|---|---|---|
| `health` | `izmir_health` | ✅ |
| `search_datasets` / `get_dataset` / `get_resource_schema` | aynı adlar | ✅ |
| `query_resource` | `izmir_query_resource` (+ `search`, `sort`) | ✅ daha geniş |
| `nearby` | `izmir_nearby` (+ bbox/ilçe/taksi) | ✅ daha geniş |
| `mobility_nearby` | `izmir_nearby(types=["taxi_stand"])` | ✅ kısmi (taksi) |
| `city_services_nearby` | `izmir_city_services_nearby` (+ bbox/ilçe) | ✅ daha geniş |
| `neighborhood_profile` | `izmir_neighborhood_profile` | ✅ farklı katmanlar |
| `market_schedule` | `izmir_market_schedule` | ✅ |
| `water_status` | `izmir_water_status` | ✅ (arıza kanıtlı 500) |
| `transport_disruptions` | `izmir_transport_disruptions` (4 operatör) | ✅ |
| `transit_line` | `izmir_bus_routes(detail=true)` | ✅ otobüs; metro/İZBAN hat detayı yok |
| `traffic_status` | — | ❌ `404`, kaynak yok |
| `metro_accessibility_status` | — | ❌ `metro/ekipmanlar` `404` |
| `datastore_query` (SQL) | — | ❌ `datastore_search_sql` bu CKAN'da yok |

**Yalnız izmirmcp'de olanlar:** `izmir_air_quality`, `izmir_transit_stations`,
`izmir_transit_schedule`, `izmir_bus_stops`, `izmir_bus_arrivals`,
`izmir_bus_departures`, `izmir_bus_routes`, `izmir_gtfs_status`.

## Bilinçli boşluklar (yapılmayacak, kanıtlı)

| Upstream yeteneği | İzmir durumu |
|---|---|
| Şehir geneli trafik indeksi | `ibb/trafikyogunluk` → 404. Yalnız geçmiş XLSX + 2023 kamera listesi var. |
| Metro ekipman/erişilebilirlik | `metro/ekipmanlar`, `metro/arizalar` → 404. |
| İZSU arıza akışı | `izsu/arizakaynaklisukesintileri` → 500. `kind=faults` açıkça unavailable. |
| Sosyal tesis nearby | "Sosyal tesis" adıyla yayımlanmış veri seti yok. |
| Sınırlı SQL (datastore_query) | **Bu CKAN'da sunucu tarafı yok**: `datastore_search_sql` → `"Action name not known"` (2026-10-28). Upstream'in kendi yaklaşımı (tam snapshot + yerel SQLite + allowlist) 20 MiB'a kadar kopya, ayrı bir altyapı ve kendi enjeksiyon yüzeyini gerektirir. Yalnızca güvenli `filters` + limit sunuluyor; bu bilinçli bir güvenlik tercihi. |
| Legacy araç alias'ları | Yayımlanmış eski ad yok; alias gereksiz. |
| İZDENİZ GTFS | ZIP HTML dönüyor; mevcut openapi sefer araçları kullanılıyor. |
| İZBAN GTFS | 2023 feed, takvim 2025-01-01'de bitti; güncel değil. |
| İZBAN duyuruları | RSS ve tüm `Single.aspx` sayfaları 302→FileNotFound; metrotramapi'de yol 404. `unavailable`. |

## Bilinen riskler

- GTFS SQLite deposu (`.data/`, ~141 MB) git dışında; ilk kalkış sorgusu
  birkaç saniye sürer. `.data/` yoksa yeniden kurulur.
- Hız sınırı ve sayaçlar süreç içi; çok işçili dağıtımda işçi başına bütçe.
- Lisans: depoda LICENSE yok. Upstream'de de yok. Yayımlamadan önce karar gerekli.
- Docker imajı yerelde derlenip çalıştırıldı, ancak `ghcr.io` registry'sine
  push yapılmadı; `server.json` içindeki `ghcr.io/batu1-1an/izmir-mcp:0.1.0`
  imajı henüz yayımlanmadı.
