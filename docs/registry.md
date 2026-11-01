# MCP registry publishing

`server.json` is the MCP Registry manifest. Its content must stay **in sync**
with the package version; `tests/test_packaging.py` enforces this. For the
runtime MCP surface itself, see [mcp-interface.md](mcp-interface.md).

## Manifest structure

The manifest lists a single OCI package that runs the stdio transport inside
the container:

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.zexy2/izmir-mcp",
  "version": "<pyproject version>",
  "packages": [
    {
      "registryType": "oci",
      "identifier": "ghcr.io/zexy2/izmir-mcp:<version>",
      "runtimeHint": "docker",
      "packageArguments": [
        {"type": "positional", "value": "izmir-mcp"},
        {"type": "positional", "value": "stdio"}
      ],
      "environmentVariables": [
        {"name": "IZMIR_MCP_SKIP_GTFS_BUILD", "default": "1"}
      ],
      "transport": {"type": "stdio"}
    }
  ]
}
```

Rules (verified by tests):

- `$schema` must match the registry schema vendored under
  `tests/fixtures/mcp_registry/`.
- `name` must have the form `io.github.<owner>/<repo>`, and the README must
  carry the matching `<!-- mcp-name: ... -->` marker (PyPI ownership check).
- `version` must be **identical to `pyproject.toml`**.
- `packages` is OCI-only, with `stdio` transport and the package arguments
  `izmir-mcp stdio`.
- The OCI tag must equal the package version, and the image name must match
  the `izmir-mcp` image the Dockerfile builds.

A PyPI package entry will be added back once trusted publishing for PyPI is
ready (see `CHANGELOG.md`).

## Release steps

When cutting a release:

1. Bump the version in `pyproject.toml`.
2. Set the `version` field and the OCI image tag in `server.json` to the same
   value.
3. Add a version heading to `CHANGELOG.md`.
4. Run `python scripts/check_release_metadata.py` (server.json vs `app/__init__.py`) and
   `pytest -q tests/test_packaging.py`; both must pass.
5. Push the tag. `release.yml` builds and scans the image, pushes it to GHCR,
   and publishes `server.json` with `mcp-publisher`. The PyPI job only runs
   when `vars.PUBLISH_PYPI` is set.

To rehearse locally before tagging, run `scripts/local_release_check.sh` (see
[development.md](development.md)).

## Known status

- The project is MIT-licensed (`LICENSE`, `pyproject.toml`).
- The PyPI release is pending; until then the README documents installing from
  source.
