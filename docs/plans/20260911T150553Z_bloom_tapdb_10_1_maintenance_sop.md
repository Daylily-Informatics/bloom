# Bloom 10.0.0 / TapDB 10.1.1rc1 Maintenance SOP

Date: 2026-09-11

Status: pre-migration review procedure

This is the bounded production procedure governed by the sibling migration ledger. It performs one in-place migration of `tapdb_bloom_prod`; it creates no Aurora snapshot, dump, database copy, replacement database, or rehearsal database. A preservation or allocator failure keeps Bloom stopped.

## Immutable target and operator capsule

- Bloom release: annotated `10.0.0`, final release commit and image digest recorded in the ledger before the outage.
- TapDB: `daylily-tapdb[aurora,gui]==10.1.1rc1`; annotated tag object `1ac2f09a1787b9e747eda582c45a628ca60b7020`; peeled commit `02ab7c9d0325dfcbf9dc47a03be66b62e0a22f2c`; wheel SHA-256 `26de691dd5f9c8fac596a18119c9220f4ea78826094753b47f9eb936b0677ce7`.
- Target: client `bloom`, logical database `bloom-day`, physical database `tapdb_bloom_prod`, schema `tapdb_bloom_lsmcok1_local`, domain `M`, owner `bloom`.
- Runtime role: `bloom_runtime_10`. Operator and every managed sequence granted to runtime: `dayhoff`, as established by the Bloom principal/allocator census.
- Operator root: `/home/ubuntu/bloom_ops/tapdb101-20260911`; native journals: `/home/ubuntu/bloom_ops/tapdb101-20260911/journal`; ordinary outputs: `/home/ubuntu/bloom_ops/tapdb101-20260911/receipts`. Both directories are mode `0700`; files are mode `0600`.
- Operator config: `/home/ubuntu/bloom_ops/tapdb101-20260911/operator.yaml`.
- Control config: `/home/ubuntu/bloom_ops/tapdb101-20260911/control-operator.yaml`, using the same Aurora writer and operator identity but the existing `postgres` control database. It must resolve to a physical database different from `tapdb_bloom_prod`.
- Runtime config identity: `/home/ubuntu/.config/tapdb/bloom/bloom-day/tapdb-config.yaml`. This exact absolute path is present on the host and in the Bloom container. It contains runtime credentials only. The principal helper overlays operator credentials in memory while retaining this runtime config identity.
- Provider contract: `/home/ubuntu/bloom_ops/tapdb101-20260911/receipts/aurora-provider-contract.json`, pinned to authenticated RDS metadata for `dayhoff-lsmcok1-tapdb`, engine `aurora-postgresql`, engine version `16.13`, profile `lsmc`, region `us-west-2`, the exact cluster ARN/resource ID/writer endpoint, and `sslmode=verify-full`.
- Sequence mapping input: `/home/ubuntu/bloom_ops/tapdb101-20260911/receipts/source-sequence-mappings.json`. Its reviewed initial value is `{}` because native catalog ownership, stored rows, template bindings and prefix configuration own the mappings. Any `unmapped` generator in the frozen source inventory is a preservation blocker; do not infer a mapping during the outage.
- Conversion manifest: `config/migrations/bloom_tapdb_10_1_conversion.json` from the exact Bloom release commit.

Before the window, install the exact release scripts and manifest under the operator root, create and hash the private configs/provider contract/mapping input, verify the pinned wheel and release artifacts, and record those hashes in B06. Preparing these files does not touch the database. The runtime config is placed at its canonical path only while Bloom is stopped.

The commands below run in one retained interactive `ubuntu` bash login session. Define:

