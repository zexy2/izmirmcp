# Sources

This document derives İzmir MCP's external sources, how they are used and their
proven limits from `app/services/sources.py`, `app/core/settings.py` and the
verifications under `docs/development/reports/`. Source health is not the
subject of this document but of the `freshness`/`warnings` fields in tool
responses. Live/down status per endpoint is recorded in
[source-reachability-analysis.md](source-reachability-analysis.md).

No source is invented. Unreachable endpoints return `source_unavailable`; no
data is produced.

## Canonical source names (`Source.name`)

The envelope's `sources[].name` values are constants in
`app/services/sources.py`. They are published Turkish names and are kept
verbatim; attribution uses these names:

| `Source.name` | Publisher | `scope` |
|---|---|---|
| İZELMAN / İZUM otopark doluluk servisi | İzmir Büyükşehir Belediyesi | `parking_occupancy` |
| İzmir nöbetçi eczane listesi | İzmir Büyükşehir Belediyesi | `on_duty_roster` |
| İzmir Metro istasyonları | İzmir Metro A.Ş. | `stations` |
| İZBAN istasyonları | İZBAN A.Ş. | `stations` |
| İZDENİZ iskeleleri | İZDENİZ A.Ş. | `piers` |
| İZSU baraj doluluk oranları | İzmir Su ve Kanalizasyon İdaresi (İZSU) | `dam_levels` |
| İzmir hava kalitesi ölçüm değerleri | İzmir Büyükşehir Belediyesi | `station_readings` |
| İzmir Metro sefer sıklığı | İzmir Metro A.Ş. | `published_timetable` |
| İZBAN sefer saatleri | İZBAN A.Ş. | `published_timetable` |
| İZDENİZ vapur sefer saatleri | İZDENİZ A.Ş. | `published_timetable` |
| İzmir Tramvay hatları, istasyonları ve sefer sıklığı | İzmir Metro A.Ş. | `published_timetable` |
| EShot otobüs durakları | İzmir Büyükşehir Belediyesi / EShot | `stops` |
| EShot durağa yaklaşan otobüsler | İzmir İnovasyon ve Teknoloji A.Ş. (İZTEK) | `live_vehicle_positions` |
| EShot hat otobüs konumları | İzmir İnovasyon ve Teknoloji A.Ş. (İZTEK) | `live_vehicle_positions` |
| İzmir Büyükşehir CBS önemli yer katmanları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmir Büyükşehir kültür sanat etkinlikleri | İzmir Büyükşehir Belediyesi | `published_events` |
| İzmir hal fiyatları (sebze-meyve ve balık) | İzmir Büyükşehir Belediyesi | `wholesale_price_bulletin` |
| İzmir eczane listesi | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| EShot GTFS toplu ulaşım verisi | İzmir Büyükşehir Belediyesi / EShot | `published_timetable` |
| İzmir semt pazar yerleri | İzmir Büyükşehir Belediyesi | `static_market_locations` |
| WizmirNET ücretsiz kablosuz internet noktaları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmirim Kart dolum noktaları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmir Büyükşehir Belediyesi kütüphaneleri | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| EShot hat duyuruları | İzmir Büyükşehir Belediyesi / EShot | `published_line_notices` |
| İzmir Metro duyuruları | İzmir Metro A.Ş. / İZTEK | `published_operator_notices` |
| İZDENİZ duyuruları | İZDENİZ A.Ş. | `published_operator_notices` |
| İZBAN duyuruları (erişilemiyor) | İZBAN A.Ş. | `published_operator_notices` |
| İzmir mahalle nüfusu (cinsiyete göre) | İzmir Büyükşehir Belediyesi | `published_neighborhood_demographics` |
| İzmir mahalle bazlı bina sayıları | İzmir Büyükşehir Belediyesi | `published_building_stock` |
| İzmir taksi durakları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İzmir ana arter hız ve süre verileri | İzmir Büyükşehir Belediyesi | `historical_segment_speed` |
| İzmir engelli şarj istasyonları | İzmir Büyükşehir Belediyesi | `static_service_locations` |
| İZBAN ücret hesaplama servisi | İZBAN A.Ş. | `published_fare_table` |
| İZELMAN otopark ücretleri | İZELMAN A.Ş. | `published_parking_tariff` |
| İzmir trafik kameraları konumları | İzmir Büyükşehir Belediyesi Ulaşım Dairesi Başkanlığı | `static_camera_locations` |
| İZSU günlük su üretimi | İzmir Su ve Kanalizasyon İdaresi (İZSU) | `published_water_production_snapshot` |

## Catalog and DataStore

