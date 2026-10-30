# Bloom persisted-lineage cycle investigation — 2026-09-19T00:55Z

Owner: Agent C. Controlling plan: Ursa/OWY/Kahlo 20260918T043330Z master ledger. User resumed the remaining plan; root assigned the Bloom/Kahlo model and GUI scope. This child does not authorize destructive lineage deletion or reset.

## Gate 0

- Bloom 10.0.10 source `534b8136a4a8f5dbf02f886cdddef59d93e751c2`, image `sha256:a99a076fdfdabf40b19d01dd42189b22dce575f71afc12ae938e373810a5eb71`, deployed 2026-09-18T23:55:22.857192Z. Current docs HEAD `3632db042ec2f3ab599660b1f906ec3e719bf5ee` and unrelated untracked historical notes preserved.
- Kahlo 9.0.7 source `9139c55383cef066dca813edde5efae69feed9a7`, image `sha256:e26744dd5f7ce7b1f176a0c1469ac8a2cb2c7a711d67faf2fe7e15e8988a4a98`, deployed 2026-09-19T00:03:11.809427Z. Prior accepted native CLI/deployment checks are reused.
- Live Bloom container package metadata reports `daylily-tapdb==10.1.4`; the earlier 10.1.6 migration tooling is not the app package pin. Exact 10.1.4 and 10.1.6 graph payload/public route files have no diff.
- Prior public GET `/api/dag/v2/data?start_euid=M-BRM-VG&depth=4` returned HTTP 409, `invalid_local_graph_contract: Cycle detected in persisted lineage`. Receipt `/home/ubuntu/kahlo-bloom-final-20260918T234700Z/bloom10010-graph409-20260919T000450Z.json`, SHA256 `d921da45f5fa13a9fab17133ed04646a99c92e07129fbdfe334c63f735ffe473`.
- Work uses the existing configured Kahlo Bloom reader against Bloom public APIs. No new auth grants, direct DB queries, source edits, builds or model mutations. SSM session runs as ubuntu on `i-07df3a933e4839f52`, us-west-2.

## Execution rows

| ID | Owner | Dependency | Category | Approval gate | Status | Evidence / terminal note |
|---|---|---|---|---|---|---|
| CY0 | C | — | Baseline | Read-only authorized | SUCCESS | Exact deployed versions and original 409 retained above. |
| CY1 | C | CY0 | Diagnosis | Public native reads authorized | SUCCESS | Ten exact reciprocal pairs; all ten reverse-row public lineage/audit queries returned 200 with no truncation. [Exact review](20260919T010230Z_exact_lineage_repair_review.json). |
| CY2 | C | CY1 | Writer correction | Non-destructive source fix authorized | IN_PROGRESS | Three reciprocal creation calls removed; canonical membership retained. Final 10.0.11 tagged release/build/deploy authorized by root. |
| CY2R | C/root | CY1, CY2 | Historical model repair | Separate destructive confirmation required | OPEN | Prepared exact ten-row soft-deletion review; not executed. Objects, canonical membership, unrelated lineage and audit history must remain. |
| CY3 | C | CY2 | Production acceptance | Existing live GUI/API scope | OPEN | Native DAG traversal plus downstream GUI evidence; readiness alone is insufficient. |

## Initial observations

2026-09-19T00:56:45.802365Z: native exact-object GET confirms M-BRM-VG is a persisted `data/sequencing_run/illumina` instance. Its public active lineage list has zero outgoing edges and one incoming `user_created` edge M-EDG-K2JH from actor M-BAR-A65W. At 00:57:16.140576Z the exact actor lookup confirms `actor/user/bloom-user`; its outgoing lineage list contains 87 `user_created` edges and zero incoming edges. Full responses are retained privately at `/home/ubuntu/bloom-cycle-20260919T005500Z/`; no identity/secret metadata is copied into this ledger.

The original cycle therefore is not a direct self-loop on the selected sequencing run. Further bounded public owner graph and exact edge/audit reads are required. Bloom's explicit diagnostic `/api/v1/graph/data` is used only to identify persisted rows; it is not substituted for Kahlo's required native `dag:v2` consumer contract.

## Exact cause and source correction

At 2026-09-19T01:00:24Z, owning public lineage lists confirmed that set M-BGS-174 has 12 outgoing and 11 incoming active generic lineage rows. Ten incoming `associated_set` edges oppose ten outgoing `run_set_member` edges. The other rows are `run_uses_flowcell`, `describes_sequencing_run`, and `user_updated`; they are outside the repair scope. The selected run reaches the historical set through the creator neighborhood.

The owning source explicitly creates both directions in `_run_set`, `create_lab_set`, and `add_lab_set_members`. The correction removes the three `associated_set` calls and documents reverse navigation through the same canonical membership edge. No native DAG cycle guard is weakened, and no persisted row is changed by deployment.

Representative canonical/reverse pair M-EDG-GAXS/M-EDG-GAYQ was inserted at 2026-07-19T02:59:36.972615Z under one historical actor for the Betelgeuse campaign. All ten reverse-edge audit observations and exact preserving counterparts are retained in [the review receipt](20260919T010230Z_exact_lineage_repair_review.json), SHA256 `413f4c8825218f432f556064a816f92834d16f1470546d4bfde98446e5ffb1c0`. Actor identity is hash-redacted in the repository; original owner responses remain private on EC2.

The diagnostic Bloom `/api/v1/graph/data` response reverses displayed directions relative to exact owning lineage/search records. The repair uses the exact lineage/search records, not that diagnostic presentation. This separate legacy display defect is recorded, not silently included in the writer release.

No tests, imports, lint, CI, local builds, new auth grants or persisted-lineage mutations were performed. Initial root-only config read failed permission and was rerun through targeted sudo from ubuntu without printing credential contents.
