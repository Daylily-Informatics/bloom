# Bloom 10.0.1 / TapDB 10.1.3 Maintenance SOP

Date: 2026-09-11

Status: resumed post-schema review procedure

This is the bounded production procedure governed by the sibling migration ledger. It resumes the in-place migration of `tapdb_bloom_prod` from the committed TapDB `10.1.1rc1` schema checkpoint; it creates no Aurora snapshot, dump, database copy, replacement database, or rehearsal database. A preservation or allocator failure keeps Bloom stopped.

## Immutable target and operator capsule

- Bloom replacement release: annotated `10.0.1`, with final release commit and image digest recorded in the ledger before promotion.
- TapDB: `daylily-tapdb[aurora,gui]==10.1.3`; annotated tag object `c043426f8d1418c9a3220aa41195dcea3a3587b4`; peeled commit `7eccfe1b4e0dc440ed08b97f8decf214648152a5`; wheel SHA-256 `835743adc8c28456e8d733d136abe31e672e0188a33ded16a99d625a22c128e5`; sdist SHA-256 `eefebb8af42e7baba5b8517daea861933fc7c8135fc0791d7bcde7f8d5762cf5`.
- Target: client `bloom`, logical database `bloom-day`, physical database `tapdb_bloom_prod`, schema `tapdb_bloom_lsmcok1_local`, domain `M`, owner `bloom`.
- Runtime role: `bloom_runtime_10`. Operator and every managed sequence granted to runtime: `dayhoff`, as established by the Bloom principal/allocator census.
- Operator root: `/home/ubuntu/bloom_ops/tapdb101-20260911`; native journals: `/home/ubuntu/bloom_ops/tapdb101-20260911/journal`; ordinary outputs: `/home/ubuntu/bloom_ops/tapdb101-20260911/receipts`. Both directories are mode `0700`; files are mode `0600`.
- Operator config: `/home/ubuntu/bloom_ops/tapdb101-20260911/operator.yaml`.
- Control config: `/home/ubuntu/bloom_ops/tapdb101-20260911/control-operator.yaml`, using the same Aurora writer and operator identity but the existing `postgres` control database. It must resolve to a physical database different from `tapdb_bloom_prod`.
- Runtime config identity: `/home/ubuntu/.config/tapdb/bloom/bloom-day/tapdb-config.yaml`. This exact absolute path is present on the host and in the Bloom container. It contains runtime credentials only. The principal helper overlays operator credentials in memory while retaining this runtime config identity.
- Provider contract: `/home/ubuntu/bloom_ops/tapdb101-20260911/receipts/aurora-provider-contract.json`, pinned to authenticated RDS metadata for `dayhoff-lsmcok1-tapdb`, engine `aurora-postgresql`, engine version `16.13`, profile `lsmc`, region `us-west-2`, the exact cluster ARN/resource ID/writer endpoint, and `sslmode=verify-full`.
- Sequence mapping input: `/home/ubuntu/bloom_ops/tapdb101-20260911/receipts/source-sequence-mappings.json`. It contains only the four independently approved source-declared prefix mappings for the actual dormant `AY`, `WSX`, `WX` and `XX` catalog allocators, preserving their frozen catalog positions. No other mapping may be inferred or added during the outage.
- Conversion manifest: `config/migrations/bloom_tapdb_10_1_conversion.json` from the exact Bloom release commit.

Before the window, install the exact release scripts and manifest under the operator root, create and hash the private configs/provider contract/mapping input, verify the pinned wheel and release artifacts, and record those hashes in B06. Preparing these files does not touch the database. The runtime config is placed at its canonical path only while Bloom is stopped.

The commands below run in one retained interactive `ubuntu` bash login session. Define:

