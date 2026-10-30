# Bloom 10.0.8 selected-image deployment preparation

Prepared 2026-09-18T18:47:35Z by Agent C under root's bounded documentation/helper assignment. Controlling work remains BL3 in [the Bloom owner ledger](20260918T135200Z_campaign_owner_contract_ledger.md) and R1/I1 in the master Ursa/OWY/Kahlo ledger. This creates no separate deployment queue. Root remains the Bloom application/release owner and the only deployment operator.

## Exact scope

| Identity | Retained baseline | Selected target |
|---|---|---|
| Bloom source tag | `10.0.6` | `10.0.8` |
| Git commit | `a67dee5dab4a2466f4534535b720f9560f261b6e` | `1c500a71b04f185099b9b4ec38534554e60da41a` |
| ECR image digest | `sha256:590a8af40c0412c5e8d24c390597be253f12ac20642429ec4e338cd0b8ff2df2` | `sha256:320ffb3e1de15991636b22f67df9a69dc63b2e05474f0a930628f84e07087f31` |

Registry/repository: `108782052779.dkr.ecr.us-west-2.amazonaws.com/dayhoff/day/bloom`. Selected instance: `i-07df3a933e4839f52`, region `us-west-2`. The final image already has a build receipt at `/home/ubuntu/bloom-10.0.8-20260918T175242Z/image-receipt.json`; this helper never builds or pulls it. Root reported Bloom stopped in the native TapDB migration session; this preparation did not independently observe or mutate runtime.

The helper is [20260918T184735Z_deploy_bloom1008_image.py](20260918T184735Z_deploy_bloom1008_image.py). It adapts Ursa's `20260918T064000Z_deploy_repair_image.py` selected-service pattern and consumes the actual `ursa-owy-kahlo.final-image/v1` schema emitted by root's `20260918T175000Z_build_bloom_final_image.py`.

## Native migration gate

Root must first review the actual terminal result and operation receipt from `20260918T183600Z_apply_bloom_authorization_migration.py`:

- Result: `/home/ubuntu/bloom_ops/kahlo-resolver-20260918T123300Z/native-apply-10.1.6-20260918T183600Z.json`.
- Operation: the same stem with `-operation.json`; return code must be zero, result must exist, and Bloom must remain stopped for review.
- Maintenance boundary: the same stem with `-maintenance.json`; the helper binds the stopped Bloom container ID and restart count to this record.
- Accepted preflight: `native-preview-10.1.6-20260918T181750Z.json`, SHA256 `b36758e02a16b44fed1b08b5f620eb5e6683e8bdb046268709ca3d974cf6c763`.
- Only migration: `20260918_070400_system_user_authorization_contract.sql`, SHA256 `e3b7313fd91777c86d3d7393c1e461f043b077b094c6dbbd340b02b70d74baf2`; exact database `tapdb_bloom_prod`, schema `tapdb_bloom_lsmcok1_local`, physical database OID 17040.

The helper requires root to supply the SHA256 of the real reviewed result. No placeholder digest is accepted. It checks `migration_result.status=applied`, exactly that migration and postflight SQL hash, the approved preflight binding, `recovery_completion.status=committed`, committed allocator evidence, and matching `writer_fence_release` schema `tapdb-writer-fence/v1` with `phase=released`. All logical/physical targets and allocator/release result hashes must agree. It performs no database query, migration, fence operation or journal rewrite.

Native source basis: TapDB `daylily_tapdb/cli/db.py:1795–1856` writes the final wrapper only after apply, post-commit recovery and release; `migration_identity.py:1308–1334` intentionally leaves the inner apply receipt's `commit_status=pending_caller_commit`; `migration_identity.py:1392–1413` supplies separate committed recovery; `sequence_fence.py:1436–1598` returns `phase=released` after restoring the original ACL and confirming the open connection gate. The inner apply status alone is never treated as terminal success.

## Root execution after review

