# Bloom Queue Refactor Execution Summary

## Status

This refactor is complete for the active beta path.

Bloom is now the beta authority for material lineage and queue-driven wet-lab execution without depending on workflow/workflow-step runtime on the supported Atlas/Ursa path.

## Active Model

- queue membership is represented by graph relationships
- Atlas intent enters Bloom through explicit test-process-item reference objects
- lineage is preserved from accepted material through extraction, library prep, pooling, run creation, and sequenced library assignment
- the canonical resolver unit is `sequenced_library_assignment`

## Canonical Resolver

Bloom resolves:

- `run_euid`
- `flowcell_id`
- `lane`
- `library_barcode`

Bloom returns:

- `sequenced_library_assignment_euid`
- `atlas_tenant_id`
- `atlas_trf_euid`
- `atlas_test_euid`
- `atlas_test_process_item_euid`

## Legacy Isolation

Retired workflow and `do_action` surfaces are not part of the active beta route. If a path depends on workflow-step runtime, accession ownership, or legacy action execution, treat it as non-beta.

## Validation

Focused validation for the active beta path:

```bash
source bloom_activate.sh
pytest --no-cov tests/test_api_atlas_bridge.py tests/test_atlas_lookup_resilience.py tests/test_queue_flow.py tests/test_run_resolver.py tests/test_beta_cross_repo_smoke.py
ruff check bloom_lims tests
```
