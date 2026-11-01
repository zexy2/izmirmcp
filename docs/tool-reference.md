# Tool Reference

This document derives the input/output contract of the 36 read-only MCP tools
from the actual code (`app/mcp/server.py` and `app/services/*`). Envelope
fields are in [response-contract.md](response-contract.md); transports,
discovery resources and error layers are in [mcp-interface.md](mcp-interface.md).
All tools are marked `read_only`, `idempotent` and `open_world`, and carry
`structured_output`.

Shared defaults: `default_limit=10`, `max_limit=50`, `max_radius_m=5000`.
When no limit is given, `default_limit` applies; exceeding the maximum returns
`validation_error` (`limit`).

Client workflows (prompts), described in [mcp-interface.md](mcp-interface.md#prompts):
`gunun_ozeti`, `veri_kesfi`, `toplu_ulasim`, `otobus`, `pazar_ve_duyurular`,
`sehir_hizmetleri`, `nobetci_eczane`, `rota_karsilastir`,
`bugun_ne_yapsam`, `su_durumu_raporu`, `eczane_ve_ulasim`, `sehir_simdi`.

## Catalog (CKAN)

### `izmir_search_datasets`
Topic search in the İzmir Open Data catalog.

| Input | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Topic to search for. |
| `formats` | string[] \| null | no | Up to 10 format filters (e.g. `CSV`). |
| `limit` | int \| null | no | Number of datasets returned. |

Output: a summary plus `relevance` (matched terms, `has_datastore`) for each
dataset. `matched` is the source's total count. Catalog metadata is not proof
that a resource is queryable.

### `izmir_get_dataset`
Metadata and resource list of one dataset.

| Input | Type | Required |
|---|---|---|
| `dataset_id` | string | yes |

Unknown id → `not_found` (`field=dataset_id`).

### `izmir_get_resource_schema`
Column schema of a DataStore resource.

| Input | Type | Required |
|---|---|---|
| `resource_id` | string | yes |

Unknown id → `not_found` (`field=resource_id`). Call this before
`izmir_query_resource`.

### `izmir_query_resource`
Fetches DataStore records with safe filters, free-text search and sorting.
Server-side SQL (`datastore_search_sql`) is **not available** on this portal
(`"Action name not known"`, 2026-10-28) and is not accepted. For analytical
queries, the separate `izmir_datastore_query` tool copies an allowed resource
in full to a local store and runs a restricted SELECT there.

| Input | Type | Required | Description |
|---|---|---|---|
| `resource_id` | string | yes | A DataStore-active resource. |
| `filters` | object \| null | no | Exact match; at most 10 keys, scalar/list values. |
| `search` | string \| null | no | Server-side free text (`q`); at most 200 characters, not SQL. |
| `sort` | string \| null | no | `COLUMN` or `COLUMN asc\|desc`; the column must be in the schema. |
| `limit` | int \| null | no | Number of records. |

- A filter key that is not in the schema → `validation_error` (`field=filters`).
- A sort value that does not match `COLUMN [asc|desc]` → `validation_error`
  (`field=sort`); a valid pattern whose column is not in the schema is also
  `validation_error` (`field=sort`). Both are rejected without a network call.
- Whitespace in `search` is normalised; values over 200 characters or with
  control characters are rejected (`field=search`).
- `matched` is the source's `total`.

### `izmir_datastore_query`
Runs a single SELECT over a **complete**, bounded local copy of an allowed
DataStore resource. No aggregate is produced unless the resource was copied in
full.

| Input | Type | Required | Description |
|---|---|---|---|
| `resource_id` | string | yes | A resource in `IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS`. |
| `sql` | string | yes | One SELECT over the `records` table; at most 4096 characters. |
| `limit` | int \| null | no | Result rows; the smaller of `max_limit` and 100. |

- The only table name is `records`; JOIN, subqueries, CTE, UNION, window
  functions, writes and non-allowlisted functions are rejected
  (`validation_error`, `field=sql`).
- A resource outside the allowlist is rejected without a network call
  (`field=resource_id`).
- If the resource exceeds the row/byte budget, the page total changes, or the
  `_id` order breaks, the tool returns `source_unavailable`; **no partial
  aggregate is produced**.
- The engine is a separate in-memory SQLite; it cannot reach the application
  database.
- `freshness` is the time the copy was taken, not the age of the rows.
- If the result limit truncates rows, `result_info.truncated=true` and a
  warning are added.

See [datastore-sql.md](datastore-sql.md) for the full SQL policy.

## Proximity and services

### `izmir_nearby`
Car parks, on-duty pharmacies, metro/İZBAN stations, ferry piers and ESHOT
stops. **One** location mode: `lat`+`lon` or `place`, or `bbox`, or `district`.

| Input | Type | Required | Description |
|---|---|---|---|
| `lat`/`lon` | number \| null | together | Radius mode; cannot be combined with `place`. |
| `place` | string \| null | no | Published district/neighbourhood reference point (e.g. `Konak`, `Abdi İpekçi`). Default radius `max_radius_m`. |
| `place_district` | string \| null | no | District hint to tell apart neighbourhoods with the same name (e.g. `Atatürk` + `Bornova`). Only valid with `place`. |
| `bbox` | number[] \| null | no | `[min_lon, min_lat, max_lon, max_lat]`; edges inclusive. |
| `district` | string \| null | no | District-wide; in practice only pharmacies match. |
| `types` | enum[] \| null | no | `parking`, `pharmacy`, `metro_station`, `izban_station`, `ferry_pier`, `bus_stop`, `taxi_stand`, `charging_station`. Default: all. |
| `radius_m` | int \| null | no | Only with `lat/lon`/`place`; default 1500 (5000 for `place`). |
| `limit` | int \| null | no | |

- Radius mode: `distance_m` is computed and results are sorted by distance;
  truncation is reported through `result_info.matched/truncated`.
- `bbox` mode: `distance_m` is null; sorted by type + name; truncation is in
  `result_info`.
- `district` mode: `distance_m` is null; matching uses the source's area text,
  not administrative boundaries. Types that publish no district label are
  skipped with a warning; if every selected type is skipped →
  `validation_error` (`field=types`).
- An unresolvable `place` → `validation_error` (`field=place`). The reference
  point is approximate; a warning is added.
- Neighbourhood names come from the published 1,219-entry mukhtar office
  inventory. If a name occurs in several districts (`Atatürk` occurs in 17),
  `place_district` is required; otherwise `validation_error` lists the
  candidates. See [place-resolution.md](place-resolution.md).

### `izmir_city_services_nearby`
WizmirNET WiFi, İzmirim Kart top-up points and libraries. Same three location
modes as `izmir_nearby`.

| Input | Type | Required | Description |
|---|---|---|---|
| `kinds` | enum[] \| null | no | `wifi`, `izmirim_card`, `library`. Default: all. |
| `kinds`, `lat`, `lon`, `place`, `place_district`, `bbox`, `district`, `radius_m`, `limit` | — | — | Same location rules as `izmir_nearby`. |

Coverage difference: `bbox` mode searches **only** WiFi and İzmirim Kart; the
library layer publishes no coordinates, so it never falls inside the
rectangle. `district` matching uses the source's district field or address
text. Duplicate records are deduplicated and the count is reported in a
warning. All layers are static snapshots.

### `izmir_mobility_nearby`
Answers nearby transport options in one envelope.

| Input | Type | Required | Description |
|---|---|---|---|
| `lat` | number \| null | location mode | Together with `lon`. |
| `lon` | number \| null | location mode | |
| `place` | string \| null | location mode | Published district/neighbourhood reference point; not address geocoding. |
| `place_district` | string \| null | no | Only with `place`; resolves an ambiguous name by district. |
| `radius_m` | int \| null | no | Default 1000, capped at `max_radius_m`. |
| `limit` | int \| null | no | Number of rows shown; summary counts refer to these rows. |

A thin preset over `izmir_nearby`: same spatial index, same row shape, same
error taxonomy. It only takes transport layers (metro, İZBAN, ferry pier,
ESHOT stop, taxi stand, charging station, car park), sorts by distance and
gives per-type counts in `summary`. Two upstream components are **honestly not
covered** and are reported in `warnings`: air quality stations (the İzmir
source publishes no coordinates) and the live traffic index (`404`). The
`counts_scope=shown` limit states that counts refer to the rows shown after
`limit`; when the result is truncated, `result_info.matched` gives the full
match count and `summary` carries a "showing the first M of N matches" note.
Pharmacy/WiFi/card/library points are not part of this summary.

## Water and air

### `izmir_water_status`
İZSU dam fill levels, or a notice that the fault feed is unavailable.

| Input | Type | Required | Values |
|---|---|---|---|
| `kind` | string | no | `dams` (default) \| `faults` |
| `limit` | int \| null | no | |

`kind="faults"` **always** returns `source_unavailable` (the İZSU endpoint
returns HTTP 500, 2026-10-28). `dams` is read from the published CSV, sorted by
fill percentage descending, and may lag.

### `izmir_air_quality`
Air quality measurements filtered by date/station.

| Input | Type | Required | Description |
|---|---|---|---|
| `date` | string \| null | no | `YYYY-MM-DD`; default today. |
| `station` | string \| null | no | Station name (normalised match). |
| `limit` | int \| null | no | |

The source publishes no coordinates or units (`unit` is null); `observed_at`
may be one day behind the requested date. No AQI is computed.

## Transit timetables

### `izmir_transit_stations`
List of metro stations, İZBAN stations or İZDENİZ piers.

| Input | Type | Required | Values |
|---|---|---|---|
| `mode` | string | yes | `metro` \| `izban` \| `izdeniz` |
| `limit` | int \| null | no | |

### `izmir_transit_schedule`
Published timetable: metro headways, İZBAN/İZDENİZ departures.

| Input | Type | Required | Description |
|---|---|---|---|
| `mode` | string | yes | `metro` \| `izban` \| `izdeniz` |
| `from_id` | int \| null | by mode | Required for İZBAN; İZDENİZ alternative to `pier_id`. |
| `to_id` | int \| null | by mode | Required for İZBAN; İZDENİZ alternative to `pier_id`. |
| `pier_id` | int \| null | by mode | İZDENİZ only; cannot be combined with `from_id`/`to_id`. |
| `day` | int | no | 1–7; **the source's own day id**, not assumed to be the weekday. |

- `metro`: accepts no station pair; returns an hour range + headway table.
- `izban`: `from_id` and `to_id` are required.
- `izdeniz`: `pier_id` or `from_id`+`to_id` is required.

Timetables are not live departures, delays or ETAs.

## ESHOT buses

### `izmir_bus_stops`
Search stops by name or list them around a coordinate.

| Input | Type | Required | Description |
|---|---|---|---|
| `query` | string \| null | one of | Stop name or id; accent- and case-insensitive. Cannot be combined with `lat/lon`. |
| `lat`/`lon` | number \| null | one of | Together; cannot be combined with `query`. |
| `radius_m` | int \| null | no | Only with `lat/lon`; default 1000. |
| `limit` | int \| null | no | |

If neither is given → `validation_error` (`field=query`).

### `izmir_bus_arrivals`
Live positions and remaining stop counts of buses approaching a stop.

| Input | Type | Required | Description |
|---|---|---|---|
| `stop_id` | string | yes | From the published stop list. |
| `limit` | int \| null | no | |

Unknown `stop_id` → `validation_error` (`field=stop_id`); a known stop that is
missing from GTFS is rejected separately by `departures`. The source **does not
publish ETAs/minutes**. An empty response is not proof of "no service"; a
warning is added.

### `izmir_bus_departures`
Published GTFS scheduled departures for a stop or for the stops around a
point; also stop id discovery by name.

| Input | Type | Required | Description |
|---|---|---|---|
| `stop_id` | string \| null | one mode | A published ESHOT stop. |
| `stop_query` | string \| null | one mode | Search by stop name/id. Returns stop candidates (`match=exact\|fuzzy`), **not departures**. `at` and `line` are rejected in this mode. |
| `lat` | number \| null | one mode | Together with `lon`; departures of nearby stops. |
| `lon` | number \| null | one mode | |
| `radius_m` | int \| null | no | Only with `lat`/`lon`; default 500, capped at `max_radius_m`. The 25 nearest stops are queried. |
| `at` | string \| null | no | `HH:MM` (Europe/Istanbul) or ISO-8601; default now. |
| `line` | string \| null | no | Line code filter; cannot be used with `stop_query`. |
| `limit` | int \| null | no | For one stop, that stop's limit; in radius mode, the total limit across **the whole stop set**. |

Exactly one target mode is given (`stop_id`, `stop_query` or `lat`+`lon`).
This is the planned timetable, not live departures/ETAs. Every response
carries `calendar_end`; once the calendar has ended (2026-10-09), out-of-range
queries return empty + a warning. `pickup_type=1` rows are dropped; `25:xx`
times are placed on the correct day. In radius mode, rows carry `stop_id`,
`stop_name` and straight-line `distance_m`; if there is no stop in the radius
the timetable store is never opened (empty response + warning). `stop_query`
mode does not build the timetable store either. The first departures query
builds the local SQLite store (~2.1M rows); see
[gtfs-schedule.md](gtfs-schedule.md).

### `izmir_bus_routes`
ESHOT GTFS line summary; with `detail=true`, the line's directions, ordered
stops and stop variants.

| Input | Type | Required | Description |
|---|---|---|---|
| `query` | string \| null | yes for `detail` | Line code/name; in `detail` mode the exact code/route_id. |
| `detail` | bool | no | `true` → stop patterns. |
| `direction` | string \| null | no | `0`/`1`; only with `detail=true`. |
| `limit` | int \| null | no | Not applied in `detail` mode. |

`detail=false`: line list + `calendar_end` and a staleness warning.
`detail=true`: **all** published patterns per `direction_id` are kept apart
(loop lines and short turns are not merged); when there is no `headsign`, no
direction name is invented. If several GTFS routes match, disambiguation by
route_id is requested. These are not live departures.

### `izmir_neighborhood_profile`
Neighbourhood profile from the published population and building count layers.

| Input | Type | Required | Description |
|---|---|---|---|
| `neighborhood` | string \| null | if no `district` | Neighbourhood name (mukhtar office inventory). |
| `district` | string \| null | if no `neighborhood` | District; on its own it lists every neighbourhood in the district. |
| `limit` | int \| null | no | |

`data[]`: `district`, `district_label`, `neighborhood`, `neighborhood_label`,
`population_total`, `population_male`, `population_female`, `population_year`,
`buildings`, `other_buildings`, `building_year`, `persons_per_building`.

- Population and buildings are **separate layers** published on different
  dates; a null `*_year` means the source gives no year.
- If a layer cannot be read, its fields return **null**, not zero; a warning is
  added.
- `persons_per_building` is a raw division, not a simultaneous census.
- A neighbourhood missing from the published layers → `validation_error`
  (`field=neighborhood`).

### `izmir_traffic_history`
Speed/duration **history** for İzmir's main arterials. This is not live
traffic; İzmir publishes no live traffic index (`/api/ibb/trafikyogunluk` →
404).

| Input | Type | Required | Description |
|---|---|---|---|
| `segment` | string \| null | no | Search in the start or end point name. |
| `since` | string \| null | no | YYYY-MM-DD lower bound (inclusive). |
| `until` | string \| null | no | YYYY-MM-DD upper bound (inclusive). |
| `limit` | int \| null | no | |

`data[]`: `segment_from`, `segment_to`, `observed_at`, `hour`, `speed_kmh`,
`duration_minutes`. Newest measurement first. A reversed date range →
`validation_error` (`field=until`). An empty result is not proof that "traffic
is flowing".

Freshness: `freshness.source_updated_at` is the source's **newest published
measurement**; `limits` reports it as `en_yeni_olcum=` and the threshold as
`stale_after_hours=` (input: `IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS`, default 72).
Data older than the threshold is `stale`; rows whose timestamp cannot be parsed
are `unknown`. An unfiltered small `limit` reads a single "newest first" page;
`matched` is still the source total. The `segment`/`since`/`until` filters do a
full scan so that `matched` and ordering stay consistent with the unfiltered
result.

### `izmir_gtfs_status`
Status of the local GTFS timetable store. Takes no input; **makes no network
call and does not rebuild the store**.

| Input | Type | Required | Description |
|---|---|---|---|
| — | — | — | Takes no input. |

`data[0]`: `database_path`, `built_at`, `feed_published_at`, `source_url`,
`calendar_start`, `calendar_end`, `checked_on`, `calendar_expired`,
`built_age_seconds`, `zip_bytes`, `stops_rows`, `routes_rows`, `trips_rows`,
`stop_times_rows`, `skipped_stop_times`.

- No store → `source_unavailable` (not an empty timetable).
- An ended calendar → `calendar_expired=true`, `freshness.status="stale"` and a
  warning.
- Store age is not the feed's publication age; a loaded store is not proof of
  live service.

## City layers

### `izmir_market_schedule`
Neighbourhood market calendar.

| Input | Type | Required | Description |
|---|---|---|---|
| `day` | string \| null | no | `pazartesi..pazar`, `bugun`, `yarin` (Turkish day names). |
| `district` | string \| null | no | District name (in the source's district field). |
| `lat`/`lon` | number \| null | together | Radius mode. |
| `radius_m` | int \| null | no | In radius mode; default 1500. |
| `limit` | int \| null | no | |

The market day is only extracted from free text (`ACIKLAMA`); markets without
a recognisable day are listed with `day_confidence="unknown"` and no day is
invented. Opening hours/status are not published.

### `izmir_transport_disruptions`
ESHOT, Metro and İZDENİZ announcements.

| Input | Type | Required | Description |
|---|---|---|---|
| `operator` | enum \| null | no | `eshot`, `metro`, `izdeniz`, `izban`. When omitted, the first three are merged. |
| `line` | string \| null | no | Line filter. |
| `active_only` | bool | no | Filters on rows where `active` can be computed. |
| `limit` | int \| null | no | |

`active` is computed **only for ESHOT** rows (it publishes a validity window);
for Metro/İZDENİZ it is null ("unknown"). `operator="izban"` always returns
`source_unavailable` (no reachable announcement feed). An operator that cannot
be read is dropped from the result with a warning; no "no disruption"
conclusion is drawn. These are announcements, not live delays or vehicle
telemetry.

### `izmir_tram_lines`
Tram lines and directions (`line_id`). Takes no input. Published data, not live
tram positions.

### `izmir_tram_schedule`
Stations and published headways of one tram line.

| Input | Type | Required | Description |
|---|---|---|---|
| `line_id` | int | yes | From `izmir_tram_lines` output, 1–999. |

Timetable data; not live arrival times.

### `izmir_bus_line_arrivals`
Buses of one line approaching a stop.

| Input | Type | Required | Description |
|---|---|---|---|
| `line` | string | yes | Line number. |
| `stop_id` | string \| null | no | From `izmir_bus_stops` output. When omitted, the line's live positions are returned. |
| `limit` | int \| null | no | |

No ETA in minutes is published; an empty result does not prove there is no
service.

### `izmir_bus_live_positions`
Live positions of the buses on a line (≤15 s cache).

| Input | Type | Required | Description |
|---|---|---|---|
| `line` | string | yes | Line number. |
| `limit` | int \| null | no | |

The source sends coordinates with decimal commas; they are converted to
numbers.

### `izmir_dam_status`
Status of İZSU dams for one day.

| Input | Type | Required | Description |
|---|---|---|---|
| `date` | string \| null | no | `YYYY-MM-DD`; default today, cannot be in the future. |
| `dam_name` | string \| null | no | Dam name, insensitive to Turkish letters and case. |
| `limit` | int \| null | no | |

Falls back to the CSV when the JSON API fails. Past days are cached long, today
briefly.

### `izmir_pharmacies_all`
All pharmacies (not only on-duty ones). For on-duty pharmacies use
`izmir_nearby`.

| Input | Type | Required | Description |
|---|---|---|---|
| `area` | string \| null | no | Published area label. |
| `query` | string \| null | no | Name search. |
| `lat` | number \| null | no | Together with `lon`. |
| `lon` | number \| null | no | Together with `lat`. |
| `radius_m` | int \| null | no | Only with `lat`+`lon`. |
| `limit` | int \| null | no | |

The source's `LokasyonX` field is latitude and `LokasyonY` is longitude; the
server corrects this.

### `izmir_cbs_layer`
Places from an İBB GIS (CBS) layer (allowlisted, e.g. `muzeler`, `hastaneler`,
`plajlar`).

| Input | Type | Required | Description |
|---|---|---|---|
| `layer` | enum | yes | Allowlisted CBS layer name. |
| `lat` | number \| null | no | Together with `lon`. |
| `lon` | number \| null | no | Together with `lat`. |
| `radius_m` | int \| null | no | Only with `lat`+`lon`. |
| `district` | string \| null | no | District filter. |
| `limit` | int \| null | no | |

These are locations, not open/closed status. Pagination is bounded and cached
daily.

### `izmir_events`
Culture and arts events.

| Input | Type | Required | Description |
|---|---|---|---|
| `query` | string \| null | no | Title/venue search. |
| `free_only` | bool | no | Free events only. |
| `limit` | int \| null | no | |

### `izmir_market_prices`
Wholesale market (fruit-vegetable/fish) prices.

| Input | Type | Required | Description |
|---|---|---|---|
| `kind` | enum | no | `sebzemeyve` (default) or `balik`. |
| `day` | string \| null | no | `YYYY-MM-DD`; default today. |
| `query` | string \| null | no | Product search. |
| `limit` | int \| null | no | |

If the source returns no content for a day (204), earlier days are checked and
the actual bulletin date is reported. For neighbourhood market days use
`izmir_market_schedule`.

### `izmir_fare`
İZBAN fare between two stations (TRY; full, student, teacher, 60+, free).

| Input | Type | Required | Description |
|---|---|---|---|
| `from_station` | int \| string | yes | İZBAN station id or name (insensitive to Turkish letters and case). |
| `to_station` | int \| string | yes | Cannot equal `from_station`. |
| `transfer` | bool | no | The source's transfer flag (sent as `0`/`1`). |
| `htt` | bool | no | The source's tariff flag (`true`/`false`); its meaning is undocumented in the API. |

Ids are validated against the published `izban/istasyonlar` list; an ambiguous
name returns `validation_error` with candidates. The response contains
`fares`, `refunds`, `min_balance` and `distance_km`.

### `izmir_parking_fees`
İZELMAN car park fee schedule (39 car parks).

| Input | Type | Required | Description |
|---|---|---|---|
| `query` | string \| null | no | Car park name fragment (plain substring). |
| `limit` | int \| null | no | |

`fees_try` gives the duration bands in TRY; empty or null columns are `null`.
For live occupancy use `izmir_nearby(types=["parking"])`.

### `izmir_traffic_cameras`
Traffic camera locations (92 points). No image or stream link is published.

| Input | Type | Required | Description |
|---|---|---|---|
| `query` | string \| null | no | Junction name fragment. |
| `lat` | number \| null | no | Together with `lon`. |
| `lon` | number \| null | no | Together with `lat`. |
| `radius_m` | int \| null | no | Only with `lat`+`lon`; default 2000, at most 50000. |
| `limit` | int \| null | no | |

### `izmir_water_production`
İZSU water production per dam/well — the latest published snapshot.

| Input | Type | Required | Description |
|---|---|---|---|
| `name` | string \| null | no | Dam/well name fragment. |
| `limit` | int \| null | no | |

The source has no date column and no unit; it is not presented as "today's
production". For dam fill levels use `izmir_dam_status`.

### `izmir_plan_trip`
Direct (single-mode) metro, İZBAN, İZDENİZ and ESHOT options between two
places; sorted by approximate duration, with walking/riding legs, the İZBAN
fare (when known) and active announcements.

| Input | Type | Required | Description |
|---|---|---|---|
| `origin` | string | yes | District/neighbourhood name, at most 80 characters. |
| `destination` | string | yes | District/neighbourhood name, at most 80 characters. |
| `depart_at` | string \| null | no | ISO-8601; informational only, no timetable matching. |
| `max_options` | int | no | 1–5, default 3. |

Durations are derived from straight-line distance and a fixed speed; they are
not timetables or live ETAs. If a source fails, a partial result and a warning
are returned. For real departures use `izmir_transit_schedule`.

### `izmir_health`
Local readiness and published limits. Takes no input. It does not measure
source health; `freshness.status="fresh"` only refers to the local runtime.
See [monitoring.md](monitoring.md) for the HTTP health endpoints.