```bash
set -euo pipefail
ROOT=/home/ubuntu/bloom_ops/tapdb101-20260911
OUT="$ROOT/receipts"
JOURNAL="$ROOT/journal"
TAPDB="$ROOT/venv/bin/tapdb"
PYTHON="$ROOT/venv/bin/python"
OPERATOR="$ROOT/operator.yaml"
CONTROL="$ROOT/control-operator.yaml"
RUNTIME=/home/ubuntu/.config/tapdb/bloom/bloom-day/tapdb-config.yaml
PROVIDER="$OUT/aurora-provider-contract.json"
MAPPINGS="$OUT/source-sequence-mappings.json"
MANIFEST="$ROOT/release/config/migrations/bloom_tapdb_10_1_conversion.json"
REVIEW_REFERENCE='B03:<reviewed-commit-and-message>'
```

Every plan and result path below is create-exclusive. Preserve stdout, stderr, terminal return code, file SHA-256 and the native journal head for each operation on the operator host. Do not put secrets or complete data receipts in Git.

## 1. Recheck the closed outage; do not recapture the source

Admission is already closed, Bloom is stopped, and the frozen source/family capsule is terminal. Recheck only the scoped admission marker, Bloom Compose/process state, active database sessions and prepared transactions. Require ordinary admission closed, no Bloom container or process, no Bloom writer, and no unexpected session or prepared transaction. Preserve siblings and do not issue an application request. A distinct read-only census may be written to `$OUT/resume-principal-census.json`; never replace the frozen census or source receipts.

The governing frozen evidence is already complete:

- recovery family `d869afb8-47a7-41dd-813a-f24d0ca96fa8`;
- `$OUT/frozen-source-contract.json`, bound to physical `tapdb_bloom_prod`, all 66 allocators and the frozen Bloom population;
- `$OUT/source-sequence-mappings.json`, containing only the four reviewed source-declared prefix mappings for the actual dormant `AY`, `WSX`, `WX` and `XX` catalog allocators, with their retained catalog positions;
- `$OUT/frozen-source-next-plan.json`, `$OUT/transition-floors.json` and `$OUT/transition-floor-projection.json`; and
- the existing family journal, including every schema fence, reservation and recovery exposure.

Do not generate a new family ID. Do not recapture the source contract, source-next plan or transition floors. Do not rerun the source inventory, floor projector or committed schema operation. These receipts remain the only source/family inputs for the resumed delta.

## 2. Preserve the committed schema checkpoint and apply only the 10.1.3 delta

The original schema operation is terminal and must never be replayed. Its retained result is `$OUT/schema-result.json`, SHA-256 `2853a09db4cbf7ef5c561afc606d9dc1a9ef3677f05d7439dee05c19a07047a8`, with recovery completion `000008-20260911T193433Z`. It committed eight migrations and released its writer fence. Preserve that result, its journal and every recovery-family exposure.

With the exact `10.1.3` operator venv, plan a distinct delta operation against the current committed schema checkpoint, mappings and recovery family. Preserve `$OUT/frozen-source-contract.json` as the immutable pre-migration source record, but do not pass it as `--source-contract` for this delta: the native option requires exact equality with the live inventory, and the terminal eight-migration operation has already changed that inventory. The delta preflight captures the complete current identity and sequence inventories, requires their physical family membership, retains all family definitions and floors, and rechecks the complete receipt under the writer fence before apply. Keep the explicit 256 MiB inventory receipt limit in the operator config.

Capture the dry migration receipt with the current native inventories, exact mappings, family and journal. `db schema migrate` deliberately omits the unsupported global `--json` option.

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day \
  db schema migrate --dry-run \
  --receipt "$OUT/schema-delta-1013-plan.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipts-dir "$JOURNAL"
