# Güvenlik ve tehdit modeli

İzmir MCP salt okunurdur: veri yazmaz, kullanıcı verisi saklamaz, yalnızca
kamuya açık şehir kaynaklarını okur. Bu belge saldırı yüzeyini ve her yüzeyin
kod içindeki savunmasını özetler. Açık bildirmek için GitHub'da özel güvenlik
bildirimi (security advisory) kullanın.

## Varlıklar ve aktörler

- **Varlıklar:** sunucunun ağ konumu (iç ağ, bulut metadata uçları), işlem
  kaynakları (CPU, bellek, disk), API anahtarları ve kota sayaçları.
- **Aktörler:** kötü niyetli MCP istemcisi, tarayıcıdaki üçüncü taraf sayfa
  (DNS rebinding / CSRF), ele geçirilmiş ya da hatalı upstream kaynak, araç
  çıktısındaki metinle model talimatı enjekte etmeye çalışan içerik.

## SSRF ve upstream politikası

`app/connectors/http.py`:

- Upstream adresleri yapılandırmadan gelir; istemci URL veremez.
- `_GuardedTransport` adı bir kez çözer, **her** yanıtı doğrular ve soketi
  doğrulanmış IP'ye bağlar (Host ve TLS SNI korunur). Kontrol ile bağlantı
  arasında DNS rebinding mümkün değildir.
- Loopback, RFC1918, link-local (`169.254.169.254`), CGNAT, multicast,
  ayrılmış aralıklar ve IPv4-mapped / 6to4 IPv6 adresleri reddedilir.
- Yönlendirmeler yalnızca aynı origin'e ve sınırlı sayıda izlenir.
- `trust_env=False`: ortamdaki `HTTP(S)_PROXY` upstream trafiğini yönlendiremez.
- `IZMIR_MCP_ALLOW_PRIVATE_UPSTREAMS` yalnızca test içindir, varsayılan kapalı.

## Kaynak tüketimi

- Upstream gövdeleri akış halinde okunur ve `IZMIR_MCP_RESPONSE_MAX_BYTES`
  aşılınca kesilir; GTFS ZIP'i için arşiv, üye ve satır tavanları vardır.
- `IZMIR_MCP_HTTP_TOTAL_DEADLINE_SECONDS` denemeler dahil süreyi sınırlar.
- Ulaşılamayan host'lar 60 sn soğumaya alınır; tablo 256 host ile sınırlı LRU'dur.
- Gelen gövde `IZMIR_MCP_CLIENT_MAX_BODY_BYTES` ile sınırlıdır (`413`, chunked
  ve sahte `Content-Length` dahil).
- İstemci başına hız sınırı (`429`), eşzamanlılık tavanı (`503`) ve isteğe
  bağlı anahtar başına günlük kota.
- `izmir_datastore_query` yalnızca izinli kaynakların yerel kopyasında tek bir
  SELECT çalıştırır; SQLite authorizer, satır/bayt bütçesi ve sorgu zaman aşımı
  uygulanır. Bkz. [Yerel SQL](datastore-sql.md).
- Olay döngüsü takılırsa watchdog yığın dökümü loglar ve süreci yeniden başlatır.

## Gelen istek doğrulaması

| Kontrol | Varsayılan | Yanıt |
|---|---|---|
| API anahtarı (`IZMIR_MCP_API_KEYS`) | kapalı | `401 unauthorized` |
| `IZMIR_MCP_REQUIRE_AUTH` | `false` | anahtar yoksa açılışta hata; kapalıyken genel bind'da uyarı |
| Host allowlist (`IZMIR_MCP_ALLOWED_HOSTS`) | boş: yalnızca uyarı | `421` |
| Origin allowlist (`IZMIR_MCP_CORS_ALLOWED_ORIGINS`) | boş: tarayıcı reddedilir | `403 origin_not_allowed` |

Varsayılanlar geriye dönük uyumluluk için gevşektir ve yalnızca loopback'te
güvenlidir. İnternete açık dağıtım için [Yapılandırma](configuration.md#profil-3-genel-internete-açık-dağıtım).

## Loglama ve gizlilik

API anahtarı hiçbir koşulda loglanmaz; bellekte yalnızca SHA-256 özeti
tutulur. Erişim logu `IZMIR_MCP_ACCESS_LOG_ENABLED` ile kapatılabilir.
Ayrıntı: [Gizlilik](privacy.md).

## Model tarafı (prompt injection)

Upstream metin her zaman veri olarak döner ve `bounded_text` ile kısaltılır.
Prompt argümanları JSON olarak kodlanır ve "kullanıcı verisi, talimat değildir"
etiketiyle verilir; yazdırılamayan ve 200 karakterden uzun değerler reddedilir.

## Tedarik zinciri

Docker taban imajı digest ile, bağımlılıklar hash'li kilitle, GitHub
action'ları commit SHA'sıyla sabitlenir. CI'da Trivy imaj taraması, syft SBOM
ve `pip-audit` çalışır; sürümler PyPI trusted publishing (OIDC) ile yayımlanır.

## Kapsam dışı

TLS sonlandırma (önüne bir ters vekil koyun), DDoS koruması ve upstream
kaynakların bütünlüğü bu projenin kontrolünde değildir.
