# GTFS tarife deposu

`izmir_bus_departures`, `izmir_bus_routes(detail=true)` ve `izmir_gtfs_status`
araçlarının arkasındaki yerel tarife deposunu açıklar.
Kod: `app/storage/gtfs_schedule.py`, servis: `app/services/bus.py`.

## Neden yerel depo

Yayımlanan ESHOT arşivi 18 MB'lık ZIP, içinde `stop_times.txt` ~85 MB ve
2.108.736 satır. Her sorguda bu dosyayı indirip ayrıştırmak hem yavaş hem de
kaynağa saygısız olurdu. Bir kez indirilip SQLite'a alınır, sonra indeksten
okunur. Ölçülen kurulum: **~3,7 sn**, ~141 MB veritabanı.

## Dosya düzeni

- Varsayılan yol: `.data/izmir_mcp.sqlite3`
- `IZMIR_MCP_DATABASE_PATH` ile değiştirilir.
- `.gitignore` ve `.dockerignore` kapsamındadır: **asla** depoya veya imaja girmez.
- Konteynerde `/data` hacmine yazılır ve açılışta `docker/entrypoint.sh` kurar.

## Kurulum ve tazelik

1. İlk kalkış sorgusu depoyu yoksa kurar.
2. Depo yaşı `IZMIR_MCP_ESHOT_GTFS_CACHE_TTL_SECONDS` (varsayılan 86400) sınırını
   aşarsa yeniden kurmayı dener.
3. Yeniden kurulum başarısız olursa `IZMIR_MCP_ESHOT_GTFS_STALE_IF_ERROR_SECONDS`
   (varsayılan 604800) içindeyse eski kopya `freshness.status="stale"` ile
   kullanılır; dışındaysa `source_unavailable`.
4. Kurulum hiçbir zaman yarım dosya bırakmaz: geçici dosyaya yazılıp atomik
   olarak taşınır.

Bütçeler: `IZMIR_MCP_ESHOT_GTFS_MAX_BYTES` (ZIP), `..._MEMBER_MAX_BYTES`
(tek üye), `..._STOP_TIMES_MAX_BYTES`, `..._MAX_ROWS`. Aşım = kurulum reddi,
kısmi veri değil.

## Takvim gerçeği

Arşivdeki `calendar.txt` penceresi **2026-08-05 → 2026-10-09**. Doğrulama
tarihi 2026-10-28, yani takvim **süresi geçmiş**.

Sonuçlar:

- `calendar_end` her yanıtta döner.
- Pencere dışı bir tarih sorulursa `ok: true`, boş `data`, `freshness: stale` ve
  açık uyarı döner — "sefer yok" denmez.
- `izmir_gtfs_status` bu durumu `calendar_expired: true` ile raporlar.

Bu bir hata değil, kaynağın durumu. Feed güncellenince depo otomatik yenilenir
ve uyarı kendiliğinden kaybolur.

## Ne yüklenir, ne yüklenmez

| Dosya | Yüklenir | Neden |
|---|---|---|
| `stops.txt`, `routes.txt`, `trips.txt`, `calendar.txt` | ✅ | Durak, hat, sefer ve servis günü |
| `calendar_dates.txt` | ✅ (varsa) | İstisna günleri; arşivde şu an yok ama desteklenir |
| `stop_times.txt` | ✅ | Kalkış saatlerinin tek kaynağı |
| `shapes.txt` | ❌ | 12 MB güzergâh geometrisi; araçlar için gereksiz |

`pickup_type=1` (binilemeyen) satırlar elenir. Kaynakta `trip_headsign` yoktur;
yön adı **uydurulmaz**, yalnızca `direction_id` verilir.

## 24:00 sonrası saatler

GTFS'te `25:10:00` "ertesi gün 01:10" demektir. Saatler servis gününe göre
mutlak zamana çevrilir ve bir önceki servis günü de taranır; böylece gece
yarısını aşan seferler doğru güne düşer.

## Komut satırı

```bash
python -m app.storage.gtfs_schedule                  # varsayılan yola kur
python -m app.storage.gtfs_schedule --database /data/x.sqlite3
python -m app.storage.gtfs_schedule --url <alternatif arşiv>
```

Geçersiz arşivde **hiçbir şey yazılmaz**.

## Canlı veri değildir

Bu depo yayımlanmış tarifedir. Canlı konum için `izmir_bus_arrivals`
(ETA içermez, yalnızca kalan durak + araç konumu), canlı kalkış için bir kaynak
**yoktur**.
