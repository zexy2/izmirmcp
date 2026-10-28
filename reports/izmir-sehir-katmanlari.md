# İzmir şehir katmanları araştırması

Tarih: 2026-10-28
Kapsam: semt pazarı, ESHOT hat duyuruları, WizmirNET, İzmirim Kart dolum, kütüphane
Yöntem: CKAN `package_show` / `datastore_search`, doğrudan CSV/HTTP istekleri.

## Bağlanan katmanlar

| Katman | Kaynak | Ölçüm |
|---|---|---|
| Semt pazarı | `semt-pazar-yerleri` / `3e63e16e-74a9-40f6-8ad3-043ad4fa4a16` | 186 kayıt, `ILCE/MAHALLE/ADI/ENLEM/BOYLAM/ACIKLAMA`, `metadata_modified 2026-10-26` |
| ESHOT duyuru | `eshot-otobus-hat-duyurulari.csv` | 124 satır, `HAT_NO;BASLIK;BASLAMA_TARIHI;BITIS_TARIHI` |
| WizmirNET | `kablosuz-internet-baglanti-noktalari` / `60ca8451-…` | 857 kayıt, `ILCE/MAHALLE/ADI/ENLEM/BOYLAM` |
| İzmirim Kart | `izmirim-kart-dolum-noktalari` / `7a3efbec-…` | 1.120 kayıt, `ADDRESS/LATITUDE/LONGITUDE`, `metadata_modified 2023-08-21` |
| Kütüphane | `izmir-buyuksehir-belediyesi-kutuphaneleri-bilgileri` / `0c1b15b9-…` | 10 kayıt, **koordinat kolonu yok** |

## Ölçülen tuzaklar

- Pazar günü bilgisi ayrı bir kolon değil, `ACIKLAMA` serbest metninde:
  "Cumartesi  günü kurulmaktadır", "Cumartesi Günü Kurulmnaktadır" (yazım hatası).
  Ayrıştırma yalnızca açık Türkçe gün adı eşleşmesiyle yapılır; eşleşmeyen
  kayıt `day_confidence="unknown"` alır.
- Koordinatlar Türkçe ondalık virgülle string olarak gelebiliyor (`"38,45441058"`).
  Ayrıştırıcı yalnızca ondalık biçimi kabul eder; keyfî tam sayıyı ölçeklemez.
- WizmirNET kaynağı aynı konumu birden çok satırla yayımlıyor; Konak 800 m
  yarıçapında 92 satırın 33'ü yinelenen. Eşleşen kayıtlarda konum/adres bazlı
  tekilleştirme yapılır ve birleştirilen sayı uyarıda bildirilir.
- Kütüphane katmanı adres ve çalışma saati verir, koordinat vermez. Yakınlık
  hesabı ve yarıçap filtresi bu katmana uygulanmaz.

## Bağlanmayan yollar

- `openapi.izmir.bel.tr/api/ibb/trafikyogunluk`, `/ibb/trafik`, `/ibb/wifi`,
  `/ibb/sosyaltesisler`, `/ibb/kutuphane` → **404**.
- `openapi.izmir.bel.tr/api/metro/ekipmanlar`, `/metro/arizalar` → **404**.
- `izsu/arizakaynaklisukesintileri` → **hâlâ 500**.
- "Sosyal tesis" adıyla yayımlanmış veri seti yok; `turizm-tesisleri` ve
  `onemli-yerler-listesi` farklı kapsamlardır, bu nedenle bağlanmadı.
- Elektrikli araç şarj: yalnızca `engelli-sarj-istasyonlari-konum-verisi`
  (XLSX) var; CSV/DataStore yayını doğrulanmadığı için bağlanmadı.
