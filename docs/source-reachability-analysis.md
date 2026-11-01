# Source reachability analysis

This document collects in one place which endpoints actually work, which are
**down**, and how that is represented in code. All measurements were made with
direct HTTP; the down endpoints were retried on **2026-10-29** with the same
results (first measurement 2026-10-28).

This is not a to-do list but an **evidence record**: no data is produced for a
down source, and the tool explicitly returns `source_unavailable`. For the
publisher, licence and coverage of each source, see [sources.md](sources.md).

## Working sources

| Endpoint / file | Result | Tool using it |
|---|---|---|
| `acikveri.bizizmir.com/api/3/action/*` (CKAN) | 200 | catalog (4), all layers |
| `openapi.izmir.bel.tr/api/ibb/izum/otoparklar` | 200 | `izmir_nearby` |
| `openapi.izmir.bel.tr/api/ibb/nobetcieczaneler` | 200 | `izmir_nearby` |
| `openapi.izmir.bel.tr/api/ibb/cevre/havadegerleri/{date}` | 200 | `izmir_air_quality` |
| `openapi.izmir.bel.tr/api/metro/istasyonlar` + `/metro/sefersaatleri` | 200 | `izmir_transit_*` |
| `openapi.izmir.bel.tr/api/izban/istasyonlar` + `/izban/sefersaatleri/{a}/{b}` | 200 | `izmir_transit_*` |
| `openapi.izmir.bel.tr/api/izdeniz/iskeleler` + trip endpoints | 200 | `izmir_transit_*` |
| `openapi.izmir.bel.tr/api/iztek/duragayaklasanotobusler/{stop}` | 200 | `izmir_bus_arrivals` |
| `openapi.izmir.bel.tr/api/iztek/hatotobuskonumlari/{line}` | 200 | (verified, not wired at the time of measurement) |
| `metrotramapi.iztek.tr/api/v1/announcements` | 200 (empty list) | `izmir_transport_disruptions` |
| `metrotramapi.iztek.tr/api/v1/lines`, `/day-types` | 200 | (verified, not wired at the time of measurement) |
| `coreapi.izdeniz.com.tr/api/v1/announcements` | 200 | `izmir_transport_disruptions` |
| `openfiles.izmir.bel.tr/.../izsu-baraj-doluluk-oranlari.csv` | 200 | `izmir_water_status` |
| `openfiles.izmir.bel.tr/211488/docs/eshot-otobus-duraklari.csv` | 200 | (DataStore preferred) |
| `openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hat-duyurulari.csv` | 200 | `izmir_transport_disruptions` |
| `www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip` | 200, valid ZIP, 18.4 MB; **re-downloaded on 2026-10-29**, `calendar.txt` still 2026-08-05 → 2026-10-09 | `izmir_bus_departures`, `izmir_bus_routes`, `izmir_gtfs_status` |
| `www.izmirmetro.com.tr/gtfs/rail-metro-gtfs.zip` | 200, valid ZIP | (verified, not wired) |
| `www.tramizmir.com/gtfs/rail-tramizmir-gtfs.zip` | 200, valid ZIP | (verified, not wired) |
| `www.izban.com.tr/gtfs/rail-izban-gtfs.zip` | 200, valid ZIP | (not wired: calendar ended on 2025-01-01) |

## Down sources (with evidence)

| Endpoint | Result | How it is represented in code |
|---|---|---|
| `openapi.izmir.bel.tr/api/izsu/arizakaynaklisukesintileri` | **500** | `izmir_water_status(kind="faults")` → `source_unavailable` |
| `openapi.izmir.bel.tr/api/izsu/barajdurum` | **500** | not used; CSV preferred |
| `openapi.izmir.bel.tr/api/ibb/trafikyogunluk`, `/ibb/trafik` | **404** | no tool (no traffic index is published) |
| `openapi.izmir.bel.tr/api/metro/ekipmanlar` | **404** | no tool |
| `openapi.izmir.bel.tr/api/metro/arizalar` | **404** | no tool |
| `openapi.izmir.bel.tr/api/ibb/cbs/adres*` | **404** | no free-text address geocoding |
| `www.izdeniz.com.tr/gtfs/ship-izdeniz-gtfs.zip` | 200 but **`text/html`** | no İZDENİZ GTFS |
| `www.izban.com.tr/Rss.aspx?MenuId=45` | **302** → `FileNotFound.htm` | `operator="izban"` → `source_unavailable` |
| `www.izban.com.tr/Sayfalar/Single.aspx?MenuId=*` | **302** → `FileNotFound.htm` | same |
| `metrotramapi.iztek.tr/api/v1/izbanannouncements` | **404** | same |
| `acikveri.bizizmir.com/api/3/action/datastore_search_sql` | **"Action name not known"** | server-side SQL not exposed; see [datastore-sql.md](datastore-sql.md) |
| Undocumented `/api/eshot/...`, `/api/iztek/hatlar`, `/api/duraklar` | **404** | never wired (guessed paths) |

## Pitfalls (real behaviour met while wiring)

| Behaviour | Effect | Fix |
|---|---|---|
| `www.eshot.gov.tr` answers an explicit `Accept: application/zip` with **406** | GTFS cannot be downloaded | `Accept: */*` |
| İZTEK returns **429** on consecutive requests | arrival queries fail | soft rate limit + 20 s cache |
| An invalid stop id returns **200 + empty array** | could be read as "no service" | empty responses come with a warning |
| ESHOT GTFS calendar **ended on 2026-10-09** | no departures for today | `calendar_end` + staleness warning |
| Coordinates use the Turkish decimal comma (`"38,45"`) | parse errors | only decimal format is accepted after conversion |
| Names are UPPERCASE with typos (`"Kurulmnaktadır"`) | day parsing | explicit day-name matching, otherwise `unknown` |
| WizmirNET publishes the same location in several rows | duplicate results | deduplication by location/address |
| The library layer has **no coordinates** | radius cannot be applied | district/address listing, `distance_m` null |
| İzmirim Kart data is from **2023-08-21** | stale | static/stale warning |

## Re-verification (2026-10-29)

The down endpoints were retried; none of them came back:

| Endpoint | 2026-10-29 result |
|---|---|
| `/api/izsu/arizakaynaklisukesintileri` | **500** (JSON) |
| `/api/izsu/barajdurum` | **500** (JSON) |
| `/api/ibb/trafikyogunluk`, `/api/ibb/trafik` | **404** |
| `/api/metro/ekipmanlar`, `/api/metro/arizalar` | **404** |
| `/api/ibb/cbs/adres` | **404** |
| `swagger/v1/swagger.json` (both roots) | **404** — no machine-readable endpoint list is published |
| `izdeniz.com.tr/gtfs/ship-izdeniz-gtfs.zip` | 200, `text/html` |
| `izban.com.tr/Rss.aspx?MenuId=45` | **302** |
| `metrotramapi.iztek.tr/api/v1/izbanannouncements` | **404** |

Second finding: the live ESHOT archive still publishes the same calendar
ending on **2026-10-09**. So the staleness warning is not a build error but the
state of the source; re-downloading does not fix anything.

```bash
.venv/bin/python scripts/smoke_live.py     # all live sources, exit 0 expected
```

The script runs 35 checks; `disruptions_izban_unavailable` deliberately
expects `source_unavailable` and counts as a **pass**.
