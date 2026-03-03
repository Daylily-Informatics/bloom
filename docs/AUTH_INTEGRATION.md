# Bloom Auth + Atlas Integration

This document describes Bloom's token-first external API model and Atlas integration contract.

## RBAC Model

Bloom roles:
- `INTERNAL_READ_ONLY`
- `INTERNAL_READ_WRITE`
- `ADMIN`

Bloom permissions:
- `bloom:read`
- `bloom:write`
- `bloom:admin`
- `token:self_manage`
- `token:admin_manage`

System groups:
- `INTERNAL_READ_ONLY`
- `INTERNAL_READ_WRITE`
- `ADMIN`
- `API_ACCESS`

`API_ACCESS` gates personal API token self-service. Admin users can always manage tokens.

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
- preferred order: `/api/integrations/bloom/v1/lookups/orders/{order_number}`
- preferred patient: `/api/integrations/bloom/v1/lookups/patients/{patient_id}`
- preferred shipment/package: `/api/integrations/bloom/v1/lookups/shipments/{shipment_number}`
- preferred testkit barcode: `/api/integrations/bloom/v1/lookups/testkits/{barcode}`
- legacy fallbacks (with warning logs): `/api/orders/*`, `/api/patients/*`, `/api/shipments/*`, `/api/testkits/*`, then `/api/search/v2/query` for testkit fallback

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
