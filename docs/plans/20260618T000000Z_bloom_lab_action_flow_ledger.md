# Bloom Lab Action Flow Ledger

Date: 2026-06-18

## Summary

Build a Bloom-owned lab actions layer for extraction plates, sequencing library plates, sequencing library pool tubes, sequencing run sets, plate mapping CSV export, object-count create, and EUID barcode print dispatch. The work stays in Bloom on `jem-dev` and uses existing TapDB generic instances plus lineage records. It does not revive queue or workflow-driving behavior.

## Gate 0 Inventory

- Repo: `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom`
- Branch: `jem-dev`
- Boundaries: no production `day`, no `us-west-2`, no destructive DB repair, no real printer calls in tests.
- Existing dirty files before this ledger included Bloom auth/UI/theme files plus recursive template-instantiation changes already present in the worktree.
- Existing primitives found:
  - recursive template create in `BloomObj.create_instances`
  - `container/plate/fixed-plate-96/1.0`, `container/plate/sequencing-library-plate-96/1.0`, `container/well/fixed-plate-well/1.0`
  - `content/sample/gdna/1.0`, `content/sample/sequencing-library/1.0`, `content/pool/sequencing-library/1.0`, `content/reagent/sequencing-index/1.0`
  - `data/quantification/gdna/1.0`, `data/sequencing_run/*/1.0`
  - Zebra Day service wrapper for print dispatch

## Ledger Rows

| ID | Agent | Requirement | Status | Evidence |
|---|---|---|---|---|
| LEDGER-001 | Agent 1 Orchestrator | Create ledger and record baseline state. | COMPLETE | This file records Gate 0 boundaries and evidence. |
| TEMPLATE-001 | Agent 2 Templates | Add `set/run-set/generic/1.01`; update taxonomy tests/docs. | COMPLETE | Added template in `config/tapdb_templates/bloom/templates.json`; updated `README.md`, `docs/apis.md`, `docs/gui.md`, `docs/architecture.md`, and `docs/lab_actions.md`; `test_wet_lab_templates_use_bloom_prefix_taxonomy` passes. Template inventory found no additional templates required for this pass. |
| CORE-001 | Agent 3 Domain Core | Add lab-actions domain service over TapDB objects/lineage, no queue driving. | COMPLETE | Added `bloom_lims/domain/lab_actions.py`; no queue/betalab runtime calls. |
| LINEAGE-001 | Agent 3 Domain Core | Standardize requested relationship types. | COMPLETE | Domain service writes `contains`, `HOLDS_MATERIAL`, `DERIVED_FROM`, `run_set_member`, `associated_set`, `uses_index`, `run_uses_pool`, `run_uses_instrument`, and `run_uses_reagent`. |
| EXTRACT-001 | Agent 4 Extraction | Auto/directed extraction plate creation/fill with gDNA and optional quant/set. | COMPLETE | API tests cover auto extraction, directed extraction into an existing plate, quant data creation, run-set creation, duplicate tube rejection, duplicate destination-well rejection, and filled-well reuse rejection. |
| LIB-001 | Agent 5 Library Plate | 1:1/directed sequencing-library plate creation with index linkage. | COMPLETE | API tests cover 1:1 library plate creation plus directed library mapping with index barcode, index EUID, run-set creation, and duplicate destination-well rejection. |
| POOL-001 | Agent 6 Pooling | Sequencing-library pool tube/content creation from containers/wells/contents/pools. | COMPLETE | API tests cover pool creation from library content, existing pool-tube fill, pool-from-pool via a filled pool tube, duplicate input rejection, and sequencing-run links to instrument/reagent EUIDs. |
| RUN-001 | Agent 7 Seq Run | Sequencing run set plus ILMN sample sheet and explicit non-ILMN rejection. | COMPLETE | API test creates seq run set, downloads ILMN sample sheet, and verifies ONT sample-sheet request returns 400. |
| CSV-001 | Agent 8 Export | Plate mapping CSV with one-degree parent/child mappings. | COMPLETE | API test downloads `plates/{plate_euid}/mapping.csv` and verifies requested columns and source tube EUID. |
| PRINT-001 | Agent 8 Print | Generic EUID print API/UI using Zebra Day; tests mock printing. | COMPLETE | Added `/api/v1/lab-actions/print-euids`; API test mocks `ZebraDayService.submit_print_job` and verifies one call per EUID. |
| GUI-001 | Agent 9 GUI | `/lab-actions` GUI wizard for the complete flow. | COMPLETE | Added `/lab-actions` route and `templates/modern/lab_actions.html`; TestClient GUI smoke verifies all four flow sections render; local browser screenshot exists. |
| QA-001 | Agent 10 QA | API/unit tests for action modes, safeguards, CSV, sample sheet, print mock. | COMPLETE | `python -m pytest tests/test_lab_actions_api.py -q --no-cov` -> 9 passed; focused coverage gate over changed lab-action/object-create surface -> 83.81%, above the requested 81% gate. |
| PW-001 | Agent 11 Playwright | GUI Playwright/screenshots. | COMPLETE | Local Playwright proof captured at `output/playwright/bloom_lab_actions/lab_actions_wizard_local.png`; page reached `/lab-actions` with status 200. Live `jemdev5` proof is tracked as a release/deploy concern, not a source/test blocker. |
| REL-001 | Agent 12 Release | Commit/tag/release later after WIP proof. | COMPLETE | User approved the release train. Bloom release target is `7.0.16`; downstream Dayhoff release evidence is tracked in `dayhoff/docs/plans/20260618T131619Z_bloom_lab_actions_release_train_ledger.md`. No live `jemdev5` refresh is included in this row. |

