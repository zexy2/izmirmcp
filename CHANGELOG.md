# Changelog

Bu proje [Semantic Versioning](https://semver.org/lang/tr/) izler.

## Yayımlanmamış (0.1.0 sonrası)

### Eklendi

- `NOTICE`: Apache-2.0 kaynakları (halilcengel/IzmirMCP,
  AtaCanYmc/izmir-open-data-py) için atıf.
- README: PyPI/registry/CI/lisans rozetleri, TR/EN yeni araç tablosu, rakip
  karşılaştırması, Claude Desktop/Cursor/VS Code `uvx` yapılandırmaları ve uzak
  HTTP barındırma notu.
- Geliştirmede: tramvay, hat bazlı/canlı otobüs, `izmir_dam_status`, tüm
  eczaneler, CBS katmanları, etkinlikler, hal fiyatları. Mevcut araç şemaları
  değişmedi; `server.json` ve sürüm henüz yükseltilmedi.
- `izmir_nearby.types`: yeni `charging_station` (şarj istasyonu) türü.
- `izmir_bus_departures`: `stop_id` artık opsiyonel; durak `lat`/`lon`/`radius_m`
  veya `stop_query` ile de bulunabilir (geriye uyumlu genişleme).

### Yayın

- `server.json` artık yalnızca OCI (`ghcr.io/zexy2/izmir-mcp:0.1.0`, stdio)
  paketini listeler; PyPI girdisi trusted publisher hazır olunca geri eklenecek.
- `release.yml`: PyPI işi `vars.PUBLISH_PYPI` ile opsiyonel, `mcp-publisher`
  v1.8.7 sha256 doğrulamalı, yayından önce `scripts/check_release_metadata.py`
  sürüm kontrolü, ön sürümlerde `latest` etiketi yok, push öncesi Trivy taraması.

### Düzeltildi

- `izmir_dam_status`: İZSU JSON servisi TLS/sertifika veya bağlantı hatası
  verirse yayımlanan baraj CSV'sine otomatik düşer (`source: csv_fallback`).
  CSV tarih seçimini desteklemez; geçmiş bir `date` istenmişse bu açıkça
  uyarılır. TLS doğrulaması kapatılmadı.

## 0.1.0 — 2026-10-28

İlk sürüm. İzmir için salt okunur şehir verisi MCP sunucusu.

### Eklendi

- `nobetci_eczane` prompt'u: ilçedeki nöbetçi eczaneleri mevcut `izmir_nearby`
  aracıyla listeler. Araç yüzeyi değişmedi (22 araç).
- CI işlere bölündü: `lint`, `test` (3.11–3.13), `conformance`, `docker`
  (Trivy + SBOM), `audit` (`pip-audit`), bloklamayan `live`. Action'lar SHA ile
  sabitlendi; Dependabot eklendi.
- `release.yml` (PyPI trusted publishing, GHCR, MCP registry) ve `uptime.yml`
  (`scripts/uptime_check.py`, otomatik olay issue'su).
- `tests/test_tool_compatibility.py`: araç adları ve girdi şemaları için
  geriye dönük uyumluluk kilidi.
- Belgeler: `docs/configuration.md`, `docs/development.md`, `docs/security.md`,
  `docs/tool-migration.md`; README'ye İngilizce bölüm ve `mcp-name` işareti.
- `docs/` dokümantasyon seti: yanıt sözleşmesi, araç referansı, dağıtım,
  kaynaklar ve izleme. `tests/test_docs.py` bu belgeleri koda karşı kilitler.
- 17 salt okunur MCP aracı: katalog (4), yakındaki hizmetler, İZSU baraj,
  hava kalitesi, metro/İZBAN/İZDENİZ, ESHOT durak/varış/tarife/hat detayı,
  semt pazarı takvimi, çok operatörlü ulaşım duyuruları, şehir hizmetleri.
- Ortak yanıt zarfı ve hata taksonomisi (`source_unavailable`,
  `source_rate_limited`, `source_timeout`, `validation_error`).
- ESHOT GTFS tarifesi için yerel SQLite deposu; `izmir_bus_departures` planlı
  kalkışları, `izmir_bus_routes(detail=true)` hat duraklarını döndürür.
- `izmir_mobility_nearby`: "yakınımdaki ulaşım" sorusunu tek zarfta cevaplar.
  Metro, İZBAN, vapur iskelesi, ESHOT durağı, taksi durağı, şarj istasyonu ve
  otopark mesafeye göre sıralı; `summary` tür başına sayım verir. Hava kalitesi
  (İzmir kaynağı koordinat yayımlamıyor) ve canlı trafik (404) `warnings`'te
  açıkça kapsam dışı ilan edilir, uydurulmaz.
- `izmir_bus_departures` üç hedef modu destekler: `stop_id` (tek durak),
  `stop_query` (durak adından kimlik keşfi; kalkış **döndürmez**) ve
  `lat`+`lon` (+`radius_m`, varsayılan 500 m, en yakın 25 durak). Yarıçap modu
  yayımlanmış durakların planlı kalkışlarını tek zaman sırasında birleştirir ve
  her satıra `stop_name` ile kuş uçuşu `distance_m` ekler; keşif ve yarıçap
  modları tarife deposunu kurmaz. Upstream `istanbul_next_departures`
  yüzeyiyle eşitlendi.
- `izmir_nearby` ve `izmir_city_services_nearby` için yarıçap, `bbox` ve ilçe
  modları.
- HTTP yüzeyi sertleştirmesi: gövde tavanı, istemci hız sınırı, eşzamanlılık
  sınırı, isteğe bağlı Bearer API anahtarı, tarayıcı Origin allowlist'i,
  yapısal erişim logu ve gerçek `/readyz`.
- **Docker** imajı: çok aşamalı olmayan, pinlenmiş `python:3.11-slim`,
  root olmayan kullanıcı, `/data` hacminde çalışma anında kurulan GTFS deposu.
- **server.json** MCP registry manifesti (stdio paketi + OCI imaj).
- GitHub Actions CI: pytest, canlı smoke, import kontrolü ve imaj derleme.
- **Sözleşme ve güvenlik testleri (P4):** 17 aracın tamamı için zarf
  conformance testi, keşif yüzeyi (tools/resources/prompts) şema testi ve auth /
  origin / gövde tavanı / XFF spoofing güvenlik testleri. Testler bir konnektör
  kaydı — yeniden oynatma koşumu kullanır; ağ yoktur.

### Değişti

- Kod MIT lisansıyla yayımlanır (`LICENSE`).
- Mekânsal indeksin yaşam döngüsü (`built_at`, kapsam, yaş, yeniden kurma)
  `app/storage/geo.GeoIndex`'e taşındı; servis yalnızca yükleyici ve uyarı
  sağlıyor. Soğuk indekste katman başına çift fetch kaldırıldı.
- `izmir_nearby`'nin üç konum modu tek zarf yoluna indi; `_maps_url`
  `app.core.geo.maps_url` oldu ve dört kopya kaldırıldı.
- `izmir_traffic_history` filtresiz küçük `limit` için tek "en yeni önce" sayfa
  okuyor (`traffic_recent`); `matched` kaynağın `total` alanından geliyor.
  Filtreli sorgular tam taramada kaldı, çünkü eşleşme herhangi bir satırda
  olabilir. Soğuk `limit=2` süresi 6,87 sn → 0,34 sn (ölçüldü).

### Düzeltildi

- `izmir_air_quality`, `izmir_transit_stations`/`izmir_transit_schedule` ve
  `izmir_water_status(kind="dams")` kaynak hatasını zarfa çevirmiyordu; MCP
  `UnexpectedToolError` sızıyordu. Artık `source_unavailable` /
  `source_rate_limited` / `source_timeout` tipli hataya dönüşür.
- Hız sınırı istemci kimliği: loopback bind'de `X-Forwarded-For` virgüllü liste
  taşıdığında ilk öğe güveniliyordu; bu, tek bağlantıdan istek başına yeni
  kimlik üretip hız sınırını atlatıyordu. Artık yalnızca tek başlık ve tek bare
  değer güvenilir; liste/boşluk durumunda soket eşi kullanılır.
- `IZMIR_MCP_GTFS_DATABASE_PATH` ayrımı belgelendi (`docs/deployment.md`,
  `docs/gtfs-schedule.md`); `IZMIR_MCP_DATABASE_PATH` artık yalnızca kota ve
  mekânsal indeks olarak tanımlanıyor. Hazırlık (`/readyz`) ve GTFS CLI testleri
  doğru ayarı kullanır.
- `izmir_nearby` yarıçap modu sonucu `limit` ile kesildiğinde artık
  `result_info.matched`/`truncated` bildiriyor ve özet "İlk sonuçlar
  gösteriliyor." diyor; önce yalnız `rows[:limit]` uygulanıyor, kesilme sessiz
  kalıyordu. `izmir_mobility_nearby` aynı sözleşmeyi devraldı.
- `izmir_traffic_history` `freshness.status="fresh"` derken
  `source_updated_at=null` bırakıyordu; 8 günlük veri taze görünüyordu. Tazelik
  artık en yeni yayımlanmış ölçümden (kaynak saat dilimi Europe/Istanbul)
  türetiliyor, eşik `IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS` (72) ve gerekçe
  `limits`/`warnings` içinde yazılı.

### Sınırlar

- `izmir_bus_departures` yarıçap modunda `distance_m` kuş uçuşudur ve `limit`
  tüm durak kümesi için toplamdır, durak başına değildir.
- İZSU arıza akışı kaynakta HTTP 500; `kind=faults` açıkça unavailable döner.
- ESHOT GTFS takvimi 2026-10-09'da bitti; her yanıt `calendar_end` ve eskime
  uyarısı taşır.
- İZBAN duyuru akışı erişilemiyor; `operator="izban"` unavailable döner.
- Lisans seçilmedi; dağıtımdan önce karar gerekir.

### Güvenlik

- Upstream SSRF koruması çözülen IP'ye sabitlenir (DNS rebinding yok),
  IPv4-mapped/6to4 adresleri reddedilir, `trust_env=False`.
- Upstream gövdeleri akış halinde ve bayt/süre tavanıyla okunur; ulaşılamayan
  host soğuma tablosu sınırlı.
- Gelen istekte gövde tavanı ve Host allowlist (`IZMIR_MCP_ALLOWED_HOSTS`,
  boşsa yalnızca uyarı); `IZMIR_MCP_REQUIRE_AUTH` ile fail-closed açılış.
