# Contributing to izmirmcp

Thanks for helping improve izmirmcp. This guide covers local setup, checks, and how to propose changes.

## Setup

```bash
# with uv (recommended)
uv sync --all-extras
# or with pip
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Running checks

```bash
.venv/bin/python -m pytest -q   # unit tests, no network
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app
```

All three must pass before you open a pull request.

## Adding a tool

1. Implement the connector under `app/` and register the tool with a clear name and description.
2. Add unit tests with recorded fixtures; tests must not hit the network.
3. Update the tool-surface snapshot. Snapshot changes must be **additive**: never rename or
   remove an existing tool without a migration note in `docs/tool-migration.md`.
4. Document the tool in `docs/tool-reference.md` and the README catalog.

## Commit convention

We use Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`, `perf`, `build`).
See `.gitmessage` and `docs/development/commit-convention.md`. PR titles are linted with the same rules.

## Pull request checklist

- [ ] Tests, ruff and mypy pass locally
- [ ] Tool snapshot changes are additive (or documented)
- [ ] Docs and CHANGELOG updated where relevant
- [ ] No secrets, tokens or personal data in code, fixtures or logs

## Conduct and security

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