| Source | Endpoint / dataset | Use | Status |
|---|---|---|---|
| İzmir Open Data Portal (CKAN) | `https://acikveri.bizizmir.com/api/3/action` | `package_search`, `package_show`, `datastore_search` | Working (2026-10-28) |

Only `datastore_search` is called on the portal; free SQL
(`datastore_search_sql`) is deliberately absent (see
[datastore-sql.md](datastore-sql.md) for the local alternative). The catalog is
cached with a TTL of 21600 s, resources with 300 s.

## İzmir Metropolitan Municipality open API

| Source | Endpoint | Use |
|---|---|---|
| İZELMAN / İZUM otopark doluluk servisi | `openapi.izmir.bel.tr/api/ibb/izum/otoparklar` | Live free-space snapshot |
| İzmir nöbetçi eczane listesi | `openapi.izmir.bel.tr/api/ibb/nobetcieczaneler` | Daily on-duty roster |
| İzmir hava kalitesi ölçüm değerleri | `openapi.izmir.bel.tr/api/ibb/cevre/havadegerleri/{date}` | Station + pollutant values |
| İzmir Metro istasyonları | `openapi.izmir.bel.tr/api/metro/istasyonlar` | Stations + coordinates |
| İzmir Metro sefer sıklığı | `openapi.izmir.bel.tr/api/metro/sefersaatleri` | Hour-range table |
| İZBAN istasyonları | `openapi.izmir.bel.tr/api/izban/istasyonlar` | Stations + coordinates |
| İZBAN sefer saatleri | `openapi.izmir.bel.tr/api/izban/sefersaatleri/{from}/{to}` | Published timetable |
| İZBAN ücret hesaplama | `openapi.izmir.bel.tr/api/izban/tutarhesaplama/{from}/{to}/{0\|1}/{true\|false}` | Working; HTTP 400 when the 4th parameter is `0`/`1` |
| İZDENİZ iskeleleri | `openapi.izmir.bel.tr/api/izdeniz/iskeleler` | Piers + coordinates |
| İZDENİZ seferleri | openapi İZDENİZ departure/line endpoints | Published timetable |

OpenAPI TTL is 120 s, with 900 s of stale use on errors. Air quality publishes
no coordinates or units (`unit=null`); no AQI is computed.

## Water

| Source | Endpoint | Status |
|---|---|---|
| İZSU baraj doluluk oranları | `openfiles.izmir.bel.tr/309436/docs/izsu-baraj-doluluk-oranlari.csv` | Working; TTL 3600 s, 86400 s stale |
| İZSU dam JSON | `openapi.izmir.bel.tr/api/izsu/barajdurum` | **HTTP 500** — not used |
| İZSU fault/outage feed (`arıza`) | `openapi.izmir.bel.tr/api/izsu/arizakaynaklisukesintileri` | **HTTP 500** — `kind=faults` returns an explicit `source_unavailable` |

When the dam CSV is read, rows without a fill percentage are dropped; fill is
sorted descending and a "may be delayed" warning is added. No fault (`arıza`)
data is produced until the endpoint is fixed (evidence:
`docs/development/reports/izmir-sehir-katmanlari.md`).

## ESHOT / İZTEK transport

| Source | Endpoint / dataset | Use |
|---|---|---|
| ESHOT bus stops | CKAN `eshot-otobus-duraklari` (`0c791266-…`) | 11,965 stops, DataStore |
| ESHOT buses approaching a stop | `openapi.izmir.bel.tr/api/iztek/duragayaklasanotobusler/{stopId}` | Live position + remaining stops (**no ETA**) |
| ESHOT GTFS | `www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip` | Lines/trips + `stop_times.txt` → local SQLite |
| ESHOT line notices | `openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv` | 124 planned notices |

- Stop list TTL 86400 s / 604800 s stale; İZTEK TTL 20 s with a `0.5` s gap
  between consecutive requests (because the source returns 429).
- The ESHOT GTFS ZIP answers an explicit `Accept: application/zip` header with
  `406`; it is downloaded with `*/*` (2026-10-28). `stop_times.txt` is ~2.1M
  rows / ~85 MB; the store is ~141 MB. See [gtfs-schedule.md](gtfs-schedule.md).
- **The GTFS service calendar ended on 2026-10-09** (verified 2026-10-28). Every
  response carries `calendar_end` + a staleness warning; no departures are
  produced for dates outside the calendar.
- The arrivals endpoint also returns `200` + an empty array for an invalid
  stop; an empty response does not count as proof of "no service".

## City layers (CKAN)

