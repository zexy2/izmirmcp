# Operatör duyuru/aksaklık kaynakları

Tarih: 2026-10-28
Kapsam: Metro, İZBAN, İZDENİZ duyuru akışları
Yöntem: Resmî sitelerin JS paketlerinin statik analizi + doğrudan HTTP.

## Bağlanan kaynaklar

### İzmir Metro (ve tramvay)
- **Uç:** `https://metrotramapi.iztek.tr/api/v1/announcements`
- **Bulunuş:** `www.izmirmetro.com.tr/assets/index-*.js` içinde
  `baseURL:"https://metrotramapi.iztek.tr/api/v1"` ve `ht.get("/announcements")`.
- **Ölçüm:** HTTP 200, `{"data":[],"isSuccessful":true,"statusCode":200}`.
  Doğrulama anında duyuru listesi **boş**; bu bir hata değil, kaynağın o anki
  durumu. Bağlayıcı boş listeyi "duyuru yok" diye sunmuyor, uyarı ekliyor.
- Aynı tabanda `/tramannouncements`, `/lines`, `/day-types` de 200 dönüyor.

### İZDENİZ
- **Uç:** `https://coreapi.izdeniz.com.tr/api/v1/announcements?version=1&isPublished=true&page=1&pageSize=20`
- **Bulunuş:** `www.izdeniz.com.tr/assets/index-*.js` içindeki
  `` `${sf}/api/v${Hc}/announcements?version=...` `` şablonu ve
  `https://coreapi.izdeniz.com.tr` kökü.
- **Ölçüm:** HTTP 200, `{"data":{"data":[...]}}` — 3 gerçek duyuru
  (ör. "Bergama Vapuru ile tarihe yolculuk başladı", 2026-10-26).
- Yanıt iki katmanlı: `data.data` listesi; `title`, `slug`, `summary`,
  `publishDate`.

## Bağlanmayan: İZBAN

Erişilebilir makine-okunur duyuru akışı **yok**:

| Denenen | Sonuç |
|---|---|
| `www.izban.com.tr/Rss.aspx?MenuId=45` | 302 → `FileNotFound.htm` |
| `Sayfalar/Duyuru.aspx?MenuId=43` | 302 → `FileNotFound.htm` |
| `Single.aspx?MenuId=` 15/17/26/28/43/45/22 | hepsi 302 → `FileNotFound.htm` |
| `metrotramapi.iztek.tr/api/v1/izbanannouncements` | 404 |
| `metrotramapi.iztek.tr/api/v1/izban-announcements` | 404 |
| `metrotramapi.iztek.tr/api/v1/announcements/izban` | 400 |
| CKAN `package_search?q=izban duyuru` | 0 sonuç |

Karar: `operator="izban"` isteği `source_unavailable` döner ve uyarıda
nedenini yazar. Duyuru yok sayılmaz.

## Tasarlanan davranış

- `operator` verilmezse ESHOT + Metro + İZDENİZ birleştirilir.
- Erişilemeyen operatör sonuçtan düşer, `warnings` içinde `unavailable` olarak
  adı geçer; "o operatörde aksaklık yok" sonucu çıkarılmaz.
- Boş duyuru listesi döndüren operatör ayrıca uyarı alır (`kanıtı değildir`).
- Yalnızca ESHOT makine-okunur geçerlilik penceresi yayımlar; diğer
  operatörlerde `active` **null** döner (bilinmiyor ≠ etkin değil).
- Sıralama: etkin olanlar önce, sonra en yeni yayımlanan.
