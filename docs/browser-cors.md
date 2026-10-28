# Tarayıcı erişimi ve CORS

Bu sunucu **tarayıcı uygulamalarından** çağrılabilir, ancak varsayılan olarak
yalnızca `Origin` göndermeyen istemcilere (CLI, masaüstü MCP istemcileri,
sunucu-sunucu) açıktır. Tarayıcı isteği geldiğinde origin **açıkça** izinli
olmalıdır.

## Varsayılan davranış

| `IZMIR_MCP_CORS_ALLOWED_ORIGINS` | Origin gönderen tarayıcı | Origin göndermeyen istemci |
|---|---|---|
| boş (varsayılan) | **403 `origin_not_allowed`** | ✅ çalışır |

Bu "fail closed" yaklaşımıdır: yanlış yapılandırılmış bir dağıtım her siteye
açılmak yerine hiçbir tarayıcıya açılmaz.

## İzin listesi

```bash
export IZMIR_MCP_CORS_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"
```

Kurallar (başlangıçta doğrulanır, ihlal `ValueError` ile süreci durdurur):

- En fazla **32** benzersiz origin.
- `https://` zorunlu; `http://` yalnızca `localhost`, `127.0.0.1`, `[::1]` için.
- Şema + host + (varsa) port dışında hiçbir şey yok: yol, sorgu, fragment yok.
- Joker (`*`), yüzde kodlama, kimlik bilgisi (`user:pass@`) yok.
- Host küçük harf olmalı.

## Yanıt başlıkları

İzinli origin'de:

```http
Access-Control-Allow-Origin: https://app.example.com
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Accept, Content-Type, Authorization, Mcp-Session-Id, ...
Access-Control-Expose-Headers: Mcp-Session-Id, Mcp-Protocol-Version, WWW-Authenticate, Retry-After
Access-Control-Max-Age: 600
```

`Access-Control-Allow-Credentials` **gönderilmez**: kimlik Bearer başlığıyla
taşınır, çerezle değil.

## Preflight

`OPTIONS /mcp/` kimlik doğrulaması ve hız sınırı tüketmeden `204` döner; gerçek
istekler tüm koruma katmanlarından geçer.

## Yaygın hatalar

| Belirti | Neden |
|---|---|
| Tarayıcıda `403 origin_not_allowed` | Origin listede değil |
| Preflight 200 ama asıl istek 401 | Bearer anahtarı eksik (CORS ile auth ayrı katman) |
| `Access-Control-Allow-Origin` hiç yok | Origin başlığı gönderilmiyor veya izin listesi boş |
| Sunucu açılmıyor, `ValueError` | Origin biçimi geçersiz (yol/joker/http) |

## Sınırlar

- Origin kontrolü **tarayıcı** içindir; CLI istemciler bu kontrolü atlar ve
  güvenlikleri Bearer anahtarına dayanır.
- DNS rebinding koruması SDK'nın kendi taşıma güvenliğine bırakılmıştır.
- Yalnızca `localhost`/`127.0.0.1` bağlanmada Host başlığı politikası SDK
  varsayılanıdır; genel bir adrese bağlanırken reverse proxy kullanın.
