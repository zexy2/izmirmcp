# Limits

This page collects the detailed behavioural limits of izmirmcp that are too long
for the README. Per-tool contracts are in [tool-reference.md](tool-reference.md);
endpoint evidence is in [source-reachability-analysis.md](source-reachability-analysis.md).

## Summary

- Location tools (`izmir_nearby`, `izmir_city_services_nearby`, `izmir_mobility_nearby`)
  accept mutually exclusive modes: `lat/lon` or `place` + `radius_m`, `bbox`, or `district`.
  `bbox` results have `distance_m = null`; `district` is meaningful only for pharmacies.
- Truncation is always reported through `result_info.returned/matched/truncated`.
- There is **no live city-wide traffic index** (upstream returns 404); `izmir_traffic_history`
  is historical data only.
- There is **no reachable İZBAN announcements feed**; İZSU fault/outage endpoints
  return HTTP 500 and are reported as typed `source_unavailable` errors, never empty data.
- `izmir_bus_departures` is a published GTFS schedule, not a live ETA; the ESHOT GTFS
  calendar can expire and is surfaced as a warning.
- `izmir_datastore_query` is not server-side SQL: one safe SELECT over a local copy of an
  allowlisted resource, with copy budgets.
- HTTP guards (body cap, rate limit, concurrency, API keys, Origin allowlist) are in-process;
  use a reverse proxy for multi-worker global limits. See [security](security.md).

## HTTP surface hardening

| Protection | Default | Setting |
|---|---|---|
| Body cap | 1 MB | `IZMIR_MCP_CLIENT_MAX_BODY_BYTES` |
| Per-client rate limit | 60 requests, refill 1/s | `IZMIR_MCP_CLIENT_RATE_LIMIT_CAPACITY`, `..._REFILL_PER_SECOND` |
| Concurrency limit | 32 | `IZMIR_MCP_CLIENT_MAX_CONCURRENT_REQUESTS` |
| Bearer API key | off | `IZMIR_MCP_API_KEYS` |
| Browser Origin allowlist | empty (requests with an Origin are rejected) | `IZMIR_MCP_CORS_ALLOWED_ORIGINS` |
| Structured access log | on | `IZMIR_MCP_ACCESS_LOG_ENABLED` |

Overruns return an HTTP status code, not an envelope: `413 payload_too_large`,
`429 rate_limited` (+`Retry-After`), `503 server_busy`, `403 origin_not_allowed`,
`401 unauthorized` (+`WWW-Authenticate`).

Limits and honest notes:

- The rate limit and counters are **in-process** and volatile. In a
  multi-worker deployment every worker applies its own budget; put a reverse
  proxy in front for a global limit.
- `X-Forwarded-For` is only honoured while the server is bound to loopback and
  the request carries a single header with a single bare value. Comma-separated
  lists, repeated headers or values with whitespace are not trusted; the client
  identity is then the socket peer. So one connection cannot mint a fake
  identity per request to bypass the rate limit.
- The access log writes method, path, status and duration; query string, body,
  headers and API key are **never** logged.
- With an empty Origin allowlist, browser requests are rejected; CLI/stdio MCP
  clients (which send no Origin header) are unaffected.
- This layer is not an authorization server; it compares static keys and has
  no OAuth/rotating keys.

The local GTFS timetable store lives at `.data/izmir_mcp_gtfs.sqlite3` by
default; it can be changed with `IZMIR_MCP_GTFS_DATABASE_PATH` and is outside
git. Quota and the spatial index use `IZMIR_MCP_DATABASE_PATH`
(`.data/izmir_mcp.sqlite3`). See [gtfs-schedule.md](gtfs-schedule.md).

## Detailed limits

### Location modes

- `izmir_nearby` accepts three location modes: `lat/lon` or `place` +
  `radius_m`, `bbox=[min_lon, min_lat, max_lon, max_lat]`, and `district`. The
  modes are mutually exclusive; `radius_m` cannot be used with
  `bbox`/`district`. All three modes return
  `result_info.returned/matched/truncated`; when the result is cut by `limit`,
  `matched` reports the full match count and the summary says the first results
  are shown. `izmir_mobility_nearby` inherits the same contract.
- `bbox` mode **includes** all four edges and works for all six published types
  that carry coordinates. With no reference point, `distance_m` is **null** and
  results are not sorted by distance. Rows without coordinates in the source
  cannot fall inside the rectangle; the match count and truncation are reported
  in `result_info`.
