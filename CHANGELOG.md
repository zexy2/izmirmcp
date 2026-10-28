# Changelog

Bu proje [Semantic Versioning](https://semver.org/lang/tr/) izler.

## 0.1.0 — 2026-10-28

İlk sürüm. İzmir için salt okunur şehir verisi MCP sunucusu.

### Eklendi

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

### Sınırlar

- İZSU arıza akışı kaynakta HTTP 500; `kind=faults` açıkça unavailable döner.
- ESHOT GTFS takvimi 2026-10-09'da bitti; her yanıt `calendar_end` ve eskime
  uyarısı taşır.
- İZBAN duyuru akışı erişilemiyor; `operator="izban"` unavailable döner.
- Lisans seçilmedi; dağıtımdan önce karar gerekir.
