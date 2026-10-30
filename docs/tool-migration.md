# Araç geçiş politikası

Bu belge MCP araç yüzeyinin nasıl değiştiğini ve istemcilerin neye
güvenebileceğini anlatır.

## Uyumluluk sözü

- Yayımlanmış bir aracın **adı** değişmez ve araç kaldırılmaz.
- Yayımlanmış bir aracın **girdi şeması** değişmez: parametre kaldırılmaz,
  yeniden adlandırılmaz, tipi daraltılmaz, isteğe bağlı parametre zorunlu olmaz.
- Yeni araçlar, yeni prompt'lar ve yeni kaynaklar eklenebilir.
- Yanıt zarfına yeni alan eklenebilir; mevcut alanlar kaldırılmaz. Bkz.
  [Yanıt sözleşmesi](response-contract.md).

Bu söz `tests/test_tool_compatibility.py` ile uygulanır: mevcut araçların adları
ve girdi şemaları `tests/fixtures/tool_compatibility_snapshot.json` ile birebir
karşılaştırılır. Anlık görüntü yalnızca kasıtlı ve CHANGELOG'da belgelenmiş bir
kırıcı değişiklikte (yeni ana sürüm) yeniden üretilir.

## Kırıcı değişiklik süreci

1. Yeni davranışı yeni bir araç adıyla ekleyin; eski aracı koruyun.
2. Eski aracın açıklamasına kullanımdan kaldırma notu ve yeni aracın adını yazın.
3. CHANGELOG'un "Kullanımdan kaldırıldı" bölümüne ekleyin.
4. Eski araç en erken bir sonraki **ana** sürümde kaldırılabilir; o sürümde
   anlık görüntü yeniden üretilir.

## Değişiklik geçmişi

| Sürüm | Değişiklik | İstemci etkisi |
|---|---|---|
| 0.1.0 | 22 araç ve 7 prompt; `nobetci_eczane` prompt'u ilk sürüme eklendi (mevcut `izmir_nearby` aracını kullanır). | Yok; araç yüzeyi değişmedi. |

## Bilinçli olarak eklenmeyenler

Açık ve güvenilir bir kaynağı olmayan yetenekler araç olarak eklenmez. Örnek:
metro asansör durumu. İzmir OpenAPI'de (`metro/asansor*`) uç yok, açık veri
kataloğunda ilgili veri seti yok. Ayrıntı: [Kaynaklar](sources.md).

## Konsol komutları ve paket

`izmir-mcp` ve `izmir-mcp-stdio` komutları ile `server.json` paket tanımları da
aynı uyumluluk sözü altındadır; `tests/test_packaging.py` ile kilitlidir.
