# Bloom Auth + Atlas Integration

This document describes Bloom's token-first external API model and Atlas integration contract.

## RBAC Model

Bloom roles:
- `READ_ONLY`
- `READ_WRITE`
- `ADMIN`

Bloom permissions:
- `bloom:read`
- `bloom:write`
- `bloom:admin`
- `token:self_manage`
- `token:admin_manage`

System groups:
- `bloom-readonly`
- `bloom-readwrite`
- `bloom-admin`
- `bloom-rnd`
- `bloom-clinical`
- `bloom-auditor`
- `API_ACCESS`
- `ENABLE_ATLAS_API`
- `ENABLE_URSA_API`

`API_ACCESS` gates personal API token self-service. Admin users can always manage tokens.

## Embedded TapDB Admin Auth Boundary

Bloom can mount TapDB admin in-process at `/admin/tapdb`.

Mounted mode defaults:
- enabled unless `BLOOM_TAPDB_MOUNT_ENABLED=0`
- mount path defaults to `BLOOM_TAPDB_MOUNT_PATH=/admin/tapdb`

Auth behavior for mounted path:
- Bloom session/user model is the only gate
- admin-only access (`user_data.role == "admin"` or role set contains `ADMIN`)
- browser unauthenticated -> redirect `/login`
- browser non-admin -> redirect `/user_home?admin_required=1`
- API/XHR-style denied access -> JSON `401`/`403`

TapDB-local auth in mounted mode:
- Bloom injects an explicit mounted-user identity into the embedded TapDB app
- TapDB login flow is bypassed for mounted requests without mutating `TAPDB_ADMIN_*`
- standalone TapDB usage remains unchanged outside Bloom

## API Tokens

Bloom personal API tokens:
- prefix: `blm_`
- stored as SHA256 hashes only
- plaintext token returned only once at create-time
- revisioned status model: `ACTIVE`, `EXPIRED`, `REVOKED`
- usage logs are persisted per request

Scopes:
- `internal_ro`
- `internal_rw`
- `admin`

Scope limits are role-capped:
- read-only users: `internal_ro`
- read/write users: `internal_ro`, `internal_rw`
- admins: all scopes

## Endpoints

Self-service:
- `GET /api/v1/user-tokens`
- `POST /api/v1/user-tokens`
- `DELETE /api/v1/user-tokens/{token_id}`
- `GET /api/v1/user-tokens/{token_id}/usage`

Admin:
- `GET /api/v1/admin/groups`
- `GET /api/v1/admin/groups/{group_code}/members`
- `POST /api/v1/admin/groups/{group_code}/members`
- `DELETE /api/v1/admin/groups/{group_code}/members/{user_id}`
- `GET /api/v1/admin/user-tokens`
- `DELETE /api/v1/admin/user-tokens/{token_id}`
- `GET /api/v1/admin/user-tokens/{token_id}/usage`

Auth context:
- `GET /api/v1/auth/me` now includes `roles`, `groups`, `permissions`, and `auth_source`.

## Legacy API Key Behavior

`X-API-Key` legacy auth is disabled by default.

To allow it in local development only:
- `BLOOM_ALLOW_LEGACY_API_KEY=true`
- environment must resolve to `development`

In non-development environments, `X-API-Key` is ignored.

## Atlas Read Integration

Bloom reads Atlas references via configured service credentials:
- `BLOOM_ATLAS__BASE_URL`
- `BLOOM_ATLAS__TOKEN`
- `BLOOM_ATLAS__TIMEOUT_SECONDS` (default `10`)
- `BLOOM_ATLAS__CACHE_TTL_SECONDS` (default `300`)
- `BLOOM_ATLAS__VERIFY_SSL` (default `true`)

Lookups:
- preferred TRF: `/api/integrations/bloom/v1/lookups/trfs/{trf_euid}`
- preferred patient: `/api/integrations/bloom/v1/lookups/patients/{patient_id}`
- preferred shipment/package: `/api/integrations/bloom/v1/lookups/shipments/{shipment_number}`
- preferred testkit barcode: `/api/integrations/bloom/v1/lookups/testkits/{barcode}`

Cache behavior:
- successful lookups are TTL-cached
- if Atlas is temporarily unavailable and cache entry is still valid, cached value is returned with stale metadata
- if Atlas is unavailable with no valid cache for required validation, Bloom returns dependency failure (`424`)

## External Specimen API (Atlas -> Bloom)

Token-auth required (`Bearer blm_...`):
- `POST /api/v1/external/specimens`
- `GET /api/v1/external/specimens/{specimen_euid}`
- `PATCH /api/v1/external/specimens/{specimen_euid}`
- `GET /api/v1/external/specimens/by-reference`

Behavior summary:
- validates Atlas references before create/update
- creates/updates Bloom specimen content
- ensures container linkage
- stores references at `json_addl.properties.atlas_refs`
- supports idempotent create via `Idempotency-Key` header

## Bloom -> Atlas Query/Status Integration

Bloom outbound Atlas query/status flows use the same Atlas integration bearer token and are single-tenant in this phase.

Required config:
- `BLOOM_ATLAS__BASE_URL`
- `BLOOM_ATLAS__TOKEN`
- `BLOOM_ATLAS__ORGANIZATION_ID` (used as `X-Atlas-Tenant-Id`)
- `BLOOM_ATLAS__TIMEOUT_SECONDS`
- `BLOOM_ATLAS__VERIFY_SSL`
- `BLOOM_ATLAS__STATUS_EVENTS_TIMEOUT_SECONDS` (default `10`)
- `BLOOM_ATLAS__STATUS_EVENTS_MAX_RETRIES` (default `5`)
- `BLOOM_ATLAS__STATUS_EVENTS_BACKOFF_BASE_SECONDS` (default `0.5`)

Bloom outbound endpoints used:
- `GET /api/integrations/bloom/v1/lookups/containers/{container_euid}/trf-context`
- `POST /api/integrations/bloom/v1/tests/{test_euid}/status-events`

Bloom manual bridge endpoint:
- `POST /api/v1/external/atlas/tests/{test_euid}/status-events`

Manual bridge behavior:
- requires Bloom token auth and write permission
- accepts Atlas status-event payload contract
- accepts optional `Idempotency-Key`
- computes deterministic idempotency key when header is omitted:
  - `sha256("{tenant_id}:{test_euid}:{event_id}:{status}")`

Retry behavior for status pushes:
- retry: `429`, `500`, `502`, `503`, `504`
- no retry: `400`, `401`, `403`, `404`, `409`
