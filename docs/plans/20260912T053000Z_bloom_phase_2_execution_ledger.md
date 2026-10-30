# Bloom phase-2 approved work and subsequent PR disposition

Status: SUCCESS

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
| P204 | Close Bloom database sessions at request completion | Operator | SUCCESS | 10.0.3 deployed; normal dashboard/object/graph access; post-access census: one idle connection, zero open transactions |
| P207 | Canonical uppercase group codes across auth and CLI | Operator | SUCCESS | Shared constants now match native persistence and CLI normalization; existing human SSO and READ_ONLY Kahlo graph access succeed without identity/group mutation |
| P202 | Accurate Bloom/Kahlo footer release provenance | Operator | SUCCESS | Authenticated pages show Bloom 10.0.3 / 84af628 and Kahlo 8.0.1 / 5dce7bf with exact working branches; Kahlo image unchanged |
| P201 | Investigate retained historical graph records; propose disposition | Operator | SUCCESS | Read-only production query: 282 entries, 72 active rows, all lack linked legacy reference evidence; retain unchanged, no remote service contact or data mutation |
| P205 | Reconcile issue 111 documentation | Operator | SUCCESS | GitHub issue remains OPEN; accepted 10.1.3 additive versioning resolved Bloom deployment blocker |
| REL | Publish/deploy selected tagged services and confirm ordinary access | Operator | SUCCESS | Bloom tag/release 10.0.3, one image build, scoped Compose exit 0; all 11 sibling containers unchanged; selected containers running with zero restarts |
| PRS | After REL, update outstanding Bloom PRs and close obsolete items; assess remaining | Operator | SUCCESS | All six commented; #10/#6/#5/#4 closed as superseded targets; #9/#8 retained. [Assessment](20260912T215250Z_bloom_pr_disposition.md) |
| P203 | Token rotation | Operator | NO_LONGER_NEEDED | Explicitly skipped for this round; existing token unchanged |

PR closure wording will be clarified before any ambiguous closure; definite obsolete/superseded items can be handled from source evidence.

## Investigation receipts and release candidate

- Protected host receipt `/home/ubuntu/bloom_ops/phase2-20260912/graph-inventory.json`: source-field counts collection event 18, organization site 24, patient 12, test 60, fulfillment item 72, testkit 36, TRF 60. All 282 entries are `no_linked_reference_evidence` under the exact historical BGX comparison. Retain metadata; a later data-conversion proposal needs independent authoritative evidence. No Atlas access or mutation occurred.
- Baseline runtime census during that read: one idle Bloom runtime session, no idle-in-transaction session at that instant. The previous lock evidence and current unclosed handler source demonstrate the lifecycle defect; it need not be reproduced with a load campaign.
- Kahlo needs no rebuild: live Compose overrides image-owned 8.0.1 provenance with tag 7.0.0, branch container and a 64-character image digest. Remove only these overrides and fix their Dayhoff generator; restart only Kahlo. Preserve the same image and credential.
- Bloom patch candidate: annotated 10.0.3, one image build; static review only before deployment. Acceptance is the running tagged service and ordinary authenticated access, not a test suite.

## Runtime closeout before PR work

- Published [Bloom 10.0.3](https://github.com/lsmc-bio/bloom/releases/tag/10.0.3), annotated tag at `84af628dcd6b135ba0785cfcf9081cbc64b3d399`. Exact image digest `sha256:5a373d5a4e8d66dd6137d2edbb8a48796e4bb0861b4c8130c93b40a3a1f225f5`. One build, no rerun.
- Protected host deployment receipt `/home/ubuntu/bloom_ops/phase2-20260912/deployment.json`: Compose returned 0; Bloom container `74d4272c9db3`, Kahlo `53f225f0693d`; 11 sibling container IDs unchanged. Only Bloom image and three stale Kahlo metadata overrides changed. No credential or schema changes.
- Normal SSO dashboard and existing object `M-BBX-E0C5` opened successfully; authenticated Kahlo graph for the already-persisted Bloom root loaded 6 nodes, 6 edges, zero external jumps and no traversal warnings. Footers show the released commits. Local receipt `/Users/jmajor/.codex/artifacts/bloom-phase2-20260912/browser-acceptance.json`.
- Post-access `/home/ubuntu/bloom_ops/phase2-20260912/post-access-sessions.json`: one idle runtime connection, oldest transaction age 0, no idle-in-transaction session. Both selected containers running, restart counts 0; Bloom log ERROR/Traceback count 0 during the startup interval. This is bounded running-service acceptance, not a test or load campaign.
- Companion Dayhoff commit `9f889d5` pushed to its existing working branch; Bloom pin 10.0.3, Kahlo remains 8.0.1. No Dayhoff release, PR, merge or full deployment.
- Approved runtime/investigation items are complete. PR inspection starts only after these receipts.

## Final status

All approved rows terminal: 7 SUCCESS, 1 NO_LONGER_NEEDED (token rotation explicitly skipped for this round). Objective complete. No tests, lint, coverage or CI campaign; one Bloom image build, no Kahlo rebuild, no PR creation or merges. Runtime acceptance is bounded ordinary access and the retained session/state receipts, not comprehensive behavior or long-duration load proof. Existing credentials, template semantics, graph history and migration/allocator receipts remain preserved.
