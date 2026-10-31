# Commit convention

This project follows [Conventional Commits](https://www.conventionalcommits.org/).
History is never rewritten; the convention applies to new commits and PR titles.

## Format

```
<type>(<scope>): <subject>
```

- **type**: `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`, `perf`, `build`
- **scope** (optional): `connectors`, `mcp`, `docs`, `ci`, ...
- **subject**: English, imperative mood ("add", not "added"), no trailing period,
  72 characters or fewer for the whole header line.
- Append `!` after type/scope (e.g. `feat(mcp)!:`) for breaking changes and
  describe them in a `BREAKING CHANGE:` footer.

Examples:

```
feat(connectors): add İZSU outage connector
fix(mcp): return empty list instead of null for unknown stop
docs: document IZMIR_MCP_CACHE_TTL
ci: pin trivy-action to v0.36.0
```

## Local template

```
git config commit.template .gitmessage
```

## Enforcement

Pull request titles are checked by `.github/workflows/commitlint.yml`
(squash merges use the PR title as the commit message). There is no local
hook that blocks commits; work-in-progress commits are fine on branches.

## AI co-author trailers

- AI tools may assist; the human author is accountable for every change.
- Add a `Co-authored-by:` trailer only when an AI tool produced a substantive
  part of the change. Do not add trailers for autocomplete-level help.
- Never let a trailer replace review, tests or a meaningful subject line.

## Author identity

`.mailmap` unifies historical spellings of the maintainer's name, so
`git shortlog -sn` shows one author.