```

Require exactly these three pending migrations, in order, and reject any plan containing one of the already committed eight: `20260911_164426_runtime_tenant_allowlist.sql` (SHA-256 `50e936edee3f2ad11d4193e1f698809bc4e39b4370355e65f3f59b6c08ac40aa`), `20260911_171000_allowlisted_lineage_scope.sql` (SHA-256 `8ee9eff8eaa5b68e23354ebf3d87356fa6ccd4b865731c0e21c4e0ef06dccc1b`) and `20260911_210000_versioned_xrf_scope.sql` (SHA-256 `098566ee17de495944485dafdb6c86dddc57e968a4decff00808cbdf7b6a05fa`). Check the immutable target/physical target, current complete inventories, exact journal/family binding, 256 MiB inventory limit, zero pending recovery intents, no unknown migration, and no principal binding. Record the delta plan SHA-256. Apply only that unchanged receipt while native fencing independently authenticates the Aurora provider and leaves only the operator trusted during the commit:

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day \
  db schema migrate --apply \
  --preflight-receipt "$OUT/schema-delta-1013-plan.json" \
  --receipt "$OUT/schema-delta-1013-result.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipts-dir "$JOURNAL" \
  --establish-writer-fence \
  --control-config "$CONTROL" \
  --provider-contract "$PROVIDER"
```

Require native `migration_result`, terminal `recovery_completion`, `principal_binding_required=true`, and a released `writer_fence_release` before continuing. Bind the result to exactly the three reviewed migration SHA-256 values recorded in B03. The original and delta release values are retained future recovery evidence, not an instruction to rerun either migration. Any ambiguous result is reconciled from the native journal and terminal receipt; never replay the original eight or the delta apply.

## 3. Prepare XRF templates and convert Bloom data

Use the public packaged TapDB core definitions and `seed_templates(overwrite=False)` for owner `bloom`, matching the transaction owner of every XRF instance created by Bloom. The helper derives exact XRF coordinates from the installed package, verifies every loaded template fingerprint, preserves the historical `tapdb_object/1.0` definition and any core-owned package definitions unchanged, and additively inserts only missing Bloom-owned canonical `opaque/1.0` and `tapdb_object/2.0` definitions. It never overwrites or reactivates a loaded definition.

```bash
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_xrf_templates.py" plan \
  --operator-config "$OPERATOR" --manifest "$MANIFEST" \
  --actor bloom-tapdb10-migration --receipt "$OUT/xrf-template-plan.json"
XRF_PLAN_SHA='<sha256 of xrf-template-plan.json>'
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_xrf_templates.py" apply \
  --operator-config "$OPERATOR" --manifest "$MANIFEST" \
  --actor bloom-tapdb10-migration --plan "$OUT/xrf-template-plan.json" \
  --reviewed-plan-sha256 "$XRF_PLAN_SHA" --review-reference "$REVIEW_REFERENCE" \
  --receipt "$OUT/xrf-template-result.json"
```

Capture the post-schema/post-template native identity baseline used to prove only Bloom conversion changes:

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db identity inventory --source-version 10.1.3 \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipt "$OUT/pre-bloom-conversion.json"
```

Plan and apply the reviewed Bloom conversion. The plan must report exactly 186 retained BGX identities: 182 Atlas, one Dewey and three unresolved/orphan; 160 active and 26 deleted. It must retain every legacy BGX UID/EUID, lineage, deletion state, original properties and duplicate evidence; the actual 26 duplicate groups have identical properties and mixed active/deleted evidence. It must repair 50 missing SYS envelopes and inspect all 93 rows containing 393 retired graph entries. Archive only the 111 entries on 21 rows that exactly match same-source authoritative BGX lineage by root, relationship, tenant and source field. Keep the 282 unmatched entries on 72 rows unchanged and explicit in their original metadata and relative order; create no identity or lineage for them. Mixed and empty graph rows must both be zero. Archived entries retain their original position and list length for reconstruction. The plan creates exactly 157 reviewed canonical native assertion groups. Any differing duplicate provenance, graph disposition, unresolved identity invention, deleted-source activation or unexpected count stops the operation.

```bash
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_conversion.py" plan \
  --operator-config "$OPERATOR" \
  --source-contract "$OUT/frozen-source-contract.json" \
  --manifest "$MANIFEST" --actor bloom-tapdb10-migration \
  --receipt "$OUT/conversion-plan.json"
