# Bloom

Bloom is the LSMC beta authority for physical and material LIMS state.

Bloom owns:

- containers
- specimens
- derived samples
- plates and wells
- extraction outputs
- library prep outputs
- pools
- sequencing runs
- sequenced library assignments
- queue membership and queue-transition state for wet-lab execution

Bloom does not own:

- accessioning
- customer, TRF, Test, patient, provider, shipment, or kit truth
- workflow or workflow-step orchestration for the beta path

## Beta Architecture

The active beta path is queue-driven and graph-native.

Canonical queues:

- `extraction_prod`
- `extraction_rnd`
- `post_extract_qc`
- `ilmn_lib_prep`
- `ont_lib_prep`
- `ilmn_seq_pool`
- `ont_seq_pool`
- `ilmn_start_seq_run`
- `ont_start_seq_run`

Atlas records intake outcomes first. Bloom accepts only Atlas-approved material, links that material to Atlas TRF/Test/process-item context through explicit graph-linked reference objects, and preserves lineage from specimen/container through plate and well placement, library prep, pooling, sequencing run creation, and sequenced library assignment.

Ursa resolves the canonical sequencing unit through Bloom with:

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

Public beta APIs return EUIDs only. Internal UUIDs are not part of the supported contract.

## Active Beta APIs

Atlas and Ursa integration paths live under:

- `/api/v1/external/atlas`
- `/api/v1/external/atlas/beta`

The queue-driven beta endpoints are:

- `POST /api/v1/external/atlas/beta/materials`
- `POST /api/v1/external/atlas/beta/queues/{queue_name}/items/{material_euid}`
- `POST /api/v1/external/atlas/beta/extractions`
- `POST /api/v1/external/atlas/beta/post-extract-qc`
- `POST /api/v1/external/atlas/beta/library-prep`
- `POST /api/v1/external/atlas/beta/pools`
- `POST /api/v1/external/atlas/beta/runs`
- `GET /api/v1/external/atlas/beta/runs/{run_euid}/resolve?flowcell_id=...&lane=...&library_barcode=...`
- `POST /api/v1/external/atlas/tests/{test_euid}/status-events`

## Legacy Isolation

Legacy workflow and `do_action` code may still exist on disk for retired surfaces, but it is not part of the active beta integration path. If a codepath depends on workflow-step runtime, accession ownership, or UUID-based external contracts, it is not part of the supported beta system.

## Development

Bloom runs on the TapDB-backed adapter layer used across the LSMC refactor. The beta queue flow uses explicit object creation, lineage writes, targeted lookup queries, process-item references, and idempotency keys on direct integration calls.

Focused validation commands for the beta path:

```bash
source bloom_activate.sh
pytest --no-cov tests/test_api_atlas_bridge.py tests/test_atlas_lookup_resilience.py tests/test_queue_flow.py tests/test_run_resolver.py tests/test_beta_cross_repo_smoke.py
ruff check bloom_lims tests
```

## Cross-Repo References

- active Bloom beta API contract: [docs/bloom_beta_api_contracts.md](/Users/jmajor/projects/lims3/bloom/docs/bloom_beta_api_contracts.md)
- queue/runtime execution summary: [docs/bloom_queue_refactor_execplan.md](/Users/jmajor/projects/lims3/bloom/docs/bloom_queue_refactor_execplan.md)
- parent beta contract: [/Users/jmajor/projects/lims3/_refactor/cross_repo_contracts.md](/Users/jmajor/projects/lims3/_refactor/cross_repo_contracts.md)
