# Bloom Beta API Contracts

## Accepted Material Registration

Bloom accepts Atlas-approved material only after Atlas records an `ACCEPTED` intake outcome and materializes one or more test process items.

Minimum request context:

- `trf_euid`
- `test_euids[]`
- patient context
- shipment or test kit context
- queue intent
- idempotency key

Bloom persists Atlas linkage through graph-linked reference objects and returns EUID-only identifiers for created material plus `process_item_euids[]`.

Implemented endpoint:

- `POST /api/v1/external/atlas/beta/materials`

## Queue Names

Canonical beta queues:

- `extraction_prod`
- `extraction_rnd`
- `post_extract_qc`
- `ilmn_lib_prep`
- `ont_lib_prep`
- `ilmn_seq_pool`
- `ont_seq_pool`
- `ilmn_start_seq_run`
- `ont_start_seq_run`

## Resolver

Input:

- `run_euid`
- `flowcell_id`
- `lane`
- `library_barcode`

Output:

- `sequenced_library_assignment_euid`
- `atlas_tenant_id`
- `atlas_trf_euid`
- `atlas_test_euid`
- `atlas_test_process_item_euid`

Rules:

- response is deterministic and replay-safe
- response contains no private UUIDs
- resolver traverses Bloom lineage and graph-linked reference objects
- one full resolver key maps to exactly one sequenced library assignment

Implemented endpoint:

- `GET /api/v1/external/atlas/beta/runs/{run_euid}/resolve?flowcell_id=...&lane=...&library_barcode=...`

Other queue-driven beta endpoints:

- `POST /api/v1/external/atlas/beta/queues/{queue_name}/items/{material_euid}`
- `POST /api/v1/external/atlas/beta/extractions`
- `POST /api/v1/external/atlas/beta/post-extract-qc`
- `POST /api/v1/external/atlas/beta/library-prep`
- `POST /api/v1/external/atlas/beta/pools`
- `POST /api/v1/external/atlas/beta/runs`
- `POST /api/v1/external/atlas/tests/{test_euid}/status-events`

## Status And Reliability

- Bloom-to-Atlas status publishing remains replay-safe
- direct beta calls remain deterministic and idempotent
- repeated accepted-material requests with the same idempotency key must not create duplicate material records