CONVERSION_PLAN_SHA='<sha256 of conversion-plan.json>'
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_conversion.py" apply \
  --operator-config "$OPERATOR" \
  --source-contract "$OUT/frozen-source-contract.json" \
  --manifest "$MANIFEST" --actor bloom-tapdb10-migration \
  --plan "$OUT/conversion-plan.json" \
  --reviewed-plan-sha256 "$CONVERSION_PLAN_SHA" \
  --review-reference "$REVIEW_REFERENCE" \
  --receipt "$OUT/conversion-result.json"
```

Both helpers reserve the exact result path before mutation and atomically replace it with the terminal result. If a post-commit transport or result-write failure leaves the reservation, run that helper's `reconcile` operation with the same plan SHA and review reference. Reconciliation is read-only, validates the reviewed metadata/template state, all BGX preservation evidence and the exact native assertion set, and finalizes the reserved receipt. Never blind-replay an apply.

Capture and verify the final identity state for this conversion stage:

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db identity inventory --source-version 10.1.3 \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipt "$OUT/post-bloom-conversion.json"
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_identity_manifest.py" \
  --before "$OUT/pre-bloom-conversion.json" \
  --after "$OUT/post-bloom-conversion.json" \
  --conversion-plan "$OUT/conversion-plan.json" \
  --manifest "$OUT/native-bloom-conversion-manifest.json"
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db identity verify --before "$OUT/pre-bloom-conversion.json" \
  --after "$OUT/post-bloom-conversion.json" \
  --conversion-manifest "$OUT/native-bloom-conversion-manifest.json" \
  --sequence-mappings "$MAPPINGS"
```

The generated native manifest permits added rows only in `generic_instance`, `generic_instance_lineage` and `audit_log`, and exact per-row value hashes only for reviewed metadata-change instances. It refuses changed immutable identities, removed rows, new tables, or changes to other original rows. The released TapDB schema result owns the preceding schema-stage physical preservation proof; the XRF helper separately proves existing templates unchanged.

## 4. Advance and verify every allocator once

Build the transition plan from the already frozen source-next floors. The recovery family also includes any retained failed-attempt/fence exposures.

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db sequences advance --floors "$OUT/transition-floors.json" \
  --receipt "$OUT/sequence-plan.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json"
SEQUENCE_PLAN_SHA='<sha256 of sequence-plan.json>'
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db sequences advance --apply \
  --floors "$OUT/transition-floors.json" \
  --preflight-receipt "$OUT/sequence-plan.json" \
  --receipt "$OUT/sequence-result.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipts-dir "$JOURNAL" \
  --establish-writer-fence --control-config "$CONTROL" \
  --provider-contract "$PROVIDER"
"$PYTHON" "$ROOT/release/scripts/bloom_sequence_transition_receipt.py" \
  --plan "$OUT/sequence-plan.json" --result "$OUT/sequence-result.json" \
  --recovery-family "$OUT/recovery-family.json" \
  --prior-floors "$OUT/sequence-prior-floors.json" \
  --future-floors "$OUT/sequence-future-floors.json" \
  --receipt "$OUT/sequence-transition-verified.json" \
  --review-reference "$REVIEW_REFERENCE"
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db sequences verify --floors "$OUT/sequence-prior-floors.json" \
  --sequence-mappings "$MAPPINGS"
```

The Bloom verifier runs immediately after apply and binds the plan, result inventory, fence release, exact configured target and physical target, and terminal recovery family. It verifies completion against the plan's prior floors and emits the separate prior/future files. The native verification then uses only `sequence-prior-floors.json`, without merging the recovery family that now contains the transition's new reservations. The result's newly reserved next values are retained as future recovery floors; they do not cause another advance. The first later allocation must exceed every applicable stored, allocated, source-next, reservation and family exposure while preserving increment, alignment, cache, bounds and ownership.

If the native command or transport fails after an intent may have been written, inspect its terminal result and journal first. Do not repeat the plan. Use `tapdb db sequences reconcile` with the exact control config, journal, provider contract, mapping file, recovery family and latest fence/release intent; create and independently inspect its preflight receipt before `--apply`. Continue only after the native family has no pending operation and the target is safely released or deliberately remains closed.

## 5. Bind the constrained runtime identity

Install the reviewed runtime-only config at its exact canonical path. The operator config remains outside the container. Plan/apply bootstrap, then plan/apply the final binding through the Bloom helper. The helper keeps `config_identity` equal to the runtime path while overlaying the operator credentials only in memory; runtime and operator target fields must otherwise be identical.

```bash
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bootstrap-plan \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bootstrap-plan.json"
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bootstrap-apply \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bootstrap-plan.json" \
  --review-reference "$REVIEW_REFERENCE"
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bind-plan \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bind-plan.json"
"$PYTHON" "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bind-apply \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bind-plan.json" \
  --review-reference "$REVIEW_REFERENCE"
