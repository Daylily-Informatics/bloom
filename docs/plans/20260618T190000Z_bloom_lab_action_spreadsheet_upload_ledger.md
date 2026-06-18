# Bloom Lab Actions Spreadsheet Upload Ledger

Date: 2026-06-18

## Summary

Extend the existing Bloom lab-action layer so extraction QC plate fill, sequencing-library plate generation, plate-well associated data, pool creation from wells/tubes/contents/pools, generic set management, and sequencing run-set creation can be driven through API, GUI, and spreadsheet uploads.

The attached workbook `Container to Container Interactions (1).xlsx` is a schema example. It has `Bulk Create`, `Transfer`, and `Annotation` sheets with source/target container, child container, content-template, and annotation/data-template columns. This pass supports that family of spreadsheet layout as a parsed/previewed container-interaction workbook and adds executable lab-action sheet shapes for the Bloom wet-lab flow.

## Boundaries

- Work stays in Bloom on `jem-dev`.
- No production `day`, no `us-west-2`, no live deploy, no destructive DB repair.
- Use existing TapDB generic instances and lineage records.
- Do not revive queue or betalab workflow-driving behavior. Existing queue/betalab code may remain until replaced.
- No fallback config discovery. Runtime config remains explicit.

## Gate 0 Inventory

| Surface | State |
|---|---|
| Branch | `jem-dev` |
| Pre-existing dirty files | Untracked `coverage-lab-actions.json`, untracked `output/` |
| Existing API | `/api/v1/lab-actions/extraction-plates`, `/seq-library-plates`, `/seq-library-pools`, `/seq-runs`, `/plates/{plate_euid}/mapping.csv`, `/print-euids` |
| Existing GUI | `/lab-actions` wizard |
| Existing templates | `set/run-set/generic/1.01`, recursive 96-well plate templates, gDNA, sequencing-library content, sequencing-library pool, sequencing-index, gDNA quant |
| Spreadsheet example | Sheets: `Bulk Create`, `Transfer`, `Annotation`; headers on row 4 |

## Workstreams

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| LEDGER-001 | Create ledger and record attached spreadsheet/current source baseline. | COMPLETE | This ledger records the workbook sheets, Bloom branch, pre-existing dirt, current lab-action API, GUI, and template baseline. |
| XLSX-001 | Add dependency-free CSV/XLSX workbook parser for lab-action uploads. | COMPLETE | `bloom_lims/domain/lab_action_spreadsheets.py`; parser accepts `.csv` and `.xlsx`, normalizes operator header typos, and previews the attached workbook family. |
| QC-001 | Add extraction QC plate fill API/domain support. | COMPLETE | `POST /api/v1/lab-actions/extraction-qc-plates`; `LabActionsService.fill_extraction_qc_plate`; tests cover explicit QC well fill and 96-assignment capacity guard. |
| DATA-001 | Add associated data-to-plate-well API/domain support. | COMPLETE | `POST /api/v1/lab-actions/plate-well-data`; supports well or well-content targets with structured data payloads. |
| SET-001 | Add generic set create/read/member-management API/domain support. | COMPLETE | `POST /sets`, `GET /sets/{set_euid}`, and `POST /sets/{set_euid}/members`; uses existing `set/run-set/generic/1.01` template and lineage. |
| IMPORT-001 | Add spreadsheet upload endpoint that can dry-run/execute explicit lab-action sheets and preview container-interaction sheets. | COMPLETE | `POST /api/v1/lab-actions/spreadsheet-import`; tests execute extraction QC, seq-library plate, seq-pool, seq-run set, set, and plate-well-data CSV imports, and preview XLSX `Transfer`. |
| GUI-001 | Expose QC, data, set, and spreadsheet-upload controls on `/lab-actions`. | COMPLETE | `templates/modern/lab_actions.html`; GUI smoke test confirms Extraction QC, Spreadsheet Upload, Manage Sets, and upload action controls render. |
| DOC-001 | Update docs with sheet schemas, API routes, and production rollout guidance. | COMPLETE | `README.md`, `docs/apis.md`, `docs/gui.md`, and `docs/lab_actions.md` updated with endpoints, sheet schemas, GUI panels, and rollout tests. |
| TEST-001 | Add focused parser/API/GUI tests and run validation. | COMPLETE | `ruff check ...` passed; `source ./activate dev && python -m pytest tests/test_lab_actions_api.py -q --no-cov` -> 13 passed; changed-surface coverage command -> 34 passed, total coverage 83.16% >= 81%. |
| REPORT-001 | Final report with test output, changed files, and commit status. | COMPLETE | This ledger plus final chat report. Generated coverage/output artifacts are not committed unless promoted separately. |

## Spreadsheet Sheet Shapes

Executable lab-action uploads use these sheet names:

- `Extraction Plate`
- `Extraction QC`
- `Seq Library Plate`
- `Seq Pool`
- `Seq Run Set`
- `Sets`
- `Plate Well Data`

Container-interaction workbook sheets from the attached example are parsed for preview/evidence:

- `Bulk Create`
- `Transfer`
- `Annotation`

## Acceptance

- API tests prove QC plate fill, plate-well data, set management, pool from plate well/tube, and spreadsheet import.
- GUI smoke test proves the upload/QC/set controls render on `/lab-actions`.
- Docs explain the spreadsheet columns and current production rollout boundary.
- No queue-driving logic is added.

## Validation

- `python -m py_compile bloom_lims/domain/lab_action_spreadsheets.py bloom_lims/domain/lab_actions.py bloom_lims/api/v1/lab_actions.py bloom_lims/schemas/lab_actions.py` -> passed.
- `ruff check bloom_lims/domain/lab_action_spreadsheets.py bloom_lims/domain/lab_actions.py bloom_lims/api/v1/lab_actions.py bloom_lims/schemas/lab_actions.py tests/test_lab_actions_api.py` -> passed.
- `source ./activate dev && python -m pytest tests/test_lab_actions_api.py -q --no-cov` -> 13 passed.
- `source ./activate dev && python -m pytest tests/test_lab_actions_api.py tests/test_bloom_prefix_taxonomy.py::test_wet_lab_templates_use_bloom_prefix_taxonomy tests/test_route_coverage_gaps_api.py::test_object_creation_plate_creates_96_linked_wells tests/test_template_instantiation_recursion.py tests/test_api_v1.py::TestObjectCreationAPI tests/test_api_v1.py::TestObjectCreationPathTraversal -q --cov-reset --cov=bloom_lims.api.v1.lab_actions --cov=bloom_lims.domain.lab_actions --cov=bloom_lims.domain.lab_action_spreadsheets --cov=bloom_lims.schemas.lab_actions --cov=bloom_lims.api.v1.object_creation --cov=bloom_lims.schemas.objects --cov-report=term-missing --cov-report=json:coverage-lab-actions.json --cov-fail-under=81` -> 34 passed, total coverage 83.16%.
