# GTFS timetable store

This document describes the local timetable store behind the
`izmir_bus_departures`, `izmir_bus_routes(detail=true)` and
`izmir_gtfs_status` tools. Code: `app/storage/gtfs_schedule.py`; service:
`app/services/bus.py`.

## Why a local store

The published ESHOT archive is an 18 MB ZIP containing a ~85 MB
`stop_times.txt` with 2,108,736 rows. Downloading and parsing that file on
every query would be slow and disrespectful to the source. It is downloaded
once into SQLite and then read from indexes. Measured build: **~3.7 s**, a
~141 MB database.

## File layout

- Default path: `.data/izmir_mcp_gtfs.sqlite3`
- Changed with `IZMIR_MCP_GTFS_DATABASE_PATH`. It is separate from
  `IZMIR_MCP_DATABASE_PATH`, which the quota and spatial index use: a timetable
  rebuild writes 2.1M rows and must not lock that file.
- Covered by `.gitignore` and `.dockerignore`: it **never** enters the
  repository or the image.
- In a container it is written to the `/data` volume and built at startup by
  `docker/entrypoint.sh`.

## Build and freshness

1. The first departures query builds the store if it does not exist.
2. When the store's age exceeds `IZMIR_MCP_ESHOT_GTFS_CACHE_TTL_SECONDS`
   (default 86400), a rebuild is attempted.
3. If the rebuild fails, the old copy is used with `freshness.status="stale"`
   while within `IZMIR_MCP_ESHOT_GTFS_STALE_IF_ERROR_SECONDS` (default 604800);
   beyond that the tool returns `source_unavailable`.
4. A build never leaves a half-written file: it is written to a temporary file
   and moved atomically.

Budgets: `IZMIR_MCP_ESHOT_GTFS_MAX_BYTES` (ZIP), `..._MEMBER_MAX_BYTES` (one
member), `..._STOP_TIMES_MAX_BYTES`, `..._MAX_ROWS`. Exceeding one rejects the
build; it never yields partial data.

## Calendar reality

The `calendar.txt` window in the archive is **2026-08-05 → 2026-10-09**. The
verification date was 2026-10-28, so the calendar has **expired**.

Consequences:

- `calendar_end` is returned in every response.
- A date outside the window returns `ok: true`, empty `data`,
  `freshness: stale` and an explicit warning — it never says "no service".
- `izmir_gtfs_status` reports this with `calendar_expired: true`.

This is not a bug but the state of the source. When the feed is updated, the
store is refreshed automatically and the warning disappears on its own.

## What is loaded and what is not

| File | Loaded | Why |
|---|---|---|
| `stops.txt`, `routes.txt`, `trips.txt`, `calendar.txt` | Yes | Stops, lines, trips and service days |
| `calendar_dates.txt` | Yes (if present) | Exception days; absent from the archive today but supported |
| `stop_times.txt` | Yes | The only source of departure times |
| `shapes.txt` | No | 12 MB of route geometry; not needed by the tools |

`pickup_type=1` (no boarding) rows are dropped. The source has no
`trip_headsign`; no direction name is **invented**, only `direction_id` is
given.

## Query modes

`izmir_bus_departures` accepts three target modes; only two of them touch the
timetable.

| Mode | Returns | Timetable store |
|---|---|---|
| `stop_id` | That stop's `stop_times` rows | Opened |
| `lat`+`lon` (+`radius_m`) | Departures of the 25 nearest stops in the radius, in one time order | Opened |
| `stop_query` | Stop candidates (`match=exact\|fuzzy`) | **Not opened** |

In radius mode a single SQL statement scans all stop ids with `IN (...)` and
returns rows ordered by `departure_sec` per day, so the result is true time
order rather than blocks per stop. `distance_m` is straight-line. If no
published stop is in the radius, the store is never opened: empty `data` + a
warning, not a "no service" claim. In radius mode `limit` is the total limit
for **the whole stop set**.

## Times after 24:00

In GTFS, `25:10:00` means "01:10 the next day". Times are converted to absolute
time relative to the service day, and the previous service day is scanned as
well, so trips that cross midnight land on the correct day.

## Command line

```bash
python -m app.storage.gtfs_schedule                  # build at the default path
python -m app.storage.gtfs_schedule --database /data/x.sqlite3
python -m app.storage.gtfs_schedule --url <alternative archive>
```

**Nothing is written** for an invalid archive.

## Not live data

This store is the published timetable. For live positions use
`izmir_bus_arrivals` (no ETA, only remaining stops + vehicle position); there is
**no** source for live departures.
