# PROGRESS — İzmir MCP

Son güncelleme: 2026-10-28
Durum: **17 araç, 151 test, 21/21 canlı smoke.** Mission: upstream parity
(olabildiğince, İzmir verisi olan kadarıyla).

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

## Sırada (öncelik sırasıyla)

### P1 — Çok operatörlü ulaşım aksaklıkları
Şu an yalnızca ESHOT hat duyuruları var. Metro, İZBAN ve İZDENİZ için
makine-okunur duyuru/aksaklık ucu araştırılacak. Her operatör ayrı `sources[]`
kaydı taşır; erişilemeyen operatör `unavailable` döner, "sorun yok" sayılmaz.

### P2 — Paketleme ve yayın hazırlığı
- `Dockerfile` + `.dockerignore`
- `server.json` (MCP registry manifesti)
- `.github/workflows/ci.yml` (pytest + smoke + import kontrolü)
- `CHANGELOG.md`

### P3 — Dokümantasyon seti (`docs/`)
Upstream'de 18 doküman var. İzmir için gerçekten gerekli olanlar:
- `response-contract.md` — zarf sözleşmesi
- `tool-reference.md` — 17 aracın girdi/çıktı sözleşmesi
- `deployment.md` — env değişkenleri, auth, CORS, çok işçili notlar
- `sources.md` — kaynak envanteri ve lisans durumu
- `monitoring.md` — `/healthz`, `/readyz`, `/status`, log formatı

### P4 — Sözleşme ve güvenlik testleri
- Tüm araçların zarf alanlarını doğrulayan conformance testi
- Keşif yüzeyi testi (tools/resources/prompts şema uyumu)
- Güvenlik testleri: auth bypass, origin bypass, büyük gövde, XFF spoofing

### P5 — Adres geocoding (opsiyonel)
Nominatim politikası, önbellek, rate limit ve ODbL atıf gerektirir. Parity
değil, farklılaşma. Ancak P0–P4 bittikten sonra.

## Bilinçli boşluklar (yapılmayacak, kanıtlı)

| Upstream yeteneği | İzmir durumu |
|---|---|
| Şehir geneli trafik indeksi | `ibb/trafikyogunluk` → 404. Yalnız geçmiş XLSX + 2023 kamera listesi var. |
| Metro ekipman/erişilebilirlik | `metro/ekipmanlar`, `metro/arizalar` → 404. |
| İZSU arıza akışı | `izsu/arizakaynaklisukesintileri` → 500. `kind=faults` açıkça unavailable. |
| Sosyal tesis nearby | "Sosyal tesis" adıyla yayımlanmış veri seti yok. |
| Sınırlı SQL (datastore_query) | Bilinçli olarak yok; yalnız güvenli `filters` + limit. |
| Legacy araç alias'ları | Yayımlanmış eski ad yok; alias gereksiz. |
| İZDENİZ GTFS | ZIP HTML dönüyor; mevcut openapi sefer araçları kullanılıyor. |
| İZBAN GTFS | 2023 feed, takvim 2025-01-01'de bitti; güncel değil. |

## Bilinen riskler

- GTFS SQLite deposu (`.data/`, ~141 MB) git dışında; ilk kalkış sorgusu
  birkaç saniye sürer. `.data/` yoksa yeniden kurulur.
- Hız sınırı ve sayaçlar süreç içi; çok işçili dağıtımda işçi başına bütçe.
- Lisans: depoda LICENSE yok. Upstream'de de yok. Yayımlamadan önce karar gerekli.
