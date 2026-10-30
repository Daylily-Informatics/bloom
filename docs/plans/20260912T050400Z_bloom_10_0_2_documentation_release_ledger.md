# Bloom 10.0.2 documentation release ledger

Status: SUCCESS

## Gate 0

- Baseline: clean `codex/bloom-tapdb10-receipts`, commit `4a073c0`; highest remote 10.x tag is annotated `10.0.1`.
- Scope: current documentation and AGENTS.md aligned to this checkout. Historical migration receipts remain historical.
- Release: annotated `10.0.2` from this working branch, branch/tag push and GitHub tagged release. No PR, merge, tests, package/container build, production inspection or redeployment.
- Version is derived by setuptools-scm; no application version constant needs editing.

| ID | Requirement | Owner | Status | Evidence |
|---|---|---|---|---|
| D00 | Record baseline and release boundary | Operator | SUCCESS | Gate 0 above |
| D01 | Reconcile current docs and instructions with source | Operator | SUCCESS | pyproject.toml; activate; CLI registrations; container entrypoint; TapDB mount/DAG; API/GUI routers; completed migration ledger |
| D02 | Commit and push documentation revision | Operator | SUCCESS | Twelve Markdown paths committed as `64f9343f5af8cd0e2d8ac85cb9772dc26ff5c1c0` and pushed to `origin/codex/bloom-tapdb10-receipts` |
| D03 | Publish annotated 10.0.2 and GitHub release | Operator | SUCCESS | Annotated `10.0.2` peels to `64f9343f5af8cd0e2d8ac85cb9772dc26ff5c1c0`; tag push and published GitHub release confirmed |

The deployed baseline recorded by the completed migration remains Bloom 10.0.1 / TapDB 10.1.3 and Kahlo 8.0.1. This documentation release does not change it.

## Documentation reconciliation

Updated README, AGENTS.md, API/GUI/architecture/setup/discovery/lab-action guides and the archive index against registered commands, mounted routes, configuration and exact dependency source. Added the TapDB 10 operations guide. Preserved historical migration receipts. Recorded the existing auth-group casing inconsistency as P207 without changing runtime code.

Validation was static source/document review only. No tests, lint, CI campaign, builds or runtime probes were run. The repository CI workflow is scoped to main pushes and main pull requests; this release uses the existing working branch and a numeric tag.

## Release receipt

- [Bloom 10.0.2](https://github.com/lsmc-bio/bloom/releases/tag/10.0.2) was published at `2026-09-12T05:11:58Z`; GitHub reports non-draft, non-prerelease.
- `git cat-file -t 10.0.2` returned `tag`; the peeled commit is `64f9343f5af8cd0e2d8ac85cb9772dc26ff5c1c0`.
- All four rows are SUCCESS. This receipt is a subsequent documentation commit on the same working branch; the published release tag remains immutable.
- No PR, merge, test, lint, build, PyPI publication, production inspection or redeployment was performed.
