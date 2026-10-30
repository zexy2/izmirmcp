# Yapılandırma

Bu belge görev odaklıdır: hangi senaryoda hangi ortam değişkenlerinin
ayarlanacağını anlatır. Her değişkenin tam listesi ve varsayılanı
[Dağıtım](deployment.md#ortam-değişkenleri) belgesindedir ve
`tests/test_docs.py` ile `app/core/settings.py`'ye karşı kilitlidir. Örnek
dosya: `.env.example`.

## Profil 1: yerel geliştirme (varsayılan)

Hiçbir şey ayarlamanız gerekmez. Sunucu `127.0.0.1:8000`'e bağlanır, kimlik
doğrulama kapalıdır, Host başlığı doğrulanmaz (yalnızca bir kez uyarı loglanır),
tarayıcı origin'leri reddedilir.

## Profil 2: yerel konteyner

`docker compose up --build` `docker-compose.yml`'yi kullanır: port yalnızca
loopback'e açılır, kök dosya sistemi salt okunurdur, tüm Linux yetenekleri
düşürülür, `IZMIR_MCP_ALLOWED_HOSTS=localhost,127.0.0.1` ve
`IZMIR_MCP_EVENT_LOOP_WATCHDOG_SECONDS=60` ayarlıdır. GTFS deposu `/data`
biriminde ilk açılışta kurulur; CI'da `IZMIR_MCP_SKIP_GTFS_BUILD=1` ile atlanır.

## Profil 3: genel (internete açık) dağıtım

Genel bir adrese bağlanmadan önce en az şunları ayarlayın:

| Değişken | Neden |
|---|---|
| `IZMIR_MCP_HOST=0.0.0.0` | Konteyner/PaaS içinde dinleme. |
| `IZMIR_MCP_API_KEYS` | Virgülle ayrılmış anahtarlar; bkz. [API erişimi](api-access.md). |
| `IZMIR_MCP_REQUIRE_AUTH=true` | Anahtar tanımlı değilse sunucu açılmaz (fail closed). |
| `IZMIR_MCP_ALLOWED_HOSTS` | Genel alan adınız; DNS rebinding'e karşı `421` döner. |
| `IZMIR_MCP_CORS_ALLOWED_ORIGINS` | Yalnızca tarayıcı istemcisi varsa; bkz. [CORS](browser-cors.md). |
| `IZMIR_MCP_API_KEY_DAILY_QUOTA` | Anahtar başına günlük çağrı tavanı. |
| `IZMIR_MCP_EVENT_LOOP_WATCHDOG_SECONDS` | Takılan olay döngüsünde süreci yeniden başlatır. |

`IZMIR_MCP_REQUIRE_AUTH` ve `IZMIR_MCP_ALLOWED_HOSTS` geriye dönük uyumluluk
için varsayılan olarak kapalıdır; genel dağıtımda açmak operatörün işidir.

## Upstream dayanıklılığı

- `IZMIR_MCP_REQUEST_TIMEOUT_SECONDS`, `IZMIR_MCP_REQUEST_ATTEMPTS`: istek başına
  zaman aşımı ve deneme sayısı.
- `IZMIR_MCP_HTTP_TOTAL_DEADLINE_SECONDS`: denemeler dahil toplam süre; `0` kapalı.
- `IZMIR_MCP_RESPONSE_MAX_BYTES`: akış halinde okunan gövde tavanı.
- `IZMIR_MCP_SOURCE_RATE_*`: upstream başına token bucket.
- `*_STALE_IF_ERROR_SECONDS`: kaynak düşükken son iyi yanıtı `stale` olarak sunma süresi.
- `IZMIR_MCP_SOURCE_CACHE_MAX_ENTRIES`: bellek içi önbellek tavanı.

## Yalnızca test için

`IZMIR_MCP_ALLOW_PRIVATE_UPSTREAMS=1` yerel test sunucularına bağlanmak için
özel/loopback upstream'lere izin verir. Üretimde asla ayarlamayın; bkz.
[Güvenlik](security.md). Canlı testler `IZMIR_LIVE=1` ile açılır.
