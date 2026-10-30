# Bloom 10.0.4 dependency rollout

Date: 2026-09-12. Owner: operator. Scope: user-selected PR #9 pyasn1 0.6.4 and PR #8 Pillow 12.3.0, incorporated directly on the working branch; one Bloom image build and scoped deployment. No tests, CI campaign, PR merge, schema/data/sequence migration, credential change or sibling deployment.

| ID | Requirement | Status | Evidence / next action |
|---|---|---|---|
| D00 | Capture baseline and selected inputs | SUCCESS | Clean codex/bloom-tapdb10-receipts at 88a50b5; live Bloom 10.0.3 image sha256:5a373d5a4e8d66dd6137d2edbb8a48796e4bb0861b4c8130c93b40a3a1f225f5 running with zero restarts. Remote 10.0.4 tag unused. |
| D01 | Incorporate only selected dependencies | SUCCESS | PR #9 f637cf99e20e751f1df0677aabe5cdce6eddbad8 and #8 6115149b92ed44c11526d7d39f581128fd233e67 remain open. Applied exact lock diffs: pyasn1 0.6.3 → 0.6.4; Pillow 12.2.0 → 12.3.0. Static TOML comparison confirms only these two package records differ. TapDB remains 10.1.3. |
| D02 | Publish annotated 10.0.4 and one image | OPEN | Commit/push/tag/release, build exact clean tagged source and retain digest. |
| D03 | Deploy only Bloom and confirm normal access | OPEN | Scoped Compose replacement; installed-version receipt, running state and authenticated dashboard. |
| D04 | Closeout and PR dispositions | OPEN | Update desired Bloom pin, documentation, receipts; close #8/#9 unmerged once incorporated and deployed. |

Evidence root: /Users/jmajor/.codex/artifacts/bloom-dependencies-20260912T215750Z. Remote receipt root: /home/ubuntu/bloom_ops/dependencies-20260912T215750Z. Prior phase-2 evidence remains historical and unchanged. A local metadata inspection initially used Python without tomllib; rerun with existing Python 3.12 succeeded. No application tests ran.
