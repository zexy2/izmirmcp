# REA ile İzmir Açık Veri Portalı incelemesi

Tarih: 2026-10-28
Araç: REA 6.8.0 (`rea-agents`), Chrome 156 üzerinden CDP
Hedef: <https://acikveri.bizizmir.com/>
Kanıt dosyası: [rea-open-data-portal-evidence.json](rea-open-data-portal-evidence.json)

## Amaç

İzmir MCP'nin katalog katmanını kurmadan önce portalın gerçekten bir CKAN
kurulumu olup olmadığını ve statik paket içinde API yollarının görünüp
görünmediğini bağımsız bir araçla görmek.

## Kullanılan komutlar

```bash
# 1) Headless Chrome'u CDP ile başlat
Google Chrome --headless=new --remote-debugging-port=9333 \
  --user-data-dir=/tmp/rea-chrome-profile https://acikveri.bizizmir.com

# 2) Hedefi listele
rea list-browser-targets http://127.0.0.1:9333

# 3) Sayfa paketini statik analiz et ve kanıtı kaydet
rea analyze-web-bundle http://127.0.0.1:9333 <targetId> \
  --observation-ms 4000 --detail complete \
  --evidence_output reports/rea-open-data-portal-evidence.json
```

## Bulgular

- Sayfa başlığı: “Hoşgeldiniz - İzmir Büyükşehir Belediyesi Açık Veri Portalı”.
- 11 script yakalandı; 239.183 AST düğümü gezildi, 0 parse hatası.
- REA `completeness.status=partial` bildirdi; bazı AST projeksiyonları
  konservatif olarak genişletildi (`unknowns` alanında listeleniyor).
- Statik pakette `api/3/action/...` biçiminde sabit bir CKAN yolu **bulunmadı**.
  Bu, portalın katalog çağrılarını dinamik kurduğunu gösterir; API yolları
  yalnızca paket analizinden çıkarılamaz.

## Bu nedenle ayrıca yapılan canlı doğrulama

REA statik analiz sağlar; ağ isteği yakalamaz. Katalog uçları doğrudan HTTP
istekleriyle doğrulandı (2026-10-28):

| Uç | Sonuç |
|---|---|
| `acikveri.bizizmir.com/api/3/action/package_list` | 200, JSON |
| `acikveri.bizizmir.com/api/3/action/package_search?q=otopark` | 200, JSON |
| `acikveri.bizizmir.com/api/3/action/datastore_search?...` | 200, JSON (DataStore etkin) |
| `openapi.izmir.bel.tr/api/ibb/izum/otoparklar` | 200, JSON |
| `openapi.izmir.bel.tr/api/ibb/nobetcieczaneler` | 200, JSON |
| `openapi.izmir.bel.tr/api/ibb/cevre/havadegerleri/{tarih}` | 200, JSON |
| `openapi.izmir.bel.tr/api/metro|izban|izdeniz/...` | 200, JSON |
| `openapi.izmir.bel.tr/api/izsu/barajdurum` | **500** |
| `openapi.izmir.bel.tr/api/izsu/arizakaynaklisukesintileri` | **500** |
| `openfiles.izmir.bel.tr/.../izsu-baraj-doluluk-oranlari.csv` | 200, CSV |

## Sınırlar

- REA çıktısı statik paket analizidir; canlı ağ trafiği veya API yanıtı kanıtı
  değildir. Bu yüzden yukarıdaki HTTP doğrulaması ayrı tutuldu.
- Analiz `partial` tamamlandı; dinamik olarak oluşturulan URL'ler statik
  pakette görünmeyebilir.
- Portalın kullanım koşulları ve veri lisansları ayrıca değerlendirilmelidir;
  erişilebilirlik lisans izni anlamına gelmez.
