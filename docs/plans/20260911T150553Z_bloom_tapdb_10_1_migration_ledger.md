# Bloom 10.0.0 / TapDB 10.1.1rc1 Migration Ledger

Date: 2026-09-11

Status: active execution ledger

## Decisions and immutable inputs

- This ledger replaces the earlier expanded migration process under the user-approved bounded amendment dated 2026-09-11.
- Bloom will release as breaking major `10.0.0` and use `daylily-tapdb[aurora,gui]==10.1.1rc1`.
- TapDB Git tag: annotated tag object `1ac2f09a1787b9e747eda582c45a628ca60b7020`, peeled commit `02ab7c9d0325dfcbf9dc47a03be66b62e0a22f2c`.
- TapDB package hashes: wheel SHA-256 `6de691dd5f9c8fac596a18119c9220f4ea78826094753b47f9eb936b0677ce7`; sdist SHA-256 `abf2e5b18184db736c8e54fb77cbc96e78c77921f0f65b7c8f026ebb20a8a5fb`.
- A sustained Bloom outage is accepted. The existing Aurora recovery arrangement is accepted. This execution creates no snapshot, dump, database copy, replacement database, or rehearsal database.
- One production migration is permitted. Preserve acknowledged work, existing data, EUIDs, allocator guarantees, audit history, deleted history, authoritative lineage, and queued Bloom work.
- Remove compatibility shims and fallback behavior. Minor features and outstanding pull-request integration remain phase 2 work after acceptance.
- Restore `main` as the GitHub default and primary branch. Release work targets `main`; after merge, align the local checkout and default upstream with `main`.
- Cost bounds: one final Bloom container build; one broad Bloom test/CI campaign with at most one informative rerun; focused checks only for changed behavior and demonstrated failures.

## Gate 0 baseline

- Controlling source: `https://github.com/lsmc-bio/bloom.git`.
- Isolated checkout: `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom-tapdb10-20260910`.
- Branch: `codex/bloom-tapdb-10-1-migration` from `948bc487415899eb50f024f2d421066a061f0a48` (`origin/jemdev10`, also the peeled `9.0.0` release commit).
- Original checkout `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom` is a different remote and has unrelated tracked and untracked changes. It is excluded from mutation.
- Live system inventory and deployed-source reconciliation remain pending under B01. Production is unchanged at ledger creation.
- Broad tests are intentionally deferred until application changes and focused checks are complete.

## Status protocol

Working states: `OPEN`, `IN_PROGRESS`, `ATTEMPTING_BUGFIX`. Terminal states: `SUCCESS`, `DUPLICATE`, `NO_LONGER_NEEDED`, `FAIL`, `BLOCKED`. A preservation failure or block prevents reopening Bloom.

## Control ledger

| ID | Area | Requirement and completion evidence | Owner | Status | Evidence / next action |
|---|---|---|---|---|---|
| B00 | Amendment | Record the bounded amendment, accepted prerelease, outage decision, existing-backup decision, execution limits, and immutable dependency identities. | Operator | SUCCESS | Decisions and Gate 0 baseline above. Initial ledger commit is the durable execution start. |
| B01 | Inventory | Reconcile live Bloom source, config, image, mounts, installed dependency, writers and actual data with Git while preserving unrelated dirty work. | Operator | OPEN | Refresh the one bounded live inventory; retain full sensitive evidence outside Git and commit only a sanitized summary/reference. |
| B02 | Implementation | Complete native TapDB API/config changes and the Bloom-specific conversion manifest and operator procedure. | Operator | OPEN | Inspect current source and actual data shapes; use public interfaces, explicit transactions/config, `set_cli_context`, `verify_existing`, non-overwriting template seed, and fail-hard validation. |
| B03 | Independent review | Review identity preservation, allocator conversion, conversion manifest, and runtime-principal procedure before production migration. | Reviewer | OPEN | Reviewer receives exact files, compact focused evidence, inputs, invariants and specific questions after B02 is ready. |
| B04 | Validation | Pass focused checks and the single designated broad Bloom run; record exact tested inputs and any informative rerun. | Operator | OPEN | Run focused checks during implementation, then one broad local or CI authority after changes settle. |
| B05 | Release/build | Restore `main` as primary/default; publish the annotated Bloom `10.0.0` major and build the one final image from the exact clean release commit. | Operator | IN_PROGRESS | GitHub default branch changed from `jemdev10` to `main` and verified through `gh repo view`; both names were at baseline commit `948bc487415899eb50f024f2d421066a061f0a48`. Merge reviewed release source through normal checks, create immutable GitHub release/tag, then use the Dayhoff service build and record release commit plus image digest. |
| B06 | Maintenance window | Stop all Bloom traffic/writers, capture frozen source/allocator/principal evidence, run released schema migration and reviewed Bloom conversion, then bind runtime access. | Operator | OPEN | No new backup artifacts. Use native receipts/fencing, inspect terminal native outcomes before any retry, and keep admission closed through B07. |
| B07 | Acceptance | Pass native identity/allocator verification and controlled application acceptance; independently review final migration and privilege receipts. | Operator / Reviewer | OPEN | Verify manifest-only transformations, prior sequence floors and future recovery floors, fresh-session privileges, authenticated workflow, embedded GUI, Bloom DAG v2, Kahlo behavior, and health/log stability. |
| B08 | Reopen/close | Reopen Bloom only after B07 succeeds, confirm health, close this ledger, and create the separate phase-2 backlog ledger. | Operator | OPEN | Preserve sibling services and shared infrastructure; use scoped Compose promotion only. |

## Data preservation contract

- Preserve stored UID/EUID, prefix, domain, issuer/tenant and creation identities, deleted records, audit history and authoritative lineage.
- Preserve historical prefix/template differences. Never regenerate an existing EUID from its current template.
- Retain BGX identities as assertion/provenance records with duplicate evidence. Add only verified canonical references and lineage; do not invent remote identities.
- Keep unresolved references explicit and deleted history deleted.
- Preserve all existing template rows. Add required templates with `overwrite=False` or its verified public equivalent.
- Repair missing native metadata envelopes only through reviewed public APIs. Reject malformed existing values. Archive retired graph metadata only after matching authoritative lineage.
- Do not hard-code observed production counts, paths, prefixes or audit-row expectations in Bloom runtime code.

## Sequence transition contract

- Verify a completed advancement against its prior plan floors. Newly reserved values become future recovery floors and do not trigger repeated advancement.
- The first resumed allocation must exceed stored values, source-next values, reservations and failed-attempt/recovery exposures, including dormant generators.
- Preserve increments, alignment, cache/bounds and ownership. Deduplicate only identical `(name, value, source)` records while retaining original receipts and journals.
- A parser or transport failure never justifies replaying a possibly committed migration. Inspect terminal native receipts and journals, then use native reconciliation for ambiguity.

## Change log

- 2026-09-11: Ledger created at execution start. B00 terminalized `SUCCESS`; B01-B08 remain ordered and open.
- 2026-09-11: User amended B05 to make `main` the primary/default branch again. GitHub default branch changed and verified; release implementation remains in progress.
