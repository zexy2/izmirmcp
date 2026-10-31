# Tool migration policy

This document explains how the MCP tool surface changes and what clients can
rely on.

## Compatibility promise

- A published tool's **name** does not change and the tool is not removed.
- A published tool's **input schema** does not change: no parameter is removed,
  renamed or narrowed in type, and no optional parameter becomes required.
- New tools, prompts and resources may be added.
- New fields may be added to the response envelope; existing fields are not
  removed. See the [Response contract](response-contract.md).

This promise is enforced by `tests/test_tool_compatibility.py`: the names and
input schemas of existing tools are compared one-to-one with
`tests/fixtures/tool_compatibility_snapshot.json`. The snapshot is only
regenerated for a deliberate breaking change documented in the CHANGELOG (a new
major version). Adding descriptions to existing parameters is not a breaking
change.

## Breaking change process

1. Add the new behaviour under a new tool name; keep the old tool.
2. Add a deprecation note and the new tool's name to the old tool's
   description.
3. Add it to the "Deprecated" section of the CHANGELOG.
4. The old tool may be removed at the earliest in the next **major** version;
   the snapshot is regenerated in that version.

## Change history

| Version | Change | Client impact |
|---|---|---|
| 0.1.0 | 22 tools and 7 prompts; the `nobetci_eczane` prompt was added to the first release (it uses the existing `izmir_nearby` tool). | None; the tool surface did not change. |

Later additive changes (the current surface is 36 tools and 12 prompts) are
listed in `CHANGELOG.md`.

## Deliberately not added

Capabilities without an open and reliable source are not added as tools.
Example: metro elevator status. The İzmir OpenAPI has no such endpoint
(`metro/asansor*`) and the open data catalog has no matching dataset. Details:
[Sources](sources.md).

## Console commands and package

The `izmir-mcp` and `izmir-mcp-stdio` commands and the `server.json` package
definitions fall under the same compatibility promise; they are locked by
`tests/test_packaging.py`.
