# Bloom phase-2 approved work and subsequent PR disposition

Status: IN_PROGRESS

## Gate 0

- User approved items 1, 2, 3, 4 and 6; credential rotation (5/P203) is skipped. PR disposition follows release completion.
- Bloom: clean `codex/bloom-tapdb10-receipts` at `671021c`; prior documentation tag 10.0.2, accepted runtime 10.0.1/TapDB 10.1.3.
- Kahlo: `codex/kahlo-8-0-1-release` at released 8.0.1; pre-existing dirty AGENTS.md is preserved and excluded.
- Dayhoff desired-state checkout: clean `codex/bloom-10-0-1-pin-20260912`.
- Source inventory: unclosed BLOOMdb3 instances occur in graph and operations handlers; role-group constants are lowercase while persistence and CLI input normalize uppercase. Bloom footer runs Git commands in an image without Git metadata; Kahlo footer metadata source requires image/config reconciliation.
- Scope: request/session lifecycle, group-code casing, Bloom/Kahlo footer provenance; historical graph investigation is read-only. No schema migration, sequence operations, template changes, credential rotation, sibling changes, PR creation, merges or tests.
- Release each changed service once from its annotated working-branch tag. Scoped container deployment and ordinary access are the acceptance evidence.

| ID | Requirement | Owner | Status | Evidence / next action |
|---|---|---|---|---|
| P204 | Close Bloom database sessions at request completion | Operator | IN_PROGRESS | Adapter and HTTP request lifecycle |
| P207 | Canonical uppercase group codes across auth and CLI | Operator | IN_PROGRESS | rbac constants, GroupService and repository |
| P202 | Accurate Bloom/Kahlo footer release provenance | Operator | IN_PROGRESS | Image build metadata and rendering |
| P201 | Investigate retained historical graph records; propose disposition | Operator | SUCCESS | Read-only production query: 282 entries, 72 active rows, all lack linked legacy reference evidence; retain unchanged, no remote service contact or data mutation |
| P205 | Reconcile issue 111 documentation | Operator | SUCCESS | GitHub issue remains OPEN; accepted 10.1.3 additive versioning resolved Bloom deployment blocker |
| REL | Publish/deploy selected tagged services and confirm ordinary access | Operator | OPEN | No tests; no PR or merge |
| PRS | After REL, update outstanding Bloom PRs and close obsolete items; assess remaining | Operator | OPEN | Refresh against final release, no PR branch updates/merges or test campaign |
| P203 | Token rotation | Operator | NO_LONGER_NEEDED | Explicitly skipped for this round; existing token unchanged |

PR closure wording will be clarified before any ambiguous closure; definite obsolete/superseded items can be handled from source evidence.

## Investigation receipts and release candidate

- Protected host receipt `/home/ubuntu/bloom_ops/phase2-20260912/graph-inventory.json`: source-field counts collection event 18, organization site 24, patient 12, test 60, fulfillment item 72, testkit 36, TRF 60. All 282 entries are `no_linked_reference_evidence` under the exact historical BGX comparison. Retain metadata; a later data-conversion proposal needs independent authoritative evidence. No Atlas access or mutation occurred.
- Baseline runtime census during that read: one idle Bloom runtime session, no idle-in-transaction session at that instant. The previous lock evidence and current unclosed handler source demonstrate the lifecycle defect; it need not be reproduced with a load campaign.
- Kahlo needs no rebuild: live Compose overrides image-owned 8.0.1 provenance with tag 7.0.0, branch container and a 64-character image digest. Remove only these overrides and fix their Dayhoff generator; restart only Kahlo. Preserve the same image and credential.
- Bloom patch candidate: annotated 10.0.3, one image build; static review only before deployment. Acceptance is the running tagged service and ordinary authenticated access, not a test suite.
