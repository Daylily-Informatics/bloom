# Bloom identity and owner-alias contract successor — 2026-09-18

This dated successor supersedes two preparation details in
[`20260918T195300Z_bloom_owner_preconditions_and_identity_ledger.md`](20260918T195300Z_bloom_owner_preconditions_and_identity_ledger.md).
The native owner snapshot, unchanged proposal, ready precondition plan and
historical receipts in that ledger remain valid. Root retains the master queue.

## Final minimal Bloom source correction

The final source change is exactly one line in
`bloom_lims/observability.py`: `base_frame.environment` now uses
`settings.deployment.name`. The existing runtime mode remains in
`settings.environment` and continues to govern existing runtime behavior.

The initially proposed additional `runtime_mode` response field was removed
before release. Kahlo's authoritative `healthz.schema.json` and
`readyz.schema.json` forbid unknown top-level properties; its fleet collector
validates the full native payload before checking identity. Although
`obs_services` permits extra fields, adding the field to their common base
frame would make health/readiness incompatible. No Kahlo schema expansion is
needed for this producer correction. Agent C reviewed those exact schemas and
`fleet.py`'s validation path independently; no tests or builds were run.

## Final native alias reconciliation helper

Use
[`20260918T195317Z_owner_namespace_executor.py`](20260918T195317Z_owner_namespace_executor.py),
SHA256 `6ccefea686783d93280dd4472de0aad7180aa3ee24d16c94dcdfb16c48bfb265`,
in place of the frozen earlier `194400Z` helper. This successor keeps the exact
proposal, 117-row seed, shared lock, append-only journal, whole-owner
preconditions and conditional PATCH receipt/readback contracts.

The root-owned POST helper must persist explicit `receipt_kind` on the
`ont_current_sequencing_run` alias:

| Receipt kind | Required native evidence |
| --- | --- |
| `native_create` | Exact raw creation response, exactly one created owner, original category/type/subtype/name, request-body digest and exact EUID. |
| `native_owner_read` | Exact raw object-detail response after one unambiguous owner match, original type/subtype/name and every requested source property, request-body digest and exact EUID. |

Both branches require a fresh native read-only owner snapshot and all requested
source properties before materializing the deferred PATCH. They are explicit
native reconciliation outcomes; neither invents a receipt, identity, alias or
missing precondition. The resolver accepts neither an absent receipt kind nor
an unrecognized response shape. Subtype stays the native exact lower-case
`ont`; no casing fallback is introduced.

The successor also explicitly requires native `ready=true` alongside the exact
version/commit and an absolute canonical private evidence directory for apply.
It does not change the prepared plan body or its SHA256
`4e127e78938701ad366f932afa1b1ec75214c5123fc464ff0d7d4159ce24891a`.

Status: source and operational handoff prepared. No owner writes, release tag,
image build or deployment were performed by this agent. Root owns the selected
release, actual registration writes, recovery and final production acceptance.
