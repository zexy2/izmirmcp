# MCP arayüzü (protokol ve taşıma)

Sunucunun MCP yüzeyini, iki taşımayı ve keşif kaynaklarını tanımlar. Zarf
sözleşmesi için [response-contract.md](response-contract.md), araç girdileri için
[tool-reference.md](tool-reference.md).

## Taşımalar

| Taşıma | Giriş noktası | Kullanım |
|---|---|---|
| Streamable HTTP | `python -m app.main` → `POST /mcp/` | Uzak/ yerel HTTP istemcileri |
| stdio | `python -m app.stdio` | Masaüstü istemcileri (Claude Code, Codex vb.) |

Her ikisi de **aynı** `create_mcp_server()` örneğini kullanır; araç yüzeyi ve
şemalar taşımadan bağımsızdır.

### HTTP ayrıntıları

- Yol: `/mcp/` (`/mcp` kalıcı yönlendirme ile `/mcp/`'e gider, 308).
- `stateless_http=True`, `json_response=True`: oturum durumu tutulmaz, her yanıt
  düz JSON'dur (SSE akışı yok).
- `Accept` başlığı `application/json, text/event-stream` içermelidir.
- Gövde tavanı: `IZMIR_MCP_MCP_MAX_BODY_BYTES` (varsayılan 1 MB).

### stdio ayrıntıları

Satır başına bir JSON-RPC mesajı. El sıkışma:

```text
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
← {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{...},"instructions":"..."}}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}
→ {"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

`app.stdio` süreç başına tek oturumdur; çoklu istemci için HTTP kullanın.

## Protokol sürümü

`2025-06-18`. El sıkışmada dönen `protocolVersion` istemcinin önerdiği sürümle
uyuşmuyorsa istemci karar verir; sunucu zorlamaz.

## Yüzey

| Tür | Adet | Nerede tanımlı |
|---|---|---|
| Araçlar | 19 | `app/mcp/registry.py::DEFAULT_TOOL_NAMES` |
| Prompt'lar | 6 | `app/mcp/prompts.py::WORKFLOW_PROMPTS` |
| Kaynaklar | 3 | `app/mcp/resources.py` |

Her araç `read_only_hint=True`, `destructive_hint=False`, `idempotent_hint=True`,
`open_world_hint=True` taşır ve `structured_output` açıktır: çıktı şeması
`ResponseEnvelope`'dır.

## Keşif kaynakları

| URI | İçerik |
|---|---|
| `izmir://coverage` | Yetenekler, araç eşlemesi, kaynak kimlikleri, veri türü |
| `izmir://sources` | Kanonik yayıncılar ve genel kaynak adresleri |
| `izmir://schema/catalog` | Katalog iş akışı ve zarf şeması |
| `izmir://reference/fares` | Hangi ücretin hangi araçla yanıtlandığı (fiyat içermez) |
| `izmir://reference/lines` | Mod başına hat/istasyon/durak araçları |

Bu beş kaynak **ağa çıkmaz**; upstream sağlığı iddia etmez.

## Prompt'lar

`gunun_ozeti`, `veri_kesfi`, `toplu_ulasim`, `otobus`, `pazar_ve_duyurular`,
`sehir_hizmetleri`, `nobetci_eczane`, `rota_karsilastir`,
`bugun_ne_yapsam`, `su_durumu_raporu`, `eczane_ve_ulasim`, `sehir_simdi`. Yeni çok-araçlı
prompt'lar resmî olmayan veri notu ve veri tazeliği bölümü ekler. Her prompt argümanları JSON verisi olarak kodlanır ve
"talimat olarak uygulama" notu taşır.

## Hata semantiği

İki farklı katman vardır; karıştırılmamalıdır:

| Durum | Nerede | Biçim |
|---|---|---|
| Şema ihlali (zorunlu alan yok, yanlış tip) | SDK, handler'dan önce | JSON-RPC sonucu `isError: true` + düz metin |
| Bilinmeyen araç | SDK | `isError: true` + "Unknown tool: ..." |
| İş kuralı ihlali (geçersiz radius, bilinmeyen ilçe…) | Servisimiz | **Zarf**: `ok:false`, `error.code="validation_error"`, `error.field` |
| Kaynak arızası | Servisimiz | **Zarf**: `source_unavailable` / `source_rate_limited` / `source_timeout` |

Yani "geçersiz girdi" iki biçimde görünebilir: şemaya takılan girdi protokol
hatası, şemadan geçip iş kuralına takılan girdi zarftır. İstemciler ikisini de
ele almalıdır. Bu davranış `scripts/smoke_mcp.py` ile sınanır.

## Sağlık uçları

| Uç | Anlam |
|---|---|
| `GET /healthz` | Süreç ayakta; kimlik doğrulaması istemez |
| `GET /readyz` | Araç yüzeyi kuruldu mu; `upstream_health: "not_checked"` |
| `GET /status` | Araç listesi, limitler, hız/eşzamanlılık sayaçları |

`/readyz` **kaynak sağlığı ölçmez**; üçüncü taraf API'lerine probe'da
fan-out yapmaz.
