# Bloom

Bloom is the LSMC beta authority for physical and material LIMS state.

Bloom owns:

- containers
- specimens
- plates and wells
- extraction outputs
- library prep outputs
- pools
- sequencing runs
- queue membership and queue-transition state for wet-lab execution

Bloom does not own:

- accessioning
- customer, order, patient, provider, shipment, or kit truth
- workflow or workflow-step orchestration for the beta path

## Beta Architecture

The active beta path is queue-driven.

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

Atlas records intake outcomes first. Bloom accepts only Atlas-approved material, stores explicit Atlas external links on Bloom-owned objects, and preserves lineage from specimen and container through plate and well placement, library prep, pooling, and sequencing run creation.

Ursa resolves `run_euid + index_string` through Bloom and receives:

- `atlas_tenant_id`
- `atlas_order_euid`
- `atlas_test_order_euid`

Public beta APIs return EUIDs only. Internal UUIDs are not part of the supported contract.

## Active Beta APIs

Atlas and Ursa integration paths live under:

- `/api/v1/external/specimens`
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
- `GET /api/v1/external/atlas/beta/runs/{run_euid}/resolve?index_string=...`

## Legacy Isolation

Legacy workflow and `do_action` code still exists in the repo for non-beta surfaces and historical GUI paths, but it is not on the active beta integration route. The old `/api/v1/actions/execute` API has been retired from the active API surface.

If a codepath depends on workflow-step runtime, accession ownership, or UUID-based external contracts, it is not part of the supported beta system.

## Development

Bloom runs on the TapDB-backed adapter layer used across the LSMC refactor. The beta queue flow uses explicit object creation, lineage writes, targeted lookup queries, and idempotency keys on direct integration calls.

Focused validation commands for the beta refactor:

```bash
source bloom_activate.sh
pytest tests/test_api_atlas_bridge.py tests/test_atlas_lookup_resilience.py tests/test_queue_flow.py tests/test_run_resolver.py
ruff check bloom_lims tests
```

## Remaining Shared-Library Gap

Bloom no longer uses the retired API-level `do_action` route for beta execution, but the repo still lacks first-class TapDB modern action templates dedicated to the new lab-operation events. That shared-library gap is documented in [docs/tapdb_required_changes.md](/Users/jmajor/projects/lims3/bloom/docs/tapdb_required_changes.md).
