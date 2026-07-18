# Bjuice Atlas/Bloom Templates and Backfill Ledger

Created: 2026-07-18T04:48:45Z

## Scope

Complete the Atlas and Bloom owning-service support needed for the Bjuice hybrid
backfill. Atlas and Bloom source changes are isolated on `jem-260717-fb`.
Production data work uses supported owning-service APIs only. Template changes are
additive and file-backed before synchronization. No TapDB schema change, direct
SQL, Aurora infrastructure mutation, destructive template replacement, or
invented Meridian EUID is permitted.

## Gate 0 Baseline

- Atlas: `/Users/jmajor/projects/mega_dayhoff/repos_work/lsmc-atlas`, branch
  created from `52e258e5c60f57ae1e90b895364166cd3b358faa`; pre-existing dirty files
  were preserved.
- Bloom: `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom`, branch created
  from `856f92186a04ba91cf1ba3d825d0522d9ca97c32`; pre-existing dirty files and
  generated output were preserved.
- TapDB: `/Users/jmajor/projects/mega_dayhoff/repos_work/daylily-tapdb`, branch
  `jem-dev` at `19f92ee176d708a42c48865fab44fc2ca59febf4`, behind its remote and
  already dirty. This lane creates GitHub issues only; it does not modify the
  checkout.
- Existing Bloom source already defines NovaSeq 6000 and MinION equipment
  templates. These must be reused, not duplicated.
- The authoritative ILMN SampleSheet contains 21 unique i7/i5 pairs: 20 samples
  and one NTC.

## Approvals Recorded

- Additive Atlas and Bloom source changes on `jem-260717-fb`: approved by user.
- Additive file-backed Bloom template creation/synchronization: approved by user.
- ILMN and ONT index/barcode record creation for the reviewed backfill: approved
  by user.
- Existing run-set/equipment lineage correction: approved only where the current
  edge is proven incorrect and an exact forward/rollback manifest is produced.
- Destructive template replacement, hard delete, schema change, direct SQL, and
  unrelated service deployment remain prohibited.

## Control Ledger

| ID | Area | Requirement | Status | Category | Gate | Owner | Evidence / terminal note |
|---|---|---|---|---|---|---|---|
| BASE-01 | Orchestration | Freeze repos, dirty state, branches, and live mutation boundary | SUCCESS | plan_amendment | Gate 0 | Agent 0 | Baselines above; feature branches created without stashing or resetting. |
| ATL-01 | Atlas | Add correct public Family contracts using Atlas-owned records and lineage | IN_PROGRESS | feature_implementation | Gate 1 | Agent 1 | Source audit in progress. |
| ATL-02 | Atlas | Add correct public CollectionEvent contracts and tests | IN_PROGRESS | feature_implementation | Gate 1 | Agent 1 | Source audit in progress. |
| IDX-01 | Bloom | Represent 21 ILMN i7/i5 assignments using real Bloom objects and lineage | SUCCESS | feature_implementation | Gate 1 | Agent 2 | One persisted sequencing-index object per pair; `uses_index` remains authoritative; generated SampleSheet now emits `index` and `index2`. |
| IDX-02 | Bloom | Represent ONT barcode identities at minimum by exact `barcodeNN` labels | SUCCESS | feature_implementation | Gate 1 | Agent 2 | Deterministic create-only manifest covers `barcode01` through `barcode16`; unknown sequences remain blank with `sequence_known=false`. |
| EQP-01 | Bloom | Reuse existing NovaSeq 6000 and MinION templates | SUCCESS | contract_test | Gate 1 | Agent 3 | Existing `1.0` templates preserved; corrected `1.1` successors are additive. |
| EQP-02 | Bloom | Add generic, NovaSeq X Series, PromethION, Ultima, and PacBio templates | SUCCESS | feature_implementation | Gate 1 | Agent 3 | Twelve-key catalog is file-backed and production validation passed without collisions. |
| EQP-03 | Bloom | Use shared equipment instance prefix for every new equipment template | SUCCESS | contract_test | Gate 1 | Agent 3 | All twelve templates use shared prefix `BEQ`; contract test enforces it. |
| TDB-01 | TapDB | Create issue for repository-backed backup of GUI/API-created templates and prefixes | SUCCESS | feature_implementation | Gate 1 | Agent 4 | https://github.com/Daylily-Informatics/daylily-tapdb/issues/90 |
| TDB-02 | TapDB | Create issue for formal CLI/API/GUI backup and recovery, tagging Josh Durham | SUCCESS | feature_implementation | Gate 1 | Agent 4 | https://github.com/Daylily-Informatics/daylily-tapdb/issues/89 tags `@jdurham38` in the requested fix. |
| MAN-01 | Data | Generate exact owning-service create/reuse/update manifest with checksums | SUCCESS | active_product_contract | Gate 2 | Agent 0 | Deterministic Bloom manifests: 21 ILMN pairs, 16 ONT barcodes, 2 equipment instances, 12 templates; create-only, checksummed, no invented EUIDs. Atlas write rows remain dependent on the new API deployment. |
| MAN-02 | Data | Generate exact incorrect equipment-lineage repair and rollback manifest | BLOCKED | active_product_contract | Gate 2 | Agent 0 | Read-only audit and forward/rollback skeletons exist; executable operations remain empty until real run-set/equipment EUIDs and current edges are retrieved. No correction is guessed. |
| LIVE-01 | Bloom | Synchronize additive templates through supported Bloom/TapDB CLI | OPEN | active_product_contract | Gate 3 | Agent 0 | Must pass collision preflight; no overwrite. |
| LIVE-02 | Backfill | Create reviewed Atlas/Bloom objects and lineages through supported APIs | OPEN | active_product_contract | Gate 3 | Agent 0 | Must retain returned EUIDs and payload hashes. |
| TEST-01 | Atlas | Focused Family and CollectionEvent API/domain/repository tests pass | OPEN | contract_test | Gate 4 | Agent 0 | Pending implementation. |
| TEST-02 | Bloom | Template, index, barcode, object creation, and lineage tests pass | SUCCESS | contract_test | Gate 4 | Agent 0 | `13 passed`; Ruff, JSON parsing, and `git diff --check` pass. Full DB-backed API lane is classified correctly but local TapDB bootstrap is unavailable on port 5566. |
| REL-01 | Source | Commit and push Atlas `jem-260717-fb` | OPEN | feature_implementation | Gate 5 | Agent 0 | Stage only request-owned files. |
| REL-02 | Source | Commit and push Bloom `jem-260717-fb` | OPEN | feature_implementation | Gate 5 | Agent 0 | Stage only request-owned files. |

## Owning-Service Write Manifest Gate

The gate is unblocked for generation and review. It is not yet satisfied for live
apply. The final manifest must separate:

1. Existing object/template reuse.
2. Additive template creation with exact category/type/subtype/version and payload
   hash.
3. Additive instance and lineage creation with idempotency keys.
4. Existing-edge corrections with exact before state and rollback operations.
5. Blocked ambiguity; no guessed EUID, model, barcode sequence, or relationship.

## Evidence Directory

`docs/plans/20260718T044845Z_bjuice_atlas_bloom_templates_backfill_artifacts/`