```

Require every managed sequence granted to runtime to remain owned by the configured `operator_user=dayhoff`. Do not change unrelated object ownership or operator access.

## 6. Controlled start and acceptance

Before promotion, read the then-current complete Dayhoff release manifest once. Merge only the selected final Bloom digest and any reviewed Kahlo digest/config into that current manifest; refuse a concurrent manifest change between comparison and write. Preserve every sibling image/config identity. Use scoped Compose pull/deploy commands with `--no-deps` and `--pull never`; do not restart the full stack.

Start the final Bloom image with external admission still closed. Bloom's container entrypoint initializes the exact TapDB CLI context, then executes `_verify_existing_tapdb`: it loads the released Bloom template requirements plus the two core XRF templates and calls public `require_seeded_templates` through a runtime-scoped connection. It creates or seeds nothing. The pinned TapDB GUI factory also receives the exact config path; schema migration, XRF preparation and principal setup remain operator-only steps.

Run the fresh-session privilege verifier from the final container environment. The final image packages the verifier at `/app/scripts/bloom_tapdb10_runtime_verify.py` and the manifest at `/app/config/migrations/bloom_tapdb_10_1_conversion.json`. Use a private transfer directory within the already-mounted host config tree; never mount the operator root/config into the runtime container.

```bash
install -d -m 0700 /home/ubuntu/.config/bloom-day/migration-receipts
docker exec dayhoff-day-bloom-1 python /app/scripts/bloom_tapdb10_runtime_verify.py \
  --runtime-config /home/ubuntu/.config/tapdb/bloom/bloom-day/tapdb-config.yaml \
  --manifest /app/config/migrations/bloom_tapdb_10_1_conversion.json \
  --receipt /home/ubuntu/.config/bloom-day/migration-receipts/runtime-verification.json
mv /home/ubuntu/.config/bloom-day/migration-receipts/runtime-verification.json \
  "$OUT/runtime-verification.json"
```

It requires Bloom `10.0.1` and TapDB `10.1.3`, two consecutive scoped transactions, recovery after intentional rollback, the exact runtime login/config/domain/owner/global scope, template SELECT, required instance/lineage DML, sequence USAGE+SELECT with UPDATE denied and exact operator ownership, database TEMP/CREATE denied, schema CREATE denied, and no SUPERUSER/BYPASSRLS/CREATEDB/CREATEROLE/REPLICATION/INHERIT.

With ordinary admission still closed, perform one authenticated application acceptance: login; one read/write/replay workflow; embedded GUI; Bloom DAG v2; and required Kahlo graph behavior without DAG v1 fallback. Confirm the replay preserves full migrated fulfillment properties and migration provenance. Capture allocator positions after the controlled write as additional future recovery exposures. Confirm a brief stable health/log interval without migration-related errors.

Send the compact native identity/sequence transition receipts, runtime privilege receipt, controlled workflow result and health evidence to B07 independent review. Reopen ordinary Bloom traffic only after B07 succeeds. If acceptance fails, keep admission closed and repair the specific defect. Once new production writes are admitted, repair forward. Any exceptional Aurora restore is a separate target-specific decision and must retain acknowledged work plus every recorded allocator exposure without rewinding sibling services.