```bash
set -euo pipefail
ROOT=/home/ubuntu/bloom_ops/tapdb101-20260911
OUT="$ROOT/receipts"
JOURNAL="$ROOT/journal"
TAPDB="$ROOT/venv/bin/tapdb"
OPERATOR="$ROOT/operator.yaml"
CONTROL="$ROOT/control-operator.yaml"
RUNTIME=/home/ubuntu/.config/tapdb/bloom/bloom-day/tapdb-config.yaml
PROVIDER="$OUT/aurora-provider-contract.json"
MAPPINGS="$OUT/source-sequence-mappings.json"
MANIFEST="$ROOT/release/config/migrations/bloom_tapdb_10_1_conversion.json"
REVIEW_REFERENCE='B03:<reviewed-commit-and-message>'
```

Every plan and result path below is create-exclusive. Preserve stdout, stderr, terminal return code, file SHA-256 and the native journal head for each operation on the operator host. Do not put secrets or complete data receipts in Git.

## 1. Close admission and freeze the source

1. Close ordinary Bloom admission, stop the scoped Bloom Compose service, and leave all sibling services running. Stop its web process, in-container workers and schedulers together. Confirm no Bloom process remains. The B01 host inventory found no separate Bloom timer or cron; if the frozen check finds one, stop it before continuing.
2. Drain acknowledged work before stopping. Retain queued work. Capture a final queue-state summary and require no running/leased/unacknowledged item; queued items may remain. Do not issue test GETs while draining because Bloom GET routes can write.
3. Close operator sessions other than the one retained maintenance session. Capture the exact principal census and database activity. Require no session or prepared transaction other than the retained operator operation.

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db census --database tapdb_bloom_prod --receipt "$OUT/frozen-principal-census.json"
```

4. Generate one recovery-family UUID and record it before the native capture. Capture the complete frozen source contract and immutable family in one native read-only operation.

```bash
FAMILY_ID='<one recorded lowercase UUID>'
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db identity inventory --source-version 9.0.10 \
  --sequence-mappings "$MAPPINGS" \
  --new-recovery-family-id "$FAMILY_ID" \
  --family-receipts-dir "$JOURNAL" \
  --family-receipt "$OUT/recovery-family.json" \
  --receipt "$OUT/frozen-source-contract.json"
```

Require the source contract target and physical target to match the immutable target, require all 66 observed generators to have a native `owned_column` or `prefix` mapping, and require no missing generator. Capture a dry native source-next plan; this does not advance an allocator.

```bash
cat >"$OUT/no-external-floors.json" <<'JSON'
{"floors":[]}
JSON
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db sequences advance --floors "$OUT/no-external-floors.json" \
  --receipt "$OUT/frozen-source-next-plan.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json"
python "$ROOT/release/scripts/bloom_sequence_floor_prepare.py" \
  --source-contract "$OUT/frozen-source-contract.json" \
  --source-next-plan "$OUT/frozen-source-next-plan.json" \
  --recovery-family "$OUT/recovery-family.json" \
  --floors "$OUT/transition-floors.json"
```

The projector validates the native plan against the frozen contract/family. It retains stored, allocated, source-next and family exposures and deduplicates only identical `(name, value, source)` records.

## 2. Apply the released schema migration

Capture the dry migration receipt with the native source contract, exact mappings, family and journal. `db schema migrate` deliberately omits the unsupported global `--json` option.

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day \
  db schema migrate --dry-run \
  --receipt "$OUT/schema-plan.json" \
  --source-contract "$OUT/frozen-source-contract.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipts-dir "$JOURNAL"
```

Check that the plan has the immutable target/physical target, exact source-contract and journal/family bindings, no unknown migration, and no principal binding. Record its SHA-256. Apply only that unchanged receipt while native fencing independently authenticates the Aurora provider and leaves only the operator trusted during the commit:

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day \
  db schema migrate --apply \
  --preflight-receipt "$OUT/schema-plan.json" \
  --receipt "$OUT/schema-result.json" \
  --source-contract "$OUT/frozen-source-contract.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipts-dir "$JOURNAL" \
  --establish-writer-fence \
  --control-config "$CONTROL" \
  --provider-contract "$PROVIDER"
