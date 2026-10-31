# ESHOT ulaşım kaynakları araştırması

Tarih: 2026-10-28
Kapsam: ESHOT durak listesi, canlı yaklaşan otobüs varışları, GTFS tarifesi
Yöntem: Doğrudan HTTP istekleri (`curl`), CKAN `package_show` / `datastore_search`,
resmî İZTEK web servis dokümanı (PDF), GTFS ZIP içerik incelemesi.

Bu rapor yalnızca **ölçülen** davranışı kaydeder. Erişilemeyen veya şüpheli
kaynaklar "kullanılmıyor" olarak işaretlenir; veri uydurulmamıştır.

## 1. Durak listesi — kullanılabilir

| Öğe | Değer |
|---|---|
| CKAN veri seti | `eshot-otobus-duraklari` (Otobüs Durakları) |
| Kaynak kimliği | `0c791266-a2e4-4f14-82b8-9a9b102fbf94` |
| DataStore | `datastore_active: true`, `total: 11965` |
| Kolonlar | `_id, DURAK_ID, DURAK_ADI, ENLEM, BOYLAM, DURAKTAN_GECEN_HATLAR` |
| CSV | <https://openfiles.izmir.bel.tr/211488/docs/eshot-otobus-duraklari.csv> (725.707 bayt, `;` ayraçlı, `Last-Modified: 2026-10-28 10:30:10 GMT`) |
| Lisans | Izmir Metropolitan Municipality Open Data License |

Ölçümler:

- CSV 11.965 satır, 11.965 benzersiz `DURAK_ID`, eksik koordinat yok.
- `datastore_search` ile `total` aynı: 11.965.
- `DURAKTAN_GECEN_HATLAR` virgülle değil **tire** ile ayrılmış hat listesidir
  (`"29-30"`, `"21-910-920-930-940-950"`).

Karar: durak listesi DataStore üzerinden sorgulanacak (725 KB dosya indirmek
gerekmez); koordinat bazlı yakınlık için tek sayfalık DataStore çekimi yapılır.

## 2. Canlı yaklaşan otobüs varışları — kullanılabilir

Resmî doküman: <https://openfiles.izmir.bel.tr/471231/docs/iztek-WebServisKullanimDokumani_1.0.pdf>
(İzmir İnovasyon ve Teknoloji A.Ş. — İzmirim Kart web servisleri V.1.0)

| Uç | Doğrulanan yanıt |
|---|---|
| `/api/iztek/duragayaklasanotobusler/{durakId}` | 200, JSON dizi (doküman örneği `21050` → 1 kayıt) |
| `/api/iztek/hattinyaklasanotobusleri/{hatId}/{durakId}` | 200, aynı şema (doküman örneği `446/21056` → 1 kayıt) |
| `/api/iztek/hatotobuskonumlari/{hatId}` | 200, `{"HataVarMi": false, "HatOtobusKonumlari": [...]}` |

Yanıt alanları: `KalanDurakSayisi` (int), `HattinYonu` (int), `KoorY`/`KoorX`
**ondalık virgüllü string**, `BisikletAparatliMi`, `EngelliMi`, `HatNumarasi`,
`HatAdi`, `OtobusId`.

Ölçülen davranış ve sınırlar:

- Doküman `KoorX`'i *enlem*, `KoorY`'yi *boylam* olarak tanımlıyor; canlı
  örneklerde `KoorX≈38.x` (enlem), `KoorY≈27.x` (boylam) doğrulandı.
- Geçersiz durak kimliği (`99999999`) **200 + boş dizi** döndürür; "servis yok"
  ile "veri yok" ayırt edilemez. Bu yüzden 200 + boş yanıt `no_nearby_buses`
  uyarısıyla sunulur, boş sonuç "sefer yok" diye yorumlanmaz.
- Varış dakikası/ETA alanı **yoktur**; yalnızca kalan durak sayısı ve anlık
  araç konumu vardır.
