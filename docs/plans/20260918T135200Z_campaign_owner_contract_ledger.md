# Bloom campaign owner API ledger

Controlling ledger: `/Users/jmajor/projects/mega_dayhoff/.codex-worktrees/ursa-dyec20062-sweeper-20260918/docs/plans/20260918T043330Z_ursa_owy_kahlo_ledger.md`. Owner: orchestrator, sole Bloom writer. AgentA owns the paired Ursa consumer/TapDB function repair.

## Gate0

Base/deployed Bloom10.0.6 exacta67dee5dab4a2466f4534535b720f9560f261b6e; existing working branchcodex/bloom-kahlo-reader-auth-20260918 has no modified source. Five prior untracked owner-read receipts are preserved and excluded from this source scope. Actual60/minute,1000/hour,burst10 limiter plus OWY15second submission timeout makes existing repeated per-file owner reads infeasible. Largest proof needs67 unique objects/66 exact edge selectors; current640 file bindings repeat them. Existing graph traversal omits required properties and is not a bounded explicit owner snapshot. Existing106 proposed metadata PUTs have no conditional-write guard. No owner payload has been applied.

| ID | Owner | Status | Deliverable / evidence |
|---|---|---|---|
| BL1 | root | IN_PROGRESS | Native authenticated read-only bounded snapshot endpoint; exact128object/128edge bounds, repeatable-read transaction, complete payload/hash contract, no traversal/cache/limiter change |
| BL2 | root | IN_PROGRESS | Native conditional additive campaign-property namespace write, exact previous JSON hash, conflict/idempotency receipts, unrelated state preserved |
| BL3 | root | OPEN | Source-reviewed immutable final tag/image on confirmed EC2 builder; selected Bloom-only deployment after proper native authorization repair |
| BL4 | root/A/B | OPEN | Actual production snapshot latency and owner persistence/readback for all proof inputs; no inference from release |

No pytest/lint/coverage/CI, dependency upgrade, local container build, PR/merge, auth grant, raw DB mutation, or destructive action is authorized by these rows. Release/deployment follows existing approved master plan; final EC2 image only. Every runtime mutation requires its native guarded route and retained receipt.

## Source review and final release gate

- 2026-09-18T14:06:59.831835+00:00: AgentA independently compared the exact Bloom snapshot producer and Ursa consumer, including all fields/digests, complete object/edge sets and native RR/read-only scope. No concrete contract mismatch found. The namespace route holds the real live row, checks the previous full JSON hash, preserves unrelated fields, and returns success only after native commit. Existing TapDB record_update audit applies. No tests or runtime endpoint calls.
- Snapshot observation time comes from the source database transaction_timestamp(), not response collection time.
- Native builder observation2026-09-18T14:05:55Z confirms i-07df3a933e4839f52/us-west-2 hosts running Bloom container3de32bc9... at deployed10.0.6 image sha256:590a8af40c0412c5e8d24c390597be253f12ac20642429ec4e338cd0b8ff2df2, restart count0.
- Remote10.0.7 already exists at a70ed8e9c553a5e7f97a52e5b8f76e6bc3d071b3 and only changes native TapDB packaging pins; it is not the observed deployed baseline. Proposed10.0.8 retains the actual deployed10.0.6 dependency set. Native TapDB10.1.6 operator installation/migration remains separately reviewed and tracked. No pushed tag will move.
- Final image build may begin after this exact source release. Bloom deployment and owner acceptance remain dependent on the native authorization repair and current deployment inventory.
