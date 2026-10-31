# Local SQL snapshot

The CKAN instance behind the İzmir Open Data portal does not expose the
`datastore_search_sql` action (`"Action name not known"`, 2026-10-28). That is
why `izmir_query_resource` only offers filters, free text and sorting. For
analytical questions (`GROUP BY`, `COUNT`, averages), the
`izmir_datastore_query` tool follows the same approach as the upstream
istanbulmcp project: it copies an allowed resource **in full** into a local
SQLite table and runs the query there.

## Why not server-side SQL?

CKAN's SQL action does not exist on this portal. Fetching only a few pages of a
resource and aggregating over them silently produces wrong results. So the tool
either takes a complete copy or returns `source_unavailable`; it **never
produces a partial aggregate**.

## Enabling it

By default the tool downloads no resource. First find the resource id with
`izmir_search_datasets` / `izmir_get_dataset`, check the schema with
`izmir_get_resource_schema`, then add the id to the allowlist:

```bash
export IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS="0c791266-a2e4-4f14-82b8-9a9b102fbf94"
```

Up to 100 comma-separated resources may be given. With an empty list the tool
returns `validation_error` (`field=resource_id`) without a network call.

## Query contract

- The only table name is `records`; columns are the published names from
  `izmir_get_resource_schema`.
- A single `SELECT`; JOIN, subqueries, CTE, UNION, window functions and writes
  are rejected.
- Allowed functions: `count`, `sum`, `avg`, `min`, `max`, `round`, `abs`,
  `coalesce`, `lower`, `upper`, `length`, `substr`, `trim`, date functions.
- The result is at most `limit` rows (default 10, cap 50); the outer limit is
  applied independently of the query's own `LIMIT`.
- A query is limited to 0.5 s and 2,000,000 VM steps; the result cannot exceed
  256 KiB.

Example:

```sql
SELECT COUNT(*) AS n FROM records
```

Column names must be checked first; an example analytical query:

```sql
SELECT ILCE, COUNT(*) AS n
FROM records
GROUP BY ILCE
ORDER BY n DESC
```

`ILCE` is only valid if it exists in the resource schema; the tool does not
invent column names.

## Copy budget

| Setting | Default | Code bound |
|---|---|---|
| `IZMIR_MCP_CKAN_SQL_MAX_ROWS` | 50,000 | 1–50,000 |
| `IZMIR_MCP_CKAN_SQL_MAX_BYTES` | 20 MiB | 1 KiB–20 MiB |
| `IZMIR_MCP_CKAN_SQL_PAGE_SIZE` | 5,000 | 1–5,000 |
| `IZMIR_MCP_CKAN_SQL_SNAPSHOT_TTL_SECONDS` | 900 | 1–3,600 |
| `IZMIR_MCP_CKAN_SQL_LOAD_TIMEOUT_SECONDS` | 30 | 0.01–60 |
| `IZMIR_MCP_CKAN_SQL_QUERY_TIMEOUT_SECONDS` | 0.5 | 0.001–2 |

Pages are requested with `_id asc`, and the total and schema are re-validated
on every page. The copy is rejected if an `_id` repeats, the total changes, the
byte/row budget is exceeded, or the source returns a short page.

## Envelope and honesty

A successful response carries the time the copy was taken as `freshness`; this
is not the age of the rows. `limits` contains `snapshot_rows`,
`snapshot_wire_bytes`, `no_partial_aggregates` and the engine limits. If the
result limit truncates rows, `result_info.truncated=true` and a warning are
added. Source failures return `source_unavailable` / `source_timeout` /
`source_rate_limited`; no exception leaks.

## Tests

- `tests/test_guarded_sql.py` — verifies that the parser and the SQLite
  authorizer reject JOIN, subqueries, CTE, UNION, `sqlite_master`, `ATTACH`,
  `load_extension` and write attempts, and that aggregates and the outer limit
  work.
- `tests/test_datastore_sql.py` — verifies the allowlist, full copy, changing
  totals, repeated `_id`, budget overruns, caching and typed source errors.
- `tests/test_contract_conformance.py` — locks that invalid SQL returns
  `validation_error` without a network call.
