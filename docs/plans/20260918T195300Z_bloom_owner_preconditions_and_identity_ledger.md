# Bloom owner preconditions and deployment identity — 2026-09-18

This child record belongs to the Ursa/OWY/Kahlo master campaign. It is evidence
and a bounded handoff, not a separate execution queue. Root owns release,
deployment, registration writes and final acceptance. No tests, lint, builds,
tags, grants or registration writes were run by this owner during this pass.

## Owner snapshot and conditional PATCH preparation

The immutable source proposal remains
`/Users/jmajor/.config/offwithyou/campaign-20260918/owner-registration-20260918T175900Z/proposal.json`,
SHA256 `b129978cfb79587ea5d6b4e8e8c7e3a51836542d8276c196620ca92dc39ee88e`.
It declares 106 conditional Bloom PATCHes, five Bloom POSTs and six Dewey POSTs.
The original proposal and 117-row `OPEN` journal were preserved byte-for-byte.

| Item | Disposition | Exact evidence |
| --- | --- | --- |
| Initial Ursa-reader collection | BLOCKED before HTTP | SSM `3f1aaf10-0a1c-441a-adf4-ad50f885435f`; configured-reader guard failed. Private stdout/stderr retained under `/home/ubuntu/bloom_ops/owner-preconditions-20260918T193010Z`. |
| Explicit configured Kahlo reader | SUCCESS | Existing native READ_ONLY bearer from `fleet.targets.bloom.headers.Authorization`; public binding `https://bloom.day.lsmc.bio`, TLS verification true. No token value was printed, persisted, rotated or created. |
| Coherent native owner snapshot | SUCCESS | SSM `51cf06f0-dca6-4705-b98f-ee63866f165f`; observed `2026-09-18T19:41:32.309498+00:00`; 112 objects and 111 exact live lineage identities in one read-only repeatable-read transaction, 0.849 seconds. |
| Existing owner namespace conflicts | SUCCESS | `dayoa_campaign_20260918` absent on every observed owner. Native snapshot SHA256 `aa3786d7bce724cddb6546efd5a650035502c1821a524d8f6e8f61303514afba`. |
| Existing owner PATCH preconditions | SUCCESS, prepared only | 105 complete whole-`json_addl` hashes and exact materialized requests. Plan SHA256 `4e127e78938701ad366f932afa1b1ec75214c5123fc464ff0d7d4159ce24891a`. |
| New ONT owner PATCH | OPEN, deferred | No invented EUID or precondition. Resolve only from the actual native creation receipt and a fresh snapshot proving the requested source identity. |
| PATCH application | OPEN, root-owned | No PATCH was transmitted by this preparation pass. |

Private local evidence directory:
`/Users/jmajor/.config/offwithyou/campaign-20260918/owner-preconditions-20260918T194037Z`.
It contains the original proposal/journal/read-set copies, bounded snapshot request,
compact observation and `patch-plan.json`. The observation file SHA256 is
`807544f21e6cc24659dc8693aa78ccf47a32bb6eebc9d3efedefb76e49d86ae3`.
The request file SHA256 is
`215d7efa4929cddfcefdc01796a1e28d7fab1dde1c7bd1381f08f6855283305d`.
Full owner payloads remain private on the designated EC2 host at
`/home/ubuntu/bloom_ops/owner-preconditions-20260918T194037Z/snapshot.stdout.json`.

The successful collector is
[`20260918T194037Z_collect_owner_snapshot.py`](20260918T194037Z_collect_owner_snapshot.py).
Its SHA256 is `2df23b7cc1f8939c1b7d618441d0c5e7fd183b140b6ec4d602f168037d9cb849`.
It pins deployed Ursa 14.1.2 and Bloom 10.0.8 image digests. The earlier
[`20260918T193010Z_collect_owner_snapshot.py`](20260918T193010Z_collect_owner_snapshot.py)
and its failure receipts remain historical; it is not an alternate reader path.

## Shared writer and native execution contract

[`20260918T194400Z_owner_namespace_executor.py`](20260918T194400Z_owner_namespace_executor.py)
implements offline `prepare`, read-only `resolve-ont`, and explicitly selected
`apply`. Root separately owns the five Bloom and six Dewey POST operations.
The helper does not implement POST creation or relation registration. Its POSTs
call only `/api/v1/graph/snapshot`, whose native route requires read permission.

All writer phases use the same private campaign directory, exclusive
`.owner-writer.lock`, and append-only `operation_journal.jsonl`. The initial
117-row journal SHA256 is
`469d007a34b36281b728c004c2aac67fee2e50ee56238dc8184d23f8ebbb8aea`.
The helper verifies those original bytes even after later entries are appended.
It preserves original operation IDs and declaration hashes and records the
separate materialized request hash before sending. It retains native response
and readback files beside each operation's evidence.