## Acceptance Notes

- All rows are terminal. User approved the explicit release train after local implementation evidence passed; `REL-001` records the branch/tag/pin train and remains separate from any live `jemdev5` refresh.
- ILMN sample sheet is implemented first.
- Other platform sample-sheet downloads must fail explicitly without fallback.
- Real printer output requires separate explicit approval.
- Template inventory found the current flow is covered by `set/run-set/generic/1.01`, the existing recursive 96-well plate templates, fixed-plate well template, generic tube template, gDNA sample, sequencing-library sample, sequencing-library pool, sequencing-index reagent, and gDNA quant templates. No extra templates are needed for this implementation pass.
- Production rollout details are now documented in `docs/lab_actions.md`.

## Current Validation

- `git diff --check` -> passed.
- `source ./activate dev && ruff check bloom_lims/api/v1/__init__.py bloom_lims/api/v1/lab_actions.py bloom_lims/api/v1/object_creation.py bloom_lims/api/v1/objects.py bloom_lims/domain/lab_actions.py bloom_lims/schemas/lab_actions.py bloom_lims/schemas/objects.py bloom_lims/gui/routes/modern.py tests/test_lab_actions_api.py tests/test_bloom_prefix_taxonomy.py` -> passed.
- `source ./activate dev && ruff check bloom_lims/api/v1/lab_actions.py bloom_lims/domain/lab_actions.py bloom_lims/schemas/lab_actions.py tests/test_lab_actions_api.py` -> passed after the docs pass.
- `source ./activate dev && python -m pytest tests/test_lab_actions_api.py -q --no-cov` -> 9 passed.
- `source ./activate dev && python -m pytest tests/test_lab_actions_api.py tests/test_bloom_prefix_taxonomy.py::test_wet_lab_templates_use_bloom_prefix_taxonomy tests/test_route_coverage_gaps_api.py::test_object_creation_plate_creates_96_linked_wells tests/test_template_instantiation_recursion.py -q --no-cov` -> 14 passed.
- `source ./activate dev && python -m pytest tests/test_lab_actions_api.py tests/test_bloom_prefix_taxonomy.py::test_wet_lab_templates_use_bloom_prefix_taxonomy tests/test_route_coverage_gaps_api.py::test_object_creation_plate_creates_96_linked_wells tests/test_template_instantiation_recursion.py tests/test_api_v1.py::TestObjectCreationAPI tests/test_api_v1.py::TestObjectCreationPathTraversal -q --cov-reset --cov=bloom_lims.api.v1.lab_actions --cov=bloom_lims.domain.lab_actions --cov=bloom_lims.schemas.lab_actions --cov=bloom_lims.api.v1.object_creation --cov=bloom_lims.schemas.objects --cov-report=term-missing --cov-report=json:coverage-lab-actions.json --cov-fail-under=81` -> 30 passed; total changed-surface coverage 83.81%.
- Full repo test collection is not clean in the local Bloom env: `tests/test_beta_cross_repo_smoke.py` imports Ursa and requires `daylily-ephemeral-cluster`; broad non-E2E collection also stalled before progress in local subprocess handling. These are not lab-action source failures.
- Template inventory from `config/tapdb_templates/bloom/templates.json` confirmed these seeded records for the lab-action flow:
  - `BGS/run-set/generic/1.01`
  - `BCP/plate/fixed-plate-96/1.0`
  - `BCP/plate/sequencing-library-plate-96/1.0`
  - `BCW/well/fixed-plate-well/1.0`
  - `BCT/tube/tube-generic-10ml/1.0`
  - `BNB/specimen/blood-whole/1.0`
  - `BNS/specimen/buccal-swab/1.0`
  - `BNA/specimen/saliva/1.0`
  - `BNG/sample/gdna/1.0`
  - `BNQ/sample/sequencing-library/1.0`
  - `BNP/pool/sequencing-library/1.0`
  - `BNX/reagent/sequencing-index/1.0`
  - `BDQ/quantification/gdna/1.0`
- Local browser proof used repo test-runtime config plus `BLOOM_OAUTH=no`; Playwright captured `/lab-actions` at `output/playwright/bloom_lab_actions/lab_actions_wizard_local.png`.
- Local browser console still shows the pre-existing `/api/v1/me/preferences` 503 under test-runtime config; `/lab-actions` itself returned 200 and static assets loaded.
- Docs pass added `docs/lab_actions.md` and linked it from `README.md`, `docs/apis.md`, `docs/gui.md`, and `docs/architecture.md`.

## Remaining Boundaries

- Local Playwright screenshot captured: `output/playwright/bloom_lab_actions/lab_actions_wizard_local.png`.
- No live `jemdev5` Playwright screenshot was captured in this pass; live proof belongs to the deferred release/deploy train.
- No real Zebra Day print job was sent.
- Bloom release, Dayhoff pin update, and Dayhoff double-release are tracked in `dayhoff/docs/plans/20260618T131619Z_bloom_lab_actions_release_train_ledger.md`.
- No live `jemdev5` refresh was performed in this pass.
