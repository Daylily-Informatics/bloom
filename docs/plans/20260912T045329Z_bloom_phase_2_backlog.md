# Bloom Post-Migration Phase 2 Backlog

Date: 2026-09-12

Status: open backlog; no item selected

The Bloom `10.0.1` / TapDB `10.1.3` production migration is accepted and ordinary access is open. This separate ledger contains deferred minor work only. Before selecting an item, refresh its source state and obtain any authorization required by the tagged-production-first workflow in `AGENTS.md`.

| ID | Deferred item | Current evidence | Status |
|---|---|---|---|
| P201 | Investigate 282 unresolved retired `tapdb_graph` entries retained unchanged on 72 rows. | Migration archived only 111 exact lineage-backed entries; no identity or lineage was invented. | OPEN |
| P202 | Repair Bloom and Kahlo footer source metadata. | Runtime images and tags are proven, but Bloom omitted branch/commit and Kahlo displayed stale tag/commit text. | OPEN |
| P203 | Rotate the Kahlo Bloom reader token before expiry. | Bloom-owned READ_ONLY identity `M-SYS-9T5J`; `internal_ro` token expires `2026-12-11T04:45:17.375690+00:00`. Keep legacy account/token untouched. Do not schedule automation without explicit approval. | OPEN |
| P204 | Fix Bloom request-session lifetime. | Runtime PIDs 958 and 981 remained idle in transaction for about 48 minutes on generic-instance/lineage reads and blocked the additive template relation lock until only Bloom was stopped. | OPEN |
| P205 | Reassess TapDB issue #111 documentation state. | Released `10.1.3` supplied the accepted additive versioned XRF behavior; [issue #111](https://github.com/Daylily-Informatics/daylily-tapdb/issues/111) remained open during migration. | OPEN |
| P206 | Refresh and triage dependency pull requests. | Snapshot: #10 cryptography 48→50, #9 pyasn1 0.6.3→0.6.4, #8 Pillow 12.2→12.3, #6 Starlette 1.1→1.3.1, #5 pydantic-settings 2.14.1→2.14.2, #4 python-multipart 0.0.29→0.0.31. All were open, non-draft and based on `main`; mergeability was `UNKNOWN`. | OPEN |

No dependency PR was selected, changed or merged during migration closeout. Atlas and sibling service source, images, configuration and databases remain outside this backlog unless separately authorized.
