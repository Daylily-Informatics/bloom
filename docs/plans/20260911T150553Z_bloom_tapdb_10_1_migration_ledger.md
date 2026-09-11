# Bloom 10.0.0 / TapDB 10.1.1rc1 Migration Ledger

Date: 2026-09-11

Status: active execution ledger

## Decisions and immutable inputs

- This ledger replaces the earlier expanded migration process under the user-approved bounded amendment dated 2026-09-11.
- Bloom will release as breaking major `10.0.0` and use `daylily-tapdb[aurora,gui]==10.1.1rc1`.
- TapDB Git tag: annotated tag object `1ac2f09a1787b9e747eda582c45a628ca60b7020`, peeled commit `02ab7c9d0325dfcbf9dc47a03be66b62e0a22f2c`.
- TapDB package hashes: wheel SHA-256 `26de691dd5f9c8fac596a18119c9220f4ea78826094753b47f9eb936b0677ce7`; sdist SHA-256 `abf2e5b18184db736c8e54fb77cbc96e78c77921f0f65b7c8f026ebb20a8a5fb`.
- A sustained Bloom outage is accepted. The existing Aurora recovery arrangement is accepted. This execution creates no snapshot, dump, database copy, replacement database, or rehearsal database.
- One production migration is permitted. Preserve acknowledged work, existing data, EUIDs, allocator guarantees, audit history, deleted history, authoritative lineage, and queued Bloom work.
- Remove compatibility shims and fallback behavior. Minor features and outstanding pull-request integration remain phase 2 work after acceptance.
- Restore `main` as the GitHub default and primary branch. Release work targets `main`; after merge, align the local checkout and default upstream with `main`.
- Cost bounds: one final Bloom container build; one broad Bloom test/CI campaign with at most one informative rerun; focused checks only for changed behavior and demonstrated failures.
- Upstream coordination: an Atlas migration is preparing a separate TapDB feature release. Bloom keeps the accepted `10.1.1rc1` pin unless a concrete shared upstream gap is established. If Bloom encounters that gap, stop and wait for the published upstream release; do not patch TapDB, add a workaround, or start a second upstream implementation.

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
| B01 | Inventory | Reconcile live Bloom source, config, image, mounts, installed dependency, writers and actual data with Git while preserving unrelated dirty work. | Operator | SUCCESS | Live 2026-09-11 inventory: container `986deb9e6150`, image `sha256:e160422141c782400f7798b01f9157c2afc4431326629c8f6543d3785303f806`, source/tag `948bc487415899eb50f024f2d421066a061f0a48` / `9.0.0`, TapDB `9.0.10`, Meridian EUID `0.4.7`. The only application writable-layer file was `/app/config/tapdb_templates/bloom/templates.json`; SHA-256 `62d49351f312b8ac9396b615ad114d04cb600c7306ede4597a62484018fe7e2e` exactly matches Git. Logs are runtime artifacts. Explicit target is `tapdb_bloom_prod`, schema `tapdb_bloom_lsmcok1_local`, domain `M`; current role `dayhoff` has CREATEDB/CREATEROLE and effective database CREATE/TEMP. One Bloom application container is the only OS writer; no Bloom timers or user/root cron were found. Actual aggregate shape: 239 templates, 8,981 instances, 9,542 lineages, 60,808 audit rows, 950 historical prefix/template differences, 186 BGX identities (160 active, 26 deleted), 50 missing `properties` envelopes all under SYS, 93 retired graph payloads, and no malformed envelopes. Queue inventory has no open beta work; it retains 12 queue definitions and 18 completed leases. Protected host evidence: `/home/ubuntu/bloom_ops/tapdb101-20260911/`; summary SHA-256 values `8032d661...33373e9`, `9a2a6806...c6a808`, `8783eabd...2dda1b`. |
| B02 | Implementation | Complete native TapDB API/config changes and the Bloom-specific conversion manifest and operator procedure. | Operator | SUCCESS | Bloom native API/conversion/startup work and the B03-approved SOP are complete. All 186 BGX identities have explicit preservation dispositions; receipts, source contracts and allocator bindings are mandatory; startup verifies released templates without mutation. Kahlo `8.0.0` is source-released at commit `95fa29b1ed80c8361ed0187753fd687ef553a05c` with DAG v2 only (`12/12` focused tests); its image is not yet promoted. Dayhoff isolated commit `9efb64d` pins Bloom `10.0.0` and Kahlo `8.0.0`, preserves sibling targets, and emits Bloom's exact constrained runtime identity (`2/2` focused tests). The protected Bloom runtime secret reference is `arn:aws:secretsmanager:us-west-2:108782052779:secret:/dayhoff/lsmcok1/tapdb/bloom-runtime-10-c92DAH`; no secret value is recorded. |
| B03 | Independent review | Review identity preservation, allocator conversion, conversion manifest, and runtime-principal procedure before production migration. | Reviewer | SUCCESS | Terminal review approved exact commit `4ced8ca98874ef0235f8366f61dc9036166c5afc`: conversion `8f752375...5370d`, XRF setup `866a5156...618dd`, floor projector `e5baa9c3...be198`, sequence verifier `828c45f7...b84`, principal overlay `f6ad61d3...f6201`, native identity manifest `eea0327e...a52`, runtime verifier `9621aca1...9868`, and maintenance SOP `3640c97e...f8e0`. Review accepted BGX/context/deletion preservation, bounded metadata changes, complete template fingerprints, public CLI floor shape, prior/future sequence semantics, runtime identity/privileges, and scoped promotion. Actual production receipts remain B07 evidence. |
| B04 | Validation | Pass focused checks and the single designated broad Bloom run; record exact tested inputs and any informative rerun. | Operator | OPEN | Latest exact migration/startup/adapter selection passed `18/18` with coverage disabled: `tests/test_tapdb10_migration_contract.py`, `tests/test_container_entry_runtime.py`, and `tests/test_tapdb_adapter_compat.py`. The broader focused behavior selection previously passed `53/53` with coverage disabled; its prior same selection also passed all tests but exited because its intentionally narrow 35.16% repository coverage did not meet the broad 39% gate. Helper/startup ruff, byte-compilation and `git diff --check` passed. No broad run has occurred. |
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
- 2026-09-11: B01 completed from one bounded live inventory. Full receipts remain on the operator host; the committed row retains only the sanitized source, writer, privilege and data-shape summary.
- 2026-09-11: B02 moved to `ATTEMPTING_BUGFIX` from the first B03 review. Focused validation before the findings was `45 passed, 1 failed` for graph/beta behavior; the one failure was a stale mocked object-detail expectation and its exact test passed after adding the native-reference mock. The earlier repeatable-read failure was separately fixed and its exact case passed; no broad run occurred. Production is unchanged.
- 2026-09-11: Recorded Atlas/TapDB release coordination. No concrete Bloom upstream limitation is present; the accepted `10.1.1rc1` pin remains unchanged while Bloom-specific work continues.
- 2026-09-11: Completed the targeted B03 corrections and returned B02 from `ATTEMPTING_BUGFIX` to `IN_PROGRESS` pending reviewer acceptance. The stable maintenance SOP is `docs/plans/20260911T150553Z_bloom_tapdb_10_1_maintenance_sop.md`. Focused behavior was `53 passed`; helper/startup subset was `10 passed`; ruff, byte-compilation and `git diff --check` passed. The designated broad run and final image remain unused.
- 2026-09-11: Applied the final B03 command-shape and ordering corrections under `ATTEMPTING_BUGFIX`, then returned B02 to `IN_PROGRESS`: native floors JSON now contains only `floors`; projection provenance is a separate receipt; transition verification uses prior floors without re-merging new recovery-family reservations; all original template rows have complete stable fingerprints; admission closes before drain and stop; helpers use the exact operator venv; and the final container uses packaged verifier/config paths plus a private receipt transfer directory. The exact focused selection passed `18/18`; no TapDB upstream gap, broad run, image build or production mutation occurred.
- 2026-09-11: B03 terminalized `SUCCESS` against exact commit `4ced8ca98874ef0235f8366f61dc9036166c5afc` and the recorded helper/SOP hashes. This approves the source and procedure; B07 still owns independent review of actual migration and runtime privilege receipts.
- 2026-09-11: B02 terminalized `SUCCESS`. Kahlo `8.0.0` was published from the v2-only source commit and remains source-only until scoped image promotion. Dayhoff commit `9efb64d` adds only Bloom's runtime-principal config path plus Bloom/Kahlo pins; the new runtime secret ARN is retained as a protected reference, never its value. Sibling service identities and credentials are unchanged.
- 2026-09-11: Restricted Bloom CI push triggers to `main` while retaining pull-request checks against `main`. The release branch push therefore does not duplicate the single designated pull-request campaign; no checks were disabled.