```

Require native `migration_result`, terminal `recovery_completion`, `principal_binding_required=true`, and a released `writer_fence_release` before continuing. The release values are future recovery evidence, not an instruction to rerun the migration.

## 3. Prepare XRF templates and convert Bloom data

Use the public packaged TapDB core definitions and `seed_templates(overwrite=False)`. The helper verifies every existing template fingerprint and inserts only a missing exact opaque/tapdb-object XRF template.

```bash
python "$ROOT/release/scripts/bloom_tapdb10_xrf_templates.py" plan \
  --operator-config "$OPERATOR" --manifest "$MANIFEST" \
  --actor bloom-tapdb10-migration --receipt "$OUT/xrf-template-plan.json"
XRF_PLAN_SHA='<sha256 of xrf-template-plan.json>'
python "$ROOT/release/scripts/bloom_tapdb10_xrf_templates.py" apply \
  --operator-config "$OPERATOR" --manifest "$MANIFEST" \
  --actor bloom-tapdb10-migration --plan "$OUT/xrf-template-plan.json" \
  --reviewed-plan-sha256 "$XRF_PLAN_SHA" --review-reference "$REVIEW_REFERENCE" \
  --receipt "$OUT/xrf-template-result.json"
```

Capture the post-schema/post-template native identity baseline used to prove only Bloom conversion changes:

```bash
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db identity inventory --source-version 10.1.1rc1 \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipt "$OUT/pre-bloom-conversion.json"
```

Plan and apply the reviewed Bloom conversion. The plan must report exactly 186 retained BGX identities: 182 Atlas, one Dewey and three unresolved/orphan; 160 active and 26 deleted. It must retain every legacy BGX UID/EUID, lineage, deletion state, original properties and duplicate evidence; the actual 26 duplicate groups have identical properties and mixed active/deleted evidence. It must repair 50 missing SYS envelopes, archive 93 explicitly matched graph payloads, and create only the reviewed canonical native assertion set. Any differing duplicate provenance, unresolved identity invention, deleted-source activation or unexpected count stops the operation.

```bash
python "$ROOT/release/scripts/bloom_tapdb10_conversion.py" plan \
  --operator-config "$OPERATOR" \
  --source-contract "$OUT/frozen-source-contract.json" \
  --manifest "$MANIFEST" --actor bloom-tapdb10-migration \
  --receipt "$OUT/conversion-plan.json"
CONVERSION_PLAN_SHA='<sha256 of conversion-plan.json>'
python "$ROOT/release/scripts/bloom_tapdb10_conversion.py" apply \
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
  db identity inventory --source-version 10.1.1rc1 \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json" \
  --receipt "$OUT/post-bloom-conversion.json"
python "$ROOT/release/scripts/bloom_tapdb10_identity_manifest.py" \
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
"$TAPDB" --config "$OPERATOR" --client-id bloom --database-name bloom-day --json \
  db sequences verify --floors "$OUT/transition-floors.json" \
  --sequence-mappings "$MAPPINGS" \
  --recovery-family "$OUT/recovery-family.json"
python "$ROOT/release/scripts/bloom_sequence_transition_receipt.py" \
  --plan "$OUT/sequence-plan.json" --result "$OUT/sequence-result.json" \
  --recovery-family "$OUT/recovery-family.json" \
  --prior-floors "$OUT/sequence-prior-floors.json" \
  --future-floors "$OUT/sequence-future-floors.json" \
  --receipt "$OUT/sequence-transition-verified.json" \
  --review-reference "$REVIEW_REFERENCE"
