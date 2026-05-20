# Bloom Sequencing Run Ledger

Date: 2026-05-20T06:49:52Z

## Scope

Add a first-class Bloom sequencing run concept for the Dayhoff-deployed Bloom service at `https://bloom.dev.lsmc.life/`. A sequencing run is an instrument-executed operation with platform/subtype, operator start time, sequencing end time, optional instrument linkage, and lineage back to sequencing pools and library assignments.

## Gate 0: Inventory Freeze

| Item | Evidence |
|---|---|
| Controlling repo | `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom` |
| Ledger path | `docs/plans/20260520T064952Z_bloom_sequencing_run_ledger.md` |
| Repo state | `git status --short --branch -> ## main...origin/main` |
| Instructions read | `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom/AGENTS.md`, `/Users/jmajor/projects/mega_dayhoff/dayhoff/AGENTS.md`, `/Users/jmajor/.agents/AGENTS.md`, `/Users/jmajor/.agents/AGENTS.md~`, `/Users/jmajor/.codex/docs/plan-ledger-workflow.md`, `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom/.augment/RULES.md` |
| Existing pool/run surface | `bloom_lims/api/v1/beta_lab.py` already exposes `POST /api/v1/external/atlas/beta/pools`, `POST /api/v1/external/atlas/beta/runs`, and `GET /api/v1/external/atlas/beta/runs/{run_euid}/resolve` |
| Existing pool implementation | `bloom_lims/domain/beta_lab_stages.py::create_pool` already creates `content/pool/generic/1.0`, a pool tube, `contains` lineage, and `beta_pool_member` edges |
| Existing run gap | `create_run` stores runs as `data/generic/generic/1.0` with `beta_kind=sequencing_run`; `BetaRunCreateRequest.platform` is `Literal["ILMN"]`; run properties do not have explicit `operator_start_datetime`, `sequencing_end_datetime`, `instrument_euid`, or run subtype |
| Template gap | `config/tapdb_templates/bloom/templates.json` has `data/wetlab/library_prep_output/1.0` and equipment sequencer templates, but no `data/sequencing_run/*/1.0` templates |
| Atlas boundary | Bloom `.augment/RULES.md` requires Bloom and Atlas to interact only through published APIs; this change will preserve existing external-reference lineage and not read/write Atlas DBs |
| Live target | Public Bloom URL is `https://bloom.dev.lsmc.life/`; exact Dayhoff EC2/runtime path to be verified before live restart |
| Safety boundary | No destructive AWS actions; use SSM only; restart only Bloom after local tests and live inventory |

## Rows

| ID | Area | Requirement | Status | Category | Approval Gate | Owner | Evidence | Root Cause | Terminal Note |
|---|---|---|---|---|---|---|---|---|---|
| BSR-001 | Template pack | Add first-class sequencing run templates with subtypes for Illumina, ONT, and NovaSeq. | SUCCESS | feature_implementation | Gate 3 | orchestrator | `config/tapdb_templates/bloom/templates.json`; live seed verified `BDT/sequencing_run/{illumina,novaseq,ont}/1.0` with EUIDs `Z-TPX-50P`, `Z-TPX-52J`, `Z-TPX-51M` | Missing template-backed sequencing-run data records; runs were generic data rows. | Added and seeded three Bloom-owned sequencing run templates. |
| BSR-002 | API schema | Extend beta run create/response schema with run subtype, operator start datetime, sequencing end datetime, and instrument linkage while preserving explicit validation. | SUCCESS | feature_implementation | Gate 3 | orchestrator | `bloom_lims/schemas/beta_lab.py`; public `https://bloom.dev.lsmc.life/openapi.json` exposes `platform` enum `ILMN,ONT`, `run_subtype`, `operator_start_datetime`, `sequencing_end_datetime`, and `instrument_euid` | Existing beta run schema only modeled ILMN flowcell runs. | Schema accepts Illumina, ONT, NovaSeq subtype contract and rejects mismatched platform/subtype and naive/out-of-order datetimes. |
| BSR-003 | Domain persistence | Store sequencing runs using the subtype-specific sequencing run template, link optional instrument via existing `beta_used_instrument`, and preserve pool/library/assignment lineage. | SUCCESS | feature_implementation | Gate 3 | orchestrator | `bloom_lims/domain/beta_lab.py`, `bloom_lims/domain/beta_lab_store.py`, `bloom_lims/domain/beta_lab_stages.py`; local DB-backed `tests/test_queue_flow.py::test_beta_queue_flow_end_to_end` verifies run instance `type=sequencing_run`, `subtype=novaseq`, persisted timing fields, and `beta_used_instrument` lineage | Persistence always created `data/generic/generic/1.0` rows for sequencing runs. | Run creation now chooses `data/sequencing_run/{illumina,ont,novaseq}/1.0` and still keeps pool, library assignment, artifact, and Atlas fulfillment lineage. |
| BSR-004 | Pool assessment | Verify whether pooled sequencing library already exists and avoid adding a duplicate concept if current `content/pool/generic/1.0` plus pool tube/member lineage satisfies the request. | SUCCESS | feature_implementation | Gate 3 | orchestrator | Existing `create_pool` creates `content/pool/generic/1.0`, pool tube, `contains`, and `beta_pool_member` edges; `tests/test_queue_flow.py::test_beta_queue_flow_end_to_end` exercises that pool before creating the run | Pool concept was uncertain, but not absent. | No duplicate pool model added; existing pool content plus container/member lineage satisfies the request. |
| BSR-005 | Tests | Add focused tests for sequencing run templates, schema validation, persisted run fields, instrument linkage, and existing pool lineage. | SUCCESS | contract_test | Gate 5 | orchestrator | `pytest tests/test_sequencing_run_contract.py tests/test_queue_flow.py::test_beta_queue_flow_end_to_end tests/test_run_resolver.py::test_run_resolver_returns_404_for_unknown_index -q --no-cov` -> `4 passed`; `jq empty config/tapdb_templates/bloom/templates.json`; `git diff --check` | Contract needed coverage for template loadability and first-class run persistence. | Focused local tests pass. |
| BSR-006 | Live deploy | Patch AWS-deployed Bloom, seed any new Bloom-owned templates, restart only Bloom, and verify public/auth/readiness behavior. | SUCCESS | contract_test | Gate 5 | orchestrator | Live target `i-09126000eb19643b0`, repo `/home/ubuntu/.cache/dayhoff/local/lsmcok1/repos/bloom`, config `/home/ubuntu/.config/bloom-lsmcok1/bloom-config-lsmcok1.yaml`; `bloom --config ... db seed` -> `seed=ok`; old Bloom PID `238229`, new Bloom PID `264810`; `https://bloom.dev.lsmc.life/readyz` -> `ready=true`, DB `status=ok` | AWS Bloom needed the same template/schema/domain patch and live TapDB seed. | AWS Bloom patched, templates seeded, and only Bloom restarted. |

## Gate 5: Closeout

All ledger rows are terminal as `SUCCESS`.

The real objective is complete on the AWS Bloom deployment: sequencing runs are template-backed TapDB data instances with Bloom-assigned EUIDs for Illumina, ONT, and NovaSeq subtypes, and the live service at `https://bloom.dev.lsmc.life/` is running the patched code.
