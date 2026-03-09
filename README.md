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

## Timezone Policy

- Bloom persists/runtime-writes timestamps in UTC (`GMT+00:00`).
- UI display timezone is user-configurable via shared TapDB `system_user` preferences:
  - key: `display_timezone`
  - format: IANA timezone name
  - default: `UTC`
- Server-rendered templates and client-side timestamp formatting use the user preference.

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
The atomic business/fulfillment/reporting unit is `TRF.test`; `TRF` is a rollup container across child tests.
Accepted-material ingress queue membership is applied to the physical container (`container_euid`), with specimen queue reads falling back to containing-container queue state when needed.

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

### Atlas Configuration Values Required For Bloom API Access

When configuring Atlas to call Bloom, set all three fields below in Atlas Bloom integration settings:

- `bloom_base_url`
  - Bloom API base URL Atlas calls (example: `https://bloom.example.org`).
- `bloom_api_key_secret_ref`
  - Secret reference Atlas resolves to the Bloom bearer token (for example `env:MY_BLOOM_API_KEY`).
- `bloom_webhook_secret_ref`
  - Secret reference Atlas uses to verify Bloom webhook signatures for inbound events.

The queue-driven beta endpoints are:

- `POST /api/v1/external/atlas/beta/materials`
- `POST /api/v1/external/atlas/beta/queues/{queue_name}/items/{material_euid}`
- `POST /api/v1/external/atlas/beta/queues/{queue_name}/items/{material_euid}/claim`
- `POST /api/v1/external/atlas/beta/claims/{claim_euid}/release`
- `POST /api/v1/external/atlas/beta/materials/{material_euid}/reservations`
- `POST /api/v1/external/atlas/beta/reservations/{reservation_euid}/release`
- `POST /api/v1/external/atlas/beta/materials/{material_euid}/consume`
- `POST /api/v1/external/atlas/beta/extractions`
- `POST /api/v1/external/atlas/beta/post-extract-qc`
- `POST /api/v1/external/atlas/beta/library-prep`
- `POST /api/v1/external/atlas/beta/pools`
- `POST /api/v1/external/atlas/beta/runs`
- `GET /api/v1/external/atlas/beta/runs/{run_euid}/resolve?flowcell_id=...&lane=...&library_barcode=...`
- `POST /api/v1/external/atlas/tests/{test_euid}/status-events`

Execution metadata for extraction/QC/library-prep/pool/run and work-control events is normalized in-place:

- canonical keys: `operator`, `instrument_euid`, `method_version`, `reagent_euid`
- empty strings are stripped
- unknown keys are preserved
- `instrument_euid` and `reagent_euid` (when provided) are validated and written as lineage:
  - `beta_used_instrument`
  - `beta_used_reagent`

## Embedded TapDB Admin Mount

Bloom mounts the TapDB admin FastAPI surface inside the same Bloom server process at:

- `/admin/tapdb`

Mounted-mode behavior:

- Bloom session auth is the only gate.
- Access is admin-only (`role=admin`).
- Unauthenticated browser requests are redirected to `/login`.
- Authenticated non-admin browser requests are redirected to `/user_home?admin_required=1`.
- JSON/XHR-style denied requests receive `401` (unauthenticated) or `403` (non-admin).
- TapDB local login/auth flow is disabled for mounted mode.

Runtime flags:

- `BLOOM_TAPDB_MOUNT_ENABLED` (default `1`)
- `BLOOM_TAPDB_MOUNT_PATH` (default `/admin/tapdb`)

## Legacy Isolation

Workflow/workset runtime surfaces are retired from active API/GUI mounts for the beta path. Any codepath that depends on workflow-step runtime, accession ownership, or UUID-based external contracts is not part of the supported beta system.

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