| Source | Dataset | Use |
|---|---|---|
| İzmir semt pazar yerleri | `semt-pazar-yerleri` (`3e63e16e-…`) | 186 markets; day from free text |
| WizmirNET WiFi points | `kablosuz-internet-baglanti-noktalari` (`60ca8451-…`) | 857 points (duplicate rows deduplicated) |
| İzmirim Kart dolum noktaları | `izmirim-kart-dolum-noktalari` (`7a3efbec-…`) | 1,120 points; **dated 2023-08-21** |
| İBB libraries | `izmir-buyuksehir-belediyesi-kutuphaneleri-bilgileri` (`0c1b15b9-…`) | 10 libraries; **no coordinates** |
| İZELMAN otopark ücretleri | `otopark-ucretleri` (`8dca3fb5-…`) | 39 tariff rows; source last updated 2024-09-02 |
| İzmir traffic cameras | `trafik-kameralari` (`b91cb15d-…`) | 92 locations; **no stream/image link** |
| İZSU günlük su üretimi | `gunluk-su-uretimi` (`0eca9087-…`) | 10 dam/well rows; **no date or unit column** |

These layers have a TTL of 86400 s / 604800 s stale. All are static snapshots;
no open/closed status is published. Missing library coordinates exclude
libraries from radius and `bbox` modes.

## Operator announcements

| Source | Endpoint | Status |
|---|---|---|
| İzmir Metro duyuruları | `metrotramapi.iztek.tr/api/v1/announcements` | Working (empty list at verification) |
| İZDENİZ duyuruları | `coreapi.izdeniz.com.tr/api/v1/announcements` | Working (real announcements) |
| İZBAN duyuruları | `izban.com.tr` RSS / `Sayfalar/Single.aspx` | **302 → FileNotFound**; `unavailable` |

There is no reachable machine-readable feed for İZBAN; the İZBAN path on
`metrotramapi` is `404`. `operator="izban"` always returns
`source_unavailable` (evidence:
`docs/development/reports/operator-duyuru-kaynaklari.md`). Only ESHOT publishes
a machine-readable validity window, so `active` is only computed for ESHOT.

## Reference points

| Source | Use | Licence |
|---|---|---|
| OpenStreetMap Nominatim | 30 districts + 24 selected landmarks (`app/data/places.json`) | ODbL 1.0 (© OpenStreetMap contributors) |
| CKAN `muhtarliklar` (`7d0b7f55-…`) | 1,219 neighbourhood reference points (`app/data/neighborhoods.json`) | Izmir Metropolitan Municipality Open Data License |
| CKAN `cinsiyete-gore-mahalle-nufus-bilgileri` (`7ef10678-…`) | 1,297 neighbourhood populations (female/male) | Izmir Metropolitan Municipality Open Data License |
| CKAN `ilcelere-ait-mahalle-bazli-bina-sayilari` (`54af6862-…`) | 1,295 neighbourhood building counts | Izmir Metropolitan Municipality Open Data License |

Retrieved 2026-10-28. These are approximate area centres, **not address
geocoding**; tools report this as a warning in `place` mode. See
[place-resolution.md](place-resolution.md).

## Unused / rejected sources

- The İZDENİZ GTFS ZIP (`www.izdeniz.com.tr/gtfs/...`) returns `text/html`;
  there is no ferry GTFS coverage, the openapi trip endpoints are used instead.
- The İZBAN GTFS is a 2023 feed whose calendar ended on 2025-01-01; it is not
  current.
- The metro/tram GTFS archives were downloaded and verified but not wired.
- `openapi.izmir.bel.tr/api/ibb/trafikyogunluk` → `404`; there is no city-wide
  live traffic index. Only a historical XLSX and a 2023 camera list exist.
- `metro/ekipmanlar`, `metro/arizalar` → `404`; no equipment/accessibility
  data.
- Guessed `/api/eshot/...`, `/api/iztek/hatlar` paths return `404`. The
  `ibb/cbs/noktayayakinduraklar` projection could not be verified.
- No dataset is published under the name "sosyal tesis" (social facilities).

## Licence status

- Licences of the city data belong to the publishing institutions; **public
  access is not a licence grant** (Turkish: "açık erişim lisans
  izni değildir"). That is why `Source.license` is `null` for most sources.
- OpenStreetMap reference points are under ODbL 1.0; attribution is required.
- This repository's own code is MIT-licensed (`LICENSE`); that licence does not
  cover the upstream city data.

## Evidence reports

- [ESHOT/transport source research](development/reports/eshot-ulasim-kaynak-arastirmasi.md)
- [City layers and the İZSU fault feed](development/reports/izmir-sehir-katmanlari.md)
- [Operator announcements](development/reports/operator-duyuru-kaynaklari.md)
- [REA open data portal review](development/reports/rea-open-data-portal.md)