The shared `aliases.json` has schema `owy.owner-registration-aliases/1`,
`proposal_sha256`, and an `aliases` mapping. The `ont_current_sequencing_run`
entry contains `service`, `operation_id`, real `euid`, `receipt_path`, the
receipt file SHA256, materialized `request_sha256`, and `observed_at`.
The receipt is the native raw JSON response, not a synthesized identity or
HTTP wrapper. Other owner phases may add their own real lineage/xref aliases.
For ONT creation, `operation_id` is the proposal's persisted declaration
`op-cbe0f7385b8ead9ee0342546`; the alias itself is not an EUID.

Root verified the existing SeqNAS writer environment file
`/home/sysman/.config/offwithyou/owy-dayhoff-env` supplies
`OWY_BLOOM_API_TOKEN`, `OWY_DEWEY_API_TOKEN` and `OWY_URSA_API_TOKEN`.
The PATCH helper reads only `OWY_BLOOM_API_TOKEN` from process memory, verifies
native `bloom:read` and `bloom:write` permissions, and rejects redirects.
Never copy these token values into arguments, files, logs, docs or receipts.

Use absolute reviewed paths for the placeholders below; shell variables denote
operator-supplied paths and hashes, not inferred locations:

```bash
python "$PATCH_HELPER" --campaign-directory "$CAMPAIGN_DIRECTORY" resolve-ont \
  --plan "$PREPARED_PATCH_PLAN" --reviewed-plan-sha256 "$PREPARED_PATCH_PLAN_SHA256" \
  --aliases-sha256 "$NATIVE_ALIASES_FILE_SHA256" --output "$RESOLVED_PATCH_PLAN"

python "$PATCH_HELPER" --campaign-directory "$CAMPAIGN_DIRECTORY" apply \
  --plan "$RESOLVED_PATCH_PLAN" --reviewed-plan-sha256 "$RESOLVED_PATCH_PLAN_SHA256" \
  --expected-bloom-version "$DEPLOYED_BLOOM_VERSION" \
  --expected-bloom-commit "$DEPLOYED_BLOOM_COMMIT" \
  --evidence-directory "$NEW_PRIVATE_EVIDENCE_DIRECTORY" --all-ready
```

The first command makes a new immutable plan after a real ONT owner exists.
The second requires root review of that new plan digest and exact deployed
version/commit. Root may instead select untouched existing-owner operations
with repeated `--operation-id` flags. Before sending anything, the helper
rechecks all retained lineage identities and every selected owner precondition;
it does not silently refresh changed preconditions. Each conditional PATCH
must return the native committed receipt and preserve all unrelated owner JSON
on exact readback. Any prior execution history on a selected PATCH stops an
automatic resend; root must reconcile that operation separately. This helper
does not assert that registration or the six workflow proofs are complete.

Native lower-case `ont` is authoritative for this proposal. Bloom's template
query compares subtype exactly; it does not normalize `ont` to `ONT`. Root
verified the current public template inventory and existing owner subtype in
`/home/sysman/.config/offwithyou/campaign-20260918/owner-template-authority-20260918T195700Z.json`,
SHA256 `cb3f03809aec02445152a91be2fc2b81288c48dd96584c37d9fed12f8dfd026e`.
The file's observation time, rather than its ahead-chosen filename, is authoritative.

## Bloom observability deployment identity correction

Kahlo's live reader correctly rejected Bloom's `environment=development`
against its explicit `day` binding. Bloom 10.0.8 health and readiness returned
HTTP 200 and the correct source commit at `2026-09-18T19:38:46Z`–`19:38:47Z`;
the error was the producer's identity field, not liveness or credentials.
Kahlo owns the native observation receipt. No Kahlo identity relaxation is needed.

The minimal producer correction changes only `base_frame()` in
`bloom_lims/observability.py`: `environment` comes from authoritative
`settings.deployment.name`; a separate `runtime_mode` retains
`settings.environment` (`development`, `staging`, `production` or `testing`).
All observability endpoints use this frame. Authentication, grants, native
owner registration contracts and database configuration remain unchanged.

Source inspection establishes the distinction at `config.py`'s
`DeploymentSettings` and `Settings.environment` validator. The common frame
previously conflated those settings. No test, build or runtime mutation was
used to prepare this correction. Root owns its necessary final corrective
release and deployed readback of `service=bloom`, `environment=day`, the exact
new source commit and the independent runtime mode.

The snapshot/precondition preparation is complete; ONT resolution, owner writes,
the corrected deployment and end-to-end acceptance remain open in the master
campaign. Not all required rows are terminal and the overall objective is not complete.