Stage the exact reviewed helper on the designated host, retain its SHA256, and invoke it from the interactive Ubuntu login shell using the existing Dayhoff Python with PyYAML. Root supplies the real result hash after receipt review:

```text
sudo /home/ubuntu/miniforge3/envs/DAYHOFF-day/bin/python <absolute-staged-helper-path> --migration-result-sha256 <reviewed-actual-result-sha256>
```

The helper then:

1. Verifies the instance, exact final build receipt, annotated source tag/commit/clean checkout, local image digest/OCI labels and image-owned Bloom version/SHA/branch.
2. Requires the manifest and Compose Bloom image still match the exact 10.0.6 baseline. Bloom must be the same stopped container retained by the migration helper. It captures all project siblings before changing files and rejects concurrent container/receipt changes.
3. Changes only `services.bloom.image` in Compose and `images.bloom.image/source_tag/source_commit` in the manifest. Structural comparison excludes sibling/config changes. A Compose override of image-owned `BLOOM_BUILD_*` fields is an explicit review blocker, not silently rewritten.
4. Executes exactly the selected start: `docker compose -p dayhoff-day -f /opt/dayhoff/deployments/day/compose/docker-compose.yml --progress plain up -d --no-deps --pull never --no-build bloom`.
5. Requires identical sibling names, container IDs, configured/actual images, states, restart counts and start times. Confirms the new Bloom container uses the exact local image, starts running with restart count zero, is not unhealthy, and exposes matching image-owned provenance. Writes receipts under `/opt/dayhoff/deployments/day/logs/bloom-10.0.8-deploy-<timestamp>/`.

Preflight or receipt mismatch prevents deployment. A failure after either file edit is retained as `requires_review`; no implicit retry, rollback or restart occurs. Root must inspect the retained files/container state before deciding recovery. Receipt `started_exact_image` means only selected-image startup, with `availability=PENDING` and `acceptance=PENDING`. Root still owns normal public readiness, existing-reader authorization and the requested snapshot/conditional-write workflow observations.

## Native Dayhoff receipt compatibility amendment

At root's explicit follow-up, before staging or execution, the prepared helper now saves the actual raw `manifest-before.json` and emits `ursa-owy-kahlo.deployment/v1`. Its `observed_at` is captured with the real post-start container observation. `roles` contains only `dayhoff-day-bloom-1`, including configured digest, container/image IDs, state, health and restart count. Existing build receipt, old/new identity and sibling gates are retained; both Compose hashes and the resulting manifest hash are present. All migration/committed-recovery/writer-fence/exact-image guards remain in force.

The historical manifest must retain its original key order: Dayhoff `app/dayhoff/kahlo_publication.py:175–186` loads it, applies only Bloom's image/tag/commit mutation, then hashes `json.dumps(..., indent=2) + "\n"`. The helper therefore saves the raw pre-deployment bytes, and does not serialize this file through its sorted-key evidence writer.

After actual successful deployment and root's runtime review, root may select the deployment receipt, existing build receipt and manifest-before using exact `{path, sha256}` references in a new dated `dayhoff.kahlo.receipts/v1` authority. Preserve every other selected service entry. Native Dayhoff independently checks the complete evidence; no receipt has been created or promoted merely by preparing this helper. A `requires_review` or incomplete deployment result must not be selected as accepted evidence. The former custom `bloom.selected-image-deployment/1` helper shape was never executed or published by this task.

## Preparation evidence and retention

Bloom worktree HEAD is `1c500a71b04f185099b9b4ec38534554e60da41a`, branch `codex/bloom-kahlo-reader-auth-20260918`; there were no tracked modifications at entry. Five preexisting untracked owner-read helper/receipt files remain untouched. Only this dated helper and its preparation note were added. Application source, release allowlist, tags, runtime files, database and containers were unchanged during preparation. No tests, lint, build, CLI execution, deployment or live probe was performed.

Prepared helper: ready for root source/receipt review. Actual deployment and acceptance: not performed by this task. Root owns the later documentation commit; the immutable 10.0.8 application tag must not move.
