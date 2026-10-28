# Changelog

Bu proje [Semantic Versioning](https://semver.org/lang/tr/) izler.

## 0.1.0 — 2026-10-28

İlk sürüm. İzmir için salt okunur şehir verisi MCP sunucusu.

### Eklendi

- `docs/` dokümantasyon seti: yanıt sözleşmesi, araç referansı, dağıtım,
  kaynaklar ve izleme. `tests/test_docs.py` bu belgeleri koda karşı kilitler.
- 17 salt okunur MCP aracı: katalog (4), yakındaki hizmetler, İZSU baraj,
  hava kalitesi, metro/İZBAN/İZDENİZ, ESHOT durak/varış/tarife/hat detayı,
  semt pazarı takvimi, çok operatörlü ulaşım duyuruları, şehir hizmetleri.
- Ortak yanıt zarfı ve hata taksonomisi (`source_unavailable`,
  `source_rate_limited`, `source_timeout`, `validation_error`).
- ESHOT GTFS tarifesi için yerel SQLite deposu; `izmir_bus_departures` planlı
  kalkışları, `izmir_bus_routes(detail=true)` hat duraklarını döndürür.
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

### Düzeltildi

- `izmir_air_quality`, `izmir_transit_stations`/`izmir_transit_schedule` ve
  `izmir_water_status(kind="dams")` kaynak hatasını zarfa çevirmiyordu; MCP
  `UnexpectedToolError` sızıyordu. Artık `source_unavailable` /
  `source_rate_limited` / `source_timeout` tipli hataya dönüşür.
- Hız sınırı istemci kimliği: loopback bind'de `X-Forwarded-For` virgüllü liste
  taşıdığında ilk öğe güveniliyordu; bu, tek bağlantıdan istek başına yeni
  kimlik üretip hız sınırını atlatıyordu. Artık yalnızca tek başlık ve tek bare
  değer güvenilir; liste/boşluk durumunda soket eşi kullanılır.

### Sınırlar

- İZSU arıza akışı kaynakta HTTP 500; `kind=faults` açıkça unavailable döner.
- ESHOT GTFS takvimi 2026-10-09'da bitti; her yanıt `calendar_end` ve eskime
  uyarısı taşır.
- İZBAN duyuru akışı erişilemiyor; `operator="izban"` unavailable döner.
- Lisans seçilmedi; dağıtımdan önce karar gerekir.
