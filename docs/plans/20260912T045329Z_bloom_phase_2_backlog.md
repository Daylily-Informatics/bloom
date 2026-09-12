# Bloom Post-Migration Phase 2 Backlog

Date: 2026-09-12

Status: approved items completed in the [phase-2 execution ledger](20260912T053000Z_bloom_phase_2_execution_ledger.md); PR assessment follows.

The Bloom `10.0.1` / TapDB `10.1.3` production migration is accepted and ordinary access is open. This ledger tracks the approved minor work and remaining deferred scope. Before selecting an item, refresh its source state and obtain any authorization required by the tagged-production-first workflow in `AGENTS.md`.

| ID | Deferred item | Current evidence | Status |
|---|---|---|---|
| P201 | Investigate 282 unresolved retired `tapdb_graph` entries retained unchanged on 72 rows. | Investigation completed: 282 entries on 72 active rows lack exact linked legacy reference evidence; retain unchanged. No data mutation or remote lookup. | SUCCESS |
| P202 | Repair Bloom and Kahlo footer source metadata. | Bloom 10.0.3 footer now shows exact source metadata; Kahlo 8.0.1 image metadata restored by removing three stale Compose overrides. | SUCCESS |
| P203 | Rotate the Kahlo Bloom reader token before expiry. | Explicitly skipped for this round. Existing token and expiry remain unchanged; no automation created. | NO_LONGER_NEEDED |
| P204 | Fix Bloom request-session lifetime. | Request-scoped adapter cleanup deployed in 10.0.3; bounded post-access census shows no open transaction. | SUCCESS |
| P205 | Reassess TapDB issue #111 documentation state. | Issue refreshed: still OPEN upstream; Bloom docs now distinguish resolved 10.1.3 deployment blocker from upstream lifecycle documentation. No upstream mutation. | SUCCESS |
| P206 | Refresh and triage dependency pull requests. | Snapshot: #10 cryptography 48→50, #9 pyasn1 0.6.3→0.6.4, #8 Pillow 12.2→12.3, #6 Starlette 1.1→1.3.1, #5 pydantic-settings 2.14.1→2.14.2, #4 python-multipart 0.0.29→0.0.31. All were open, non-draft and based on `main`; mergeability was `UNKNOWN`. | OPEN |
| P207 | Reconcile auth group casing across constants, repository output and CLI validation. | Uppercase role-group constants now match repository and CLI normalization in 10.0.3; no stored roles, memberships or identities rewritten. | SUCCESS |

No dependency PR was selected, changed or merged during migration closeout. Atlas and sibling service source, images, configuration and databases remain outside this backlog unless separately authorized.