```

The verifier binds the plan, result inventory, fence release, exact configured target and physical target, and terminal recovery family. It verifies completion against the plan's prior floors. The result's newly reserved next values are retained as future recovery floors; they do not cause another advance. The first later allocation must exceed every applicable stored, allocated, source-next, reservation and family exposure while preserving increment, alignment, cache, bounds and ownership.

If the native command or transport fails after an intent may have been written, inspect its terminal result and journal first. Do not repeat the plan. Use `tapdb db sequences reconcile` with the exact control config, journal, provider contract, mapping file, recovery family and latest fence/release intent; create and independently inspect its preflight receipt before `--apply`. Continue only after the native family has no pending operation and the target is safely released or deliberately remains closed.

## 5. Bind the constrained runtime identity

Install the reviewed runtime-only config at its exact canonical path. The operator config remains outside the container. Plan/apply bootstrap, then plan/apply the final binding through the Bloom helper. The helper keeps `config_identity` equal to the runtime path while overlaying the operator credentials only in memory; runtime and operator target fields must otherwise be identical.

```bash
python "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bootstrap-plan \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bootstrap-plan.json"
python "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bootstrap-apply \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bootstrap-plan.json" \
  --review-reference "$REVIEW_REFERENCE"
python "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bind-plan \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bind-plan.json"
python "$ROOT/release/scripts/bloom_tapdb10_principal_prepare.py" bind-apply \
  --runtime-config "$RUNTIME" --operator-config "$OPERATOR" \
  --manifest "$MANIFEST" --receipt "$OUT/runtime-bind-plan.json" \
  --review-reference "$REVIEW_REFERENCE"
```

Require every managed sequence granted to runtime to remain owned by the configured `operator_user=dayhoff`. Do not change unrelated object ownership or operator access.

## 6. Controlled start and acceptance

Before promotion, read the then-current complete Dayhoff release manifest once. Merge only the selected final Bloom digest and any reviewed Kahlo digest/config into that current manifest; refuse a concurrent manifest change between comparison and write. Preserve every sibling image/config identity. Use scoped Compose pull/deploy commands with `--no-deps` and `--pull never`; do not restart the full stack.

Start the final Bloom image with external admission still closed. Bloom's container entrypoint initializes the exact TapDB CLI context, then executes `_verify_existing_tapdb`: it loads the released Bloom template requirements plus the two core XRF templates and calls public `require_seeded_templates` through a runtime-scoped connection. It creates or seeds nothing. The pinned TapDB GUI factory also receives the exact config path; schema migration, XRF preparation and principal setup remain operator-only steps.

Run the fresh-session privilege verifier from the final container environment:

```bash
python "$ROOT/release/scripts/bloom_tapdb10_runtime_verify.py" \
  --runtime-config "$RUNTIME" --manifest "$MANIFEST" \
  --receipt "$OUT/runtime-verification.json"
```

It requires Bloom `10.0.0` and TapDB `10.1.1rc1`, two consecutive scoped transactions, recovery after intentional rollback, the exact runtime login/config/domain/owner/global scope, template SELECT, required instance/lineage DML, sequence USAGE+SELECT with UPDATE denied and exact operator ownership, database TEMP/CREATE denied, schema CREATE denied, and no SUPERUSER/BYPASSRLS/CREATEDB/CREATEROLE/REPLICATION/INHERIT.

With ordinary admission still closed, perform one authenticated application acceptance: login; one read/write/replay workflow; embedded GUI; Bloom DAG v2; and required Kahlo graph behavior without DAG v1 fallback. Confirm the replay preserves full migrated fulfillment properties and migration provenance. Capture allocator positions after the controlled write as additional future recovery exposures. Confirm a brief stable health/log interval without migration-related errors.

Send the compact native identity/sequence transition receipts, runtime privilege receipt, controlled workflow result and health evidence to B07 independent review. Reopen ordinary Bloom traffic only after B07 succeeds. If acceptance fails, keep admission closed and repair the specific defect. Once new production writes are admitted, repair forward. Any exceptional Aurora restore is a separate target-specific decision and must retain acknowledged work plus every recorded allocator exposure without rewinding sibling services.
