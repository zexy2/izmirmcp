# AGENTS.md — İzmir MCP çalışma sözleşmesi

Bu dosya her oturumun başında okunur. Talimat çelişkisi varsa bu dosya ve
`PROGRESS.md` esastır.

## Mission

Upstream [istanbulmcp](https://github.com/Batu1-1an/istanbulmcp) deposunda
**yapılabilen ve İzmir'de gerçek veri karşılığı olan** her yeteneği, bu depoda
eşdeğer kalitede sağlamak.

Bu bir "her şeyi zorla kopyala" görevi değildir:

- İzmir'de kaynak yoksa veya erişilemiyorsa (404/500/HTML) **yapılmaz**; neden
  yapılmadığı README "Sınırlar" ve `PROGRESS.md` "Bilinçli boşluklar" altında
  kanıtla yazılır.
- İzmir'de upstream'den **daha iyi** veri varsa (ör. canlı otobüs konumu,
  İZDENİZ tarifesi) o üstünlük korunur.
- Hiçbir koşulda veri uydurulmaz.

## Değişmez kurallar

1. **Zarf sözleşmesi:** her araç çıktısı `ok, summary, data, freshness, sources,
   limits, warnings, next_queries, error, result_info` taşır.
2. **Hata taksonomisi:** kaynak arızası `source_unavailable`,
   `source_rate_limited`, `source_timeout` olarak zarfa döner. Hiçbir araç
   exception sızdırmaz. Geçersiz girdi `validation_error` + `error.field`.
3. **TDD:** önce başarısız test, sonra kod. İstisna yok.
4. **Dürüstlük:** boş sonuç "hiç yok" kanıtı değildir; bunu `warnings` içinde
   söyle. Kısmi sonuç `result_info.truncated`/`matched` ile bildirilir.
5. **Kaynak doğrulama:** yeni bir uç bağlamadan önce canlı HTTP ile doğrula.
   Sonucu `reports/` altına kanıtla yaz. Doğrulanmamış uç bağlanmaz.
6. **README güncel kalır:** araç tablosu ve "Sınırlar" bölümü her değişiklikle
   birlikte güncellenir.
7. **Commit:** her pass tek odaklı bir commit. Commit mesajı Türkçe, gövdesinde
   ne/neden yazılı. Kullanıcı istemeden push edilmez.

## Doğrulama komutları

```bash
.venv/bin/python -m pytest -q              # birim testleri (ağ yok)
.venv/bin/python scripts/smoke_live.py     # canlı kaynak duman testi
python -m app.stdio                        # stdio MCP el sıkışması
python -m app.main                         # HTTP sunucu (varsayılan 127.0.0.1:8000)
```

Pass bitmiş sayılması için: pytest yeşil **ve** smoke exit 0 **ve** README doğru.

## Mimari sınırlar (dosya sahipliği)

- `app/connectors/` — yalnızca dış kaynak okuma ve ayrıştırma. İş kuralı yok.
- `app/services/` — zarf, filtreleme, sıralama, uyarılar. Her veri türünün tek
  sahibi burasıdır; paralel implementasyon açılmaz.
- `app/storage/` — kalıcı yerel durum (GTFS SQLite).
- `app/core/` — zarf, doğrulama, geo, önbellek, HTTP güvenliği.
- `app/mcp/` — ince adaptörler: doğrula → servisi çağır → zarfı döndür.
  İş mantığı buraya taşınmaz.

## Bilinen İzmir gerçekleri (yeniden araştırmayın)

Ayrıntı ve kanıtlar `reports/` altında.

- ESHOT GTFS takvimi **2026-10-09'da bitti** (doğrulama 2026-10-28). Her yanıt
  `calendar_end` + eskime uyarısı taşır.
- ESHOT varış akışı ETA/dakika yayımlamaz; yalnızca kalan durak + konum.
- İZTEK ardışık isteklerde 429 verir (hız sınırı eklendi).
- `www.eshot.gov.tr` açık zip `Accept` başlığına 406 döner; `*/*` gerekir.
- İZSU arıza ucu hâlâ HTTP 500. Metro ekipman/arıza ve şehir geneli trafik 404.
- İZDENİZ GTFS ZIP'i HTML döndürüyor (kullanılmıyor).
- Kütüphane katmanı koordinat yayımlamaz.
