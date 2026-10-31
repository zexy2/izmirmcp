# Response Contract

This document is the **single source of truth** for the envelope every MCP tool
returns. Its source is `app/core/envelope.py` and `app/core/validation.py`;
when behaviour changes, the code is updated first and this document second.
`tests/test_docs.py` locks this document against the code. For per-tool inputs
see [tool-reference.md](tool-reference.md); for protocol-level errors see
[mcp-interface.md](mcp-interface.md#error-semantics).

## Envelope

Every tool output is validated against the same Pydantic model
(`ResponseEnvelope`) and returned as MCP `structured_output`. Plain Python
handlers return dicts; `app/mcp/structured.py` turns them into the model. The
following fields are **always** present:

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | `true` when the tool returned data successfully; `false` in an error envelope. |
| `summary` | string | One-line human summary. Counts and scope live here. |
| `data` | list[object] | Record list. Usually empty in an error envelope. |
| `freshness` | object | Data freshness and source timestamp (below). |
| `sources` | list[object] | Evidence sources; attribution and public URL (below). |
| `limits` | list[string] | Limits applied in this response (`limit=10`, `realtime=false`…). |
| `warnings` | list[string] | Honesty warnings; this is where an empty result is marked as not meaning "none exist". |
| `next_queries` | list[string] | Suggested next tool calls. |
| `error` | object \| null | Error taxonomy (below). `null` on success. |
| `result_info` | object | Returned/matched/truncation info (below). |
| `disclaimer` | string \| null | Fixed bilingual notice: the data is unofficial, comes from İBB open data, and may be delayed or wrong. |

User-facing runtime text (`summary`, `warnings`, error messages and hints) is
Turkish; field names and codes are stable English identifiers.

### `freshness`

| Field | Type | Meaning |
|---|---|---|
| `status` | `fresh` \| `stale` \| `unknown` \| `broken` | Freshness class of the data. |
| `retrieved_at` | ISO-8601 UTC | When this server fetched the data. |
| `source_updated_at` | string \| null | The source's own timestamp. For GTFS it carries `calendar_end`. |
| `ttl_seconds` | int \| null | In-app cache lifetime of this data. |

- `fresh` — freshly read from the source (or cached within TTL).
- `stale` — an old cached copy was used, or the source window has passed
  (e.g. the ESHOT GTFS calendar ended on 2026-10-09).
- `unknown` — the tool returns local metadata and claims no source freshness.
- `broken` — error envelope; the data could not be read.

`izmir_health` and the `izmir://*` resources return **`fresh`**, but this only
refers to local readiness metadata, not source health (`upstream_health:
"not_checked"`).

### `sources[]`

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Source name. |
| `publisher` | string | Publishing institution (default İzmir Metropolitan Municipality). |
| `url` | string \| null | **Public pages only**. API endpoints and addresses with file extensions are reduced to `null`. |
| `license` | string \| null | The licence when known. `null` for most city sources: public access is not a licence grant. |
| `dataset_id` / `resource_id` | string \| null | CKAN ids. |
| `scope` | string \| null | Data kind (`stops`, `published_timetable`, `live_vehicle_positions`…). |
| `source_updated_at` | string \| null | Update time reported by the source. |

`public_page_url()` is applied when `url` is serialised: `http://`,
`api.*`/`*.api` hosts, `/api/`, `/download/` and `/docs/` paths, and file
extensions such as `.csv`/`.json`/`.zip` return `null`. This stops agents from
showing users API endpoints. Attribution is always `name` + `publisher`.

### `result_info`

| Field | Type | Meaning |
|---|---|---|
| `returned` | int | Number of records in `data`. |
| `matched` | int \| null | Total matching the filter (as reported by the source). `null` when unknown. |
| `truncated` | bool \| null | `true` when `matched > returned`. `null` when truncation is unknown. |
| `scope` | string | Query mode (table below). |
| `next_step` | string \| null | When truncated, a suggestion to raise the limit or narrow the query. |

`scope` values (from code):

| `scope` | Producing tool/mode |
|---|---|
| `data` | Default (tools that report no match count). |
| `error_details` | Every error envelope. |
| `bbox` | `bbox` mode of `izmir_nearby` and `izmir_city_services_nearby`. |
| `district` | `district` mode of `izmir_nearby` and `izmir_city_services_nearby`. |
| `radius` | Radius mode of `izmir_nearby` and `izmir_city_services_nearby`. |
| `mobility_nearby` | `izmir_mobility_nearby` transport summary; counts refer to the rows shown (`counts_scope=shown`). |
| `route_detail` | `izmir_bus_routes(detail=true)`. |
| `published_departures` | `izmir_bus_departures` (`stop_id` mode). |
| `published_departures_near` | `izmir_bus_departures` `lat`/`lon` radius mode. |
| `stop_candidates` | `izmir_bus_departures(stop_query=...)` stop discovery; not departures. |
| `operator_notices` | `izmir_transport_disruptions`. |
| `traffic_history` | `izmir_traffic_history`. |
| `sql` | `izmir_datastore_query`. |
| `outside_coverage` | `izmir_nearby`/`izmir_mobility_nearby` coordinate outside İzmir province. |

When `truncated` is **unknown**, `result_info` leaves a "not the full total"
note; when truncated, it leaves a "raise within the limit or narrow the filter;
this is not the full total" note. An empty `data` alone is not proof of
absence; read `warnings`.

## Error taxonomy

Error envelopes never leak exceptions. `ok=false`, `error` is set, and
`freshness.status` is usually `broken` (source access) or `stale` (it may stay
`fresh` for local/invalid-input cases).

| `error.code` | When | `temporary` | `error.field` |
|---|---|---|---|
| `validation_error` | Invalid input (type, range, mutually exclusive modes). | `false` | Name of the offending field. |
| `not_found` | CKAN `dataset_id`/`resource_id` does not exist. | `false` | `dataset_id` or `resource_id`. |
| `source_unavailable` | Source HTTP error/500, malformed body, unreachable endpoint. | `true` | `null`. |
| `source_timeout` | The source timed out. | `true` | `null`. |
| `source_rate_limited` | The source returned HTTP 429. | `true` | `null`. |
| `request_failed` | Generic error without a code (internal default). | `false` | `null`. |

When `temporary=true`, `error.next_step` suggests retrying later; otherwise it
says to review the inputs and the published limits. Cases where a source is
**knowingly unavailable** (İZSU faults: HTTP 500; İZBAN announcements:
302→FileNotFound/404) return an explicit `source_unavailable` instead of
invented data.

### Validation error rules

`InputValidationError` carries the field name. The most common fields:

- `lat`/`lon` — must be given together; `lat` ∈ [-90, 90], `lon` ∈ [-180, 180].
- `bbox` — `[min_lon, min_lat, max_lon, max_lat]`, finite, four elements,
  `min < max`; zero width/height is rejected.
- `radius_m` — positive and within `max_radius_m` (default 5000); only with
  `lat/lon` or `place` mode.
- `limit` — positive and within `max_limit` (default 50).
- `types`/`kinds` — a non-empty subset of the defined values.
- `filters` — an object; at most 10 keys; keys match `[\w .:-]+`; values are
  scalars or lists of at most 20 scalars; text is cut to 200 characters. An
  unknown column name returns `validation_error` + `filters`.
- `place` — must be a published reference point; cannot be combined with
  `lat/lon`.
- `at` — `HH:MM` (Europe/Istanbul) or ISO-8601.
- `date` — `YYYY-MM-DD`.
- `direction` — `0` or `1`, only with `detail=true`.

## HTTP surface errors (outside the envelope)

The protection layers on `/mcp` return an HTTP status code and a small body,
**not** an envelope: `{"ok": false, "error_code": "<code>", "summary": "<text>"}`.
Details and defaults are in [deployment.md](deployment.md). The envelope
contract only applies to **tool calls**.

## Contract tests (P4)

The envelope contract is tested, not assumed:

| Test | What it locks |
|---|---|
| `tests/test_contract_conformance.py` | For every advertised tool, `set(payload) == ResponseEnvelope.model_fields`; `result_info.returned == len(data)`; `error=null` when `ok=true`; `scope="error_details"` when `ok=false`. |
| same file, error parameters | Invalid input returns `validation_error` + `error.field` + `temporary=false` without a network call. |
| same file, replay | When a recorded source response is replayed as 503/500, every tool returns either a typed `source_*` error or a partial result with `warnings`; no exception ever leaks. |
| `tests/test_discovery_surface.py` | `output_schema` carries the same fields and the same `required` set as the `ResponseEnvelope` schema; resource/prompt schemas are valid. |

The tests replace the connector with `httpx.MockTransport`; there is no
network. This verifies **field shape and the error taxonomy**, not that the
source publishes the same data today — that evidence comes from
`scripts/smoke_live.py`.

### The 429 label

All services translate source failures with the shared
`source_failure_envelope` helper: HTTP 429 becomes `source_rate_limited`, a
timeout becomes `source_timeout`, and other failures become
`source_unavailable`. All three carry `temporary=true`. This label is locked by
`tests/test_contract_conformance.py`.
