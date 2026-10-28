# Yer, mahalle ve ilçe çözümleme

`place` ve `place_district` parametrelerinin nasıl çözüldüğünü ve neden
serbest metin adres geçmediğini açıklar. Kod: `app/services/places.py`,
veri: `app/data/places.json` ve `app/data/neighborhoods.json`.

## İki katmanlı kaynak

| Katman | Kaynak | Kayıt | Kullanım |
|---|---|---|---|
| Mahalle envanteri | CKAN `muhtarliklar` (`7d0b7f55-…`) | 1.292 muhtarlık → **1.219** benzersiz mahalle, 30 ilçe | `place` ile en çok eşleşen |
| Elle seçilmiş | OpenStreetMap Nominatim | 30 ilçe + 24 simge yer | İlçe adları ve `Kemeraltı`, `Kültürpark` gibi mahalle olmayan yerler |

Her iki katman da **gömülü dosyadır**; çözümleme ağa çıkmaz.

## Çözümleme sırası

1. Ad Türkçe'ye duyarlı normalize edilir (`İ`/`I`, `ş`/`s`, büyük/küçük).
2. `", izmir"` / `" izmir"` soneki kırpılır.
3. **İlçe etiketi mahalleye üstündür.** İzmir'de Konak ilçesi içinde "Konak"
   mahallesi, Torbalı içinde "Karşiyaka" mahallesi var; ilçe yorumu kazanır.
4. Eşleşme tek ise o döner.
5. Birden çok mahalle eşleşirse **hata**: adaylar listelenir ve
   `place_district` istenir. Sessizce ilk eşleşme **seçilmez**.

```text
place="Konak"                      -> Konak ilçesi
place="Abdi İpekçi"                -> Abdi İpekçi mahallesi (Karabağlar)
place="Atatürk"                    -> validation_error: 17 ilçede geçiyor
place="Atatürk", place_district="Bornova" -> Atatürk mahallesi (Bornova)
```

## Neden serbest metin adres yok

- İzmir'de resmî makine-okunur geocoding ucu **yok**
  (`openapi .../ibb/cbs/adres*` → 404; doğrulama 2026-10-28).
- Nominatim'i birincil geocoder yapmak kullanım politikası, önbellek ve hız
  sınırı yükü getirir; oysa yayımlanmış envanter İzmir sorgularının çoğunu
  karşılıyor.
- Bir sokak adresini mahalle noktasına indirgemek, olmayan bir kesinlik iddia
  eder. Bunun yerine açık hata döner.

## Hassasiyet

Mahalle noktası, o mahalledeki **muhtarlık noktalarının ortalamasıdır**. Mahalle
sınırı, poligon veya kapı koordinatı **değildir**. Yarıçap sorgularında bu
yaklaşıklık `warnings` içinde belirtilir.

## Ad normalizasyonu

Yayımlanan adlar BÜYÜK harftir. `str.title()` Türkçe `i`'yi birleşik noktalı
(`U+0307`) yaptığı için özel bir `turkish_title` kullanılır:

```text
AŞAĞIŞAKRAN   -> Aşağışakran
ABDİ İPEKÇİ   -> Abdi İpekçi
1.KADRİYE     -> 1.Kadriye
B.HAYRETTİN PAŞA -> B.Hayrettin Paşa
```
