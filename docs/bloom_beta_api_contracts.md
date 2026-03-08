# Bloom Beta API Contracts

## Accepted Material Registration

Bloom accepts Atlas-approved material only after Atlas records an `ACCEPTED` intake outcome.

Minimum request context:

- Atlas identity context for the accepted item
- Atlas order EUID
- Atlas test-order EUID
- idempotency key

Bloom response must include EUID-only identifiers for created material and explicit Atlas-link metadata.

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
- `index_string`

Output:

- `atlas_tenant_id`
- `atlas_order_euid`
- `atlas_test_order_euid`

Rules:

- response is deterministic and replay-safe
- response contains no private UUIDs
- resolver uses Bloom lineage plus explicit Atlas external links

Implemented endpoint:

- `GET /api/v1/external/atlas/beta/runs/{run_euid}/resolve?index_string=...`

Other queue-driven beta endpoints:

- `POST /api/v1/external/atlas/beta/queues/{queue_name}/items/{material_euid}`
- `POST /api/v1/external/atlas/beta/extractions`
- `POST /api/v1/external/atlas/beta/post-extract-qc`
- `POST /api/v1/external/atlas/beta/library-prep`
- `POST /api/v1/external/atlas/beta/pools`
- `POST /api/v1/external/atlas/beta/runs`

## Status And Reliability

- Bloom-to-Atlas status publishing remains replay-safe
- direct beta calls remain deterministic and idempotent
- repeated accepted-material requests with the same idempotency key must not create duplicate material records