- Yoğun ardışık isteklerde `429 {"message":"API rate limit exceeded"}` görüldü;
  kısa bekleme sonrası toparlandı. Bu nedenle bağlantıda yumuşak hız sınırı ve
  kararlı `source_rate_limited` hata eşlemesi uygulanır.
- Sayısal olmayan kimlik (`abc`) için 400
  `{"Message":"Lutfen gecerli parametre giriniz."}`.

## 3. GTFS tarifesi — kısmen kullanılabilir

CKAN veri seti `toplu-ulasim-gtfs-verileri` (Toplu Ulaşım GTFS Verileri),
`metadata_modified: 2026-04-03`.

| Mod | URL | Canlı sonuç |
|---|---|---|
| Otobüs (EShot) | <https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip> | **200, geçerli ZIP, 18.410.657 bayt** |
| Metro | <https://www.izmirmetro.com.tr/gtfs/rail-metro-gtfs.zip> | 200, geçerli ZIP, 116.277 bayt |
| Tramvay | <https://www.tramizmir.com/gtfs/rail-tramizmir-gtfs.zip> | 200, geçerli ZIP, 158.951 bayt |
| İZBAN | <https://www.izban.com.tr/gtfs/rail-izban-gtfs.zip> | 200, geçerli ZIP, 40.841 bayt |
| İZDENİZ | <https://www.izdeniz.com.tr/gtfs/ship-izdeniz-gtfs.zip> | **200 ama `text/html` (912 bayt) — ZIP değil** |

EShot ZIP içeriği (açılmış boyut ~100 MB): `shapes.txt`, `stop_times.txt`
(2.108.737 satır, 85,9 MB), `stops.txt` (11.740 satır), `trips.txt`,
`agency.txt`, `calendar.txt`, `routes.txt`.

**Kritik güncellik bulgusu:** EShot `calendar.txt` yalnızca
`20260805–20261005` (hafta içi), `20260808–20261008` (Cumartesi),
`20260809–20261009` (Pazar) aralığını kapsar. Doğrulama tarihi **2026-10-28**,
yani servis takvimi **yaklaşık üç hafta önce sona ermiş**. Dosyanın ZIP zaman
damgası da `2026-08-05`. Metro ve tramvay takvimleri 2026-07 → 2027-07 aralığını
kapsıyor; İZBAN feed'i ise **2023-03 tarihli** ve takvimi 2025-01-01'de bitiyor.

Karar:

- Yalnızca **EShot GTFS** bağlanır ve her sonuçta "takvim penceresi geçmiş
  olabilir" uyarısı ile `calendar_end` sınırı döndürülür.
- `stop_times.txt` (2,1M satır) istek anında belleğe alınmaz; yalnızca
  `stops.txt` (durak listesi) ve `routes.txt`/`trips.txt`/`calendar.txt`
  (hat servis bilgisi) sınırlı boyutta okunur. Kalkış saatleri istek anında
  yüklenmez; bunun için `source_unavailable` değil, açık bir `limits` maddesi
  kullanılır.
- İZDENİZ GTFS ZIP'i HTML döndürdüğü için kullanılmaz; `source_unavailable`.

## Bağlanmayan yollar

- `/api/eshot/...`, `/api/hareketliotobusler`, `/api/duraklar`, `/api/hatlar`,
  `/api/iztek`, `/api/iztek/hatlar`, `/api/hatbilgileri/...` → **404
  "no Route matched"**. Bu yollar tahmin edilmiştir ve gerçek değildir.
- `/api/ibb/cbs/noktayayakinduraklar?x=&y=&inCoordSys=&outCoordSys=` yalnızca
  dokümandaki boş şablon ile yayımlanmıştır; **projeksiyon parametrelerinin
  anlamı doğrulanamadı** (test isteğinde metre cinsinden koordinat döndü).
  Bu nedenle bağlanmadı.
- `eshot.gov.tr/gtfs` (uzantısız) → 403; `eshot.gov.tr/gtfs.zip` → 404.
