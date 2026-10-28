# Kırmızı takım denetimi — 2026-10-28 (2. tur)

Yöntem: kaynak tükenmesi, amplifikasyon, kaynak zehirleme, TOCTOU ve protokol
kötüye kullanımı üzerine 15 yeni saldırı. Bulgular
`tests/test_redteam_probes.py` (10 test) ile kalıcı kilitlendi.

Önceki turdan farkı: ilk tur **girdi doğrulama** açıklarını (SSRF, injection,
DoS) arıyordu; bu tur **kaynak ekonomisi** ve **kaynak zehirlemesini** hedefledi.

## Bulgular ve düzeltmeler

### BULGU A — ZIP merkezi dizin amplifikasyonu — YÜKSEK

**Saldırı:** 18,5 MB'lık, gerekli dosyayı da içeren 200.001 girdili ZIP.

**Önce:** `zipfile.infolist()` tüm merkezi dizini ayrıştırıyordu →
**131 MB bellek, 4,59 sn CPU**, sonra kabul. Zip byte bütçesi (64 MB) altında
kaldığı için hiçbir koruma devreye girmiyordu. 1 MB girdi → 7 MB bellek.

**Düzeltme:** `_declared_entry_count` — girdi sayısı **EOCD kaydından**
(`PK\x05\x06`, offset +10) okunuyor; zip hiç açılmadan reddediliyor.
`MAX_ZIP_ENTRIES = 200` (gerçek feed 7 dosya).

**Sonra:** **0,000 sn, 18 MB** (yalnız zip'in kendisi).

### BULGU B — CSV satır patlaması — ORTA

**Saldırı:** 7,6 MB'lık, 1.000.000 satırlı CSV.

**Önce:** **214 MB bellek, 2,8 sn**, 1 milyon dict döndü. `response_max_bytes`
(2 MB) metni sınırlıyor ama satır sayısı sınırsızdı.

**Düzeltme:** `MAX_CSV_ROWS = 50_000`; aşımda sessiz kesme değil,
`SourceError` (eksik liste "tam" görünmesin).

**Sonra:** **0,17 sn, 40 MB**, hata.

### BULGU C — Kaynak zehirlemesi 500'e düşürüyor — ORTA

**Saldırı:** Kaynak `[null, 1, "str", [1,2,3]]` döndürürse.

**Önce:** `AttributeError: 'NoneType' object has no attribute 'get'` — yakalanmıyor,
sunucu 500.

**Düzeltme:** `izmir_api._records()` — yalnız dict satırlar döner; 8 çağrı
noktası bu filtreden geçiyor.

### BULGU D — Alansal zarf şişmesi — ORTA

**Saldırı:** Kaynak tek kayıtta 1 MB `id` + 1 MB `name`.

**Önce:** tek kayıt **1,9 MB zarf**; `limit=50` ile **~95 MB yanıt**.

**Düzeltme:** `envelope.bounded_text` (512) / `bounded_id` (128). Sayısal id
tipi korunuyor (test yakaladı: `1` → `"1"` regresyonu).

**Sonra:** zarf **0,8 KB**.

## Savuşturulan saldırılar

| Saldırı | Sonuç |
|---|---|
| ZIP bomb (200 MB → 199 KB) | üye byte bütçesi |
| Mükerrer id ile indeks bozma | `GeoStoreError`, indeks korunur |
| Boş liste ile indeksi silme | reddedildi, mevcut veri korunur |
| `kinds` üzerinden SQL enjeksiyonu (3 varyant) | parametreli sorgu, 0 satır |
| 200 eşzamanlı istek | 32×200 / 28×503 / 140×429 |
| SQLite `BEGIN EXCLUSIVE` kilidi | `GeoStoreError`, asılı kalmıyor |
| Symlink ile depo yolu kaçışı | `GeoStoreError`, hedef dosya bozulmadı |
| ReDoS / patolojik unicode (10k–12M karakter) | doğrusal, <0,2 sn |
| Kota tablosu şişirme (2000 subject) | 252 KB, `prune` mevcut |

## Doğrulama

- `pytest`: **528 passed** (10 yeni kırmızı takım testi)
- Canlı smoke: 30/30, exit 0 (gerçek GTFS 7 dosya hâlâ geçer)
- Protokol smoke: 32/32
- Resmî conformance: 5/5

## Kalan riskler

| Risk | Not |
|---|---|
| ZIP içi tek üye şişmesi | byte bütçesi var; oran (ratio) kontrolü yok |
| CSV alan uzunluğu | satır sınırı var; alan başına sınır `bounded_text` ile |
| `bounded_text` kırpma | kırpılan değer "tam" gibi görünür; kaynak zaten 512 karakteri aşmıyor |
