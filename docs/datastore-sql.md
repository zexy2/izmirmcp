# Yerel SQL Snapshot'ı

İzmir Açık Veri portalındaki CKAN, `datastore_search_sql` eylemini
yayımlamıyor (`"Action name not known"`, 2026-10-28). `izmir_query_resource`
bu yüzden yalnızca filtre, serbest metin ve sıralama sunar. Analitik sorular
(`GROUP BY`, `COUNT`, ortalama) için `izmir_datastore_query` aracı, upstream
istanbulmcp ile aynı yaklaşımı kullanır: izin verilen kaynağın **tamamını**
yerel bir SQLite tablosuna alır ve sorguyu orada çalıştırır.

## Neden sunucu tarafı SQL değil?

CKAN'ın SQL eylemi bu portalda yok. Kaynağın yalnızca birkaç sayfasını çekip
üzerinde toplam almak, sessizce yanlış sonuç üretir. Bu nedenle araç ya tam
kopyayı alır ya da `source_unavailable` döner; **kısmi toplam üretmez**.

## Etkinleştirme

Araç varsayılan olarak hiçbir kaynağı indirmez. Önce kaynak kimliğini
`izmir_search_datasets` / `izmir_get_dataset` ile bulun, şemayı
`izmir_get_resource_schema` ile doğrulayın, sonra kimliği izin listesine ekleyin:

```bash
export IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS="0c791266-a2e4-4f14-82b8-9a9b102fbf94"
```

Virgülle en fazla 100 kaynak verilebilir. Liste boşsa araç, ağa çıkmadan
`validation_error` (`field=resource_id`) döner.

## Sorgu sözleşmesi

- Tablo adı yalnızca `records`; kolonlar `izmir_get_resource_schema` çıktısındaki
  yayımlanmış adlardır.
- Tek bir `SELECT`; JOIN, alt sorgu, CTE, UNION, pencere fonksiyonu ve yazma
  reddedilir.
- İzinli fonksiyonlar: `count`, `sum`, `avg`, `min`, `max`, `round`, `abs`,
  `coalesce`, `lower`, `upper`, `length`, `substr`, `trim`, tarih fonksiyonları.
- Sonuç en fazla `limit` (varsayılan 10, üst sınır 50) satırdır; dış limit
  sorgunun kendi `LIMIT`'inden bağımsız uygulanır.
- Sorgu 0,5 sn ve 2.000.000 VM adımıyla sınırlıdır; sonuç 256 KiB'ı aşamaz.

Örnek:

```sql
SELECT COUNT(*) AS n FROM records
```

Kolon adları önce doğrulanmalıdır; örnek bir analitik sorgu:

```sql
SELECT ILCE, COUNT(*) AS n
FROM records
GROUP BY ILCE
ORDER BY n DESC
```

`ILCE` yalnızca kaynak şemasında varsa geçerlidir; araç kolon adı uydurmaz.

## Kopya bütçesi

| Ayar | Varsayılan | Kod sınırı |
|---|---|---|
| `IZMIR_MCP_CKAN_SQL_MAX_ROWS` | 50.000 | 1–50.000 |
| `IZMIR_MCP_CKAN_SQL_MAX_BYTES` | 20 MiB | 1 KiB–20 MiB |
| `IZMIR_MCP_CKAN_SQL_PAGE_SIZE` | 5.000 | 1–5.000 |
| `IZMIR_MCP_CKAN_SQL_SNAPSHOT_TTL_SECONDS` | 900 | 1–3.600 |
| `IZMIR_MCP_CKAN_SQL_LOAD_TIMEOUT_SECONDS` | 30 | 0,01–60 |
| `IZMIR_MCP_CKAN_SQL_QUERY_TIMEOUT_SECONDS` | 0,5 | 0,001–2 |

Sayfalar `_id asc` ile istenir ve her sayfada toplam ile şema yeniden
doğrulanır. `_id` tekrar ederse, toplam değişirse, byte/satır bütçesi aşarsa
veya kaynak yarım sayfa dönerse kopya reddedilir.

## Zarf ve dürüstlük

Başarılı yanıt `freshness` olarak kopyanın alınma zamanını taşır; bu, satırların
yaşı değildir. `limits` içinde `snapshot_rows`, `snapshot_wire_bytes`,
`no_partial_aggregates` ve motor sınırları bulunur. Sonuç limiti kesilirse
`result_info.truncated=true` ve uyarı eklenir. Kaynak hatası
`source_unavailable` / `source_timeout` / `source_rate_limited` olarak döner;
exception sızmaz.

## Testler

- `tests/test_guarded_sql.py` — parser ve SQLite authorizer'ın JOIN, alt sorgu,
  CTE, UNION, `sqlite_master`, `ATTACH`, `load_extension` ve yazma girişimlerini
  reddettiğini; toplamların ve dış limitin çalıştığını doğrular.
- `tests/test_datastore_sql.py` — izin listesi, tam kopya, değişen toplam,
  tekrarlanan `_id`, bütçe aşımı, önbellek ve tipli kaynak hatasını doğrular.
- `tests/test_contract_conformance.py` — geçersiz SQL'in ağa çıkmadan
  `validation_error` döndüğünü kilitler.