- `district` mode is meaningful **only for pharmacies**. The source `Bolge`
  field is an on-duty area, not an administrative district (`KARŞIYAKA 4`,
  `BORNOVA 3`, etc.); matching relies on this area/area description text, not
  boundary validation, and no distance is shown. Only rows whose area text
  contains the district name match; this is not a full district inventory. The
  car park source publishes **no district and no address** (all 7 records were
  `null` at verification), and the metro/İZBAN/pier/stop layers have no
  district field either; these types are skipped in district mode with a
  warning. No match is not proof that "the district has no pharmacy".
- `izmir_city_services_nearby` accepts the same three location modes as
  `izmir_nearby`: `lat/lon` or `place` + `radius_m`, `bbox`, `district`. The
  modes are mutually exclusive; `radius_m` cannot be used with
  `bbox`/`district`. This tool has a **coverage difference** between modes:
  - `bbox` includes all four edges and only works on the WiFi and İzmirim Kart
    layers, which publish coordinates. **The library layer publishes no
    coordinates, so it never enters a rectangle query**; `distance_m` is null.
  - `district` lists a whole district and shows no distance. Matching uses the
    source's own district field or address text (`published_district_field`),
    not administrative boundary validation. WizmirNET and İzmirim Kart records
    match by address/district text, libraries by the district field. No match
    is not proof that "the district has no service".
  The match count and truncation are reported in `result_info`.
- Neighbourhood resolution relies on the İzmir Metropolitan Municipality's
  mukhtar office inventory (1,292 records → 1,219 unique neighbourhoods, 30
  districts). The point is the **per-neighbourhood average** of mukhtar office
  locations; it is not a neighbourhood boundary or door address.
- The same neighbourhood name can occur in several districts (`Atatürk` in 17).
  In that case `place` alone returns `validation_error` with the candidates;
  the district must be given with `place_district`. The first match is never
  picked silently.
- For neighbourhoods that share a district's name, the district reading wins
  (Konak district, not the Konak neighbourhood). See
  [place-resolution.md](place-resolution.md).

### Announcements

- `izmir_transport_disruptions` knows four operators: `eshot`, `metro`,
  `izdeniz`, `izban`. Without `operator`, the first three are merged. These are
  **announcements**, not live delays, vehicle positions or fault telemetry.
- Only ESHOT publishes a machine-readable validity window (start/end), so
  `active` is computed **only for ESHOT rows**. For Metro and İZDENİZ, `active`
  is **null** — "unknown", not "inactive".
- **There is no reachable announcement feed for İZBAN.** The `Rss.aspx` and
  `Sayfalar/Single.aspx` pages redirect with HTTP 302 to `FileNotFound.htm`,
  and the İZBAN announcement path on `metrotramapi` is 404. So
  `operator="izban"` always returns `source_unavailable`; it is not treated as
  "no announcements".
- An operator that is unreachable or returns nothing is dropped from the result
  and reported explicitly in `warnings`; no "this operator has no disruption"
  conclusion is drawn. The total match count and truncation are reported in
  `result_info`.
- ESHOT line notices are not live delays/vehicle status. The `active` field
  only compares the notice's own start/end dates with the system date.

### Traffic, water and air

- **There is no live traffic index** (`/api/ibb/trafikyogunluk` → 404).
  `izmir_traffic_history` only returns **historical** segment measurements
  (8 fixed corridors, 2020-06 → 2026-10); it is not live congestion or an ETA.
  `freshness.source_updated_at` is the source's **newest published
  measurement**, and `limits` reports it with `en_yeni_olcum=` and the
  freshness threshold with `stale_after_hours=`
  (`IZMIR_MCP_TRAFFIC_STALE_AFTER_HOURS`, default 72). Data older than the
  threshold is `stale` — freshness is never claimed from the re-download time.
  An unfiltered small `limit` does a single-page "newest first" read and takes
  the total from the source's `total` field; the `segment`/`since`/`until`
  filters need a full scan because a match can be anywhere in the dataset.
- Only a historical `ana-arterler-gunluk-hiz-ve-sure-verileri` dataset and a
  2023 `trafik-kameralari` list exist.
- There is no accident/incident data. `izmir_plan_trip` only offers direct
  single-mode options from straight-line estimates; it is not a multi-leg
  journey planner.
- No data is produced for the İZSU fault/outage feed because the source returns
  500.
- The air quality source publishes no coordinates or units; no AQI is computed.

### Timetables and buses

- The metro timetable is an hour range and headway table, not a station pair.
- The İZDENİZ `day` value is the source's own day id; it is not assumed to be
  the weekday.
- The ESHOT arrival feed **publishes no ETA/minutes**; only the number of
  remaining stops and the live vehicle position are returned. Because the
  approaching-bus endpoints return `200` + an empty array for invalid stops
  too, an empty response is not proof of "no service"; the envelope carries a
  warning.
- İZTEK returned `429` under consecutive heavy requests, so the connection runs
  with a soft rate limit and a 20-second cache.
- The service window in ESHOT GTFS `calendar.txt` **ended on 2026-10-09**
  (verified 2026-10-28). `izmir_bus_routes` and `izmir_bus_departures` return
  `calendar_end` and a "timetable may be out of date" warning in every
  response; no departures are produced for dates outside the calendar.
- `izmir_bus_routes(detail=true)` returns **all published stop variants** of a
  line per `direction_id`. Short turns or alternative routes in the same
  direction are not merged; `stop_sequence` order and repeated stops (loop
  lines) are preserved. `limit` does not apply in this mode. The source
  publishes no `trip_headsign`, so no direction name is invented; only
  `direction_id` and the source heading, if any, are given. This is also the
  published timetable, not live departures or ETAs.
- On the first departures query, `izmir_bus_departures` loads ESHOT GTFS
  `stop_times.txt` (~2.1M rows, 85 MB) into the local SQLite store (measured:
  ~4 s, ~141 MB); later queries read from indexes. Without `at`, the current
  Istanbul time is used. This is the **planned timetable**, not live
  departures, delays or ETAs. `pickup_type=1` (no boarding) rows are dropped and
  GTFS times such as `25:xx` are placed on the correct calendar day.
- `izmir_bus_departures` offers two extra modes: `stop_query` only returns
  stop candidates (not departures; `match=exact|fuzzy`) and **never builds the
  timetable store**, while `lat`+`lon` merges the departures in the radius
  (default 500 m, nearest 25 stops) into one time order. With no published stop
  in the radius, the store is not opened and an empty response + a warning is
  returned; `distance_m` is straight-line and `limit` is the total for the
  whole stop set, not per stop.
- The İZDENİZ GTFS ZIP link returns `text/html`, so there is no ferry GTFS
  coverage; the current İZDENİZ trip tools use the openapi sources.
- The metro, tram and İZBAN GTFS archives were downloaded and verified but not
  wired: the İZBAN feed is from 2023 and its calendar ended on 2025-01-01, so it
  is not current.
- Undocumented guessed paths such as `/api/eshot/...` and `/api/iztek/hatlar`
  return `404` and are not used. `ibb/cbs/noktayayakinduraklar` was not wired
  because its projection parameters could not be verified.

### City layers

- The neighbourhood market day is only extracted from the source's free text
  (`ACIKLAMA`). Records without a recognisable day are listed with
  `day_confidence="unknown"`; no day is invented and "no market that day" is not
  treated as proof.
- The library layer **publishes no coordinates**, so `distance_m` and
  `maps_url` are null and the radius filter cannot be applied. Address and
  district are given.
- In the WizmirNET and İzmirim Kart layers the source publishes the same
  location in several rows; identical locations/addresses are deduplicated and
  the number of duplicate rows is reported in a warning.
- İzmirim Kart top-up points are a static publication dated **2023-08-21**; a
  point may have closed.
- **There is no metro equipment/fault data**: `metro/ekipmanlar` and
  `metro/arizalar` return `404`. There is no counterpart of Istanbul's
  `metro_accessibility_status` tool.
- No dataset is published under the name "sosyal tesis" (social facilities);
  there is no one-to-one counterpart of the upstream `sosyal_tesis_nearby`
  tool.

### Local SQL and error labels

- `izmir_datastore_query` is not server-side SQL: a single SELECT only runs
  after a resource explicitly allowed by `IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS`
  has been copied **in full** into local SQLite. The list is empty by default;
  if the resource exceeds the row/byte budget or changes between pages,
  `source_unavailable` is returned and no partial aggregate is produced. There
  are no JOINs, subqueries, CTEs, UNIONs, window functions or writes. Details:
  [datastore-sql.md](datastore-sql.md).
- Source error labels are produced in one place (`source_failure_envelope`):
  HTTP 429 → `source_rate_limited`, timeout → `source_timeout`, other source
  failures → `source_unavailable`. None of them leaks as an exception.
- The envelope conformance test replays source responses; it verifies field
  shape and the error taxonomy, not that the live source returns the same
  schema today. Live verification is the job of `scripts/smoke_live.py`.
