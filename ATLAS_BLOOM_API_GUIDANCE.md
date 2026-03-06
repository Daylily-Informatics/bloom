# Atlas ↔ Bloom API Guidance

Audience: Atlas backend integration engineers

This guide documents how Atlas should integrate with Bloom for container/specimen lifecycle operations using Bloom's current API surface.

## 1. Integration Summary

- Most common path:
1. Create empty container.
2. Later fill that container with a specimen.
- Alternative path:
1. Create specimen and container in one call.

Current defaults and constraints:
- Supported specimen templates for this integration:
1. `content/specimen/blood-whole/1.0`
2. `content/specimen/buccal-swab/1.0`
- `saliva` is not currently available as a specimen template in Bloom.
- No order-alert subscription/webhook endpoint exists yet. Use polling (documented below).

Transport policy:
- Bloom is HTTPS-only for all inbound requests. `http://` calls are rejected with `426 Upgrade Required`.
- Bloom outbound Atlas integration is HTTPS-only. Configure local Atlas as:
  - `https://localhost:8915`

## 2. Authentication Prerequisites

Atlas should use a Bloom-issued bearer token:

```http
Authorization: Bearer blm_<token>
```

Token management endpoints:
- Self-service (user in `API_ACCESS` group):
1. `POST /api/v1/user-tokens`
2. `GET /api/v1/user-tokens`
3. `DELETE /api/v1/user-tokens/{token_id}`
- Admin-managed:
1. `GET /api/v1/admin/user-tokens`
2. `DELETE /api/v1/admin/user-tokens/{token_id}`
3. Group membership management under `/api/v1/admin/groups/...`
4. Tool API user lifecycle:
5. `GET /api/v1/admin/tool-api-users`
6. `POST /api/v1/admin/tool-api-users` (optionally issues initial token)
7. `POST /api/v1/admin/tool-api-users/{tool_user_id}/tokens` (grant additional token)

Admin tool-user defaults:
- role defaults to `INTERNAL_READ_WRITE` + `API_ACCESS`
- default token TTL is 30 days (configurable in Bloom)
- tool users are restricted to `INTERNAL_READ_ONLY` or `INTERNAL_READ_WRITE`

Recommended token scope for Atlas write flows:
- `internal_rw` (or `admin`)

## 2.1 Atlas Lookup Endpoints (Bloom Validation)

Bloom should validate Atlas references using Atlas integration lookup routes first:

1. `GET /api/integrations/bloom/v1/lookups/orders/{order_number}`
2. `GET /api/integrations/bloom/v1/lookups/patients/{patient_id}`
3. `GET /api/integrations/bloom/v1/lookups/shipments/{shipment_number}`
4. `GET /api/integrations/bloom/v1/lookups/testkits/{kit_barcode}`

For transition diagnostics only, Bloom may fallback to legacy Atlas paths with warning logs.

## 3. Template Discovery (Dynamic)

Atlas can discover available categories/types/subtypes via:

1. `GET /api/v1/object-creation/categories`
2. `GET /api/v1/object-creation/types?category=<category>`
3. `GET /api/v1/object-creation/subtypes?category=<category>&type=<type>`
4. Optional details: `GET /api/v1/object-creation/template?category=...&type=...&subtype=...&version=...`

Example specimen template targets:
- Blood: `content/specimen/blood-whole/1.0`
- Buccal: `content/specimen/buccal-swab/1.0`

## 4. API Recipes

Base URL examples below assume:
- `https://<bloom-host>`

### 4.1 Create Empty Container (Most Common First Step)

Endpoint:
- `POST /api/v1/object-creation/create`

Request:

```bash
curl -X POST "https://<bloom-host>/api/v1/object-creation/create" \
  -H "Authorization: Bearer blm_<token>" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "container",
    "type": "tube",
    "subtype": "tube-generic-10ml",
    "version": "1.0",
    "name": "Atlas Intake Tube",
    "properties": {
      "lab_code": "ATLAS-INTAKE",
      "comments": "Created empty; specimen to be added later"
    }
  }'
```

Response (example):

```json
{
  "euid": "CX-123",
  "uuid": "5f79fa27-2ef0-4d6f-baa0-1eaf5c93cbca",
  "name": "Atlas Intake Tube",
  "category": "container",
  "type": "tube",
  "subtype": "tube-generic-10ml",
  "message": "Successfully created CX-123"
}
```

Atlas should persist:
- `container_euid`
- `container_uuid`

### 4.2 Fill Existing Container With Biospecimen

Endpoint:
- `POST /api/v1/external/specimens`

Notes:
- Send `container_euid` to attach specimen to an existing container.
- Use `Idempotency-Key` for retry safety.

Request:

```bash
curl -X POST "https://<bloom-host>/api/v1/external/specimens" \
  -H "Authorization: Bearer blm_<token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: atlas-order-1001-specimen-1" \
  -d '{
    "specimen_template_code": "content/specimen/blood-whole/1.0",
    "specimen_name": "Order 1001 Blood Specimen",
    "container_euid": "CX-123",
    "status": "active",
    "properties": {
      "source_system": "atlas",
      "collection_site": "Clinic A"
    },
    "atlas_refs": {
      "order_number": "ORD-1001",
      "patient_id": "PAT-2001",
      "shipment_number": "SHP-3001",
      "kit_barcode": "KIT-4001"
    }
  }'
```

Idempotency behavior:
- If the same `Idempotency-Key` is replayed, Bloom returns the original specimen record rather than creating a duplicate.

### 4.3 Create Container + Specimen In One Call

Endpoint:
- `POST /api/v1/external/specimens`

Notes:
- Omit `container_euid`.
- Set `container_template_code` so Bloom creates a new container and links the specimen.

Request:

```bash
curl -X POST "https://<bloom-host>/api/v1/external/specimens" \
  -H "Authorization: Bearer blm_<token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: atlas-order-1002-specimen-1" \
  -d '{
    "specimen_template_code": "content/specimen/buccal-swab/1.0",
    "specimen_name": "Order 1002 Buccal Specimen",
    "container_template_code": "container/tube/tube-generic-10ml/1.0",
    "status": "active",
    "properties": {
      "source_system": "atlas"
    },
    "atlas_refs": {
      "order_number": "ORD-1002",
      "patient_id": "PAT-2002",
      "package_number": "PKG-3002",
      "kit_barcode": "KIT-4002"
    }
  }'
```

### 4.4 Query Biospecimen By EUID

Endpoint:
- `GET /api/v1/external/specimens/{specimen_euid}`

Request:

```bash
curl -X GET "https://<bloom-host>/api/v1/external/specimens/SP-901" \
  -H "Authorization: Bearer blm_<token>"
```

### 4.5 Edit Biospecimen By EUID

Endpoint:
- `PATCH /api/v1/external/specimens/{specimen_euid}`

Supported update fields:
- `specimen_name`
- `status`
- `properties`
- `atlas_refs`
- `container_euid` (to link specimen to a different existing container)

Request:

```bash
curl -X PATCH "https://<bloom-host>/api/v1/external/specimens/SP-901" \
  -H "Authorization: Bearer blm_<token>" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "in_progress",
    "properties": {
      "received_by": "lab-tech-2",
      "condition_on_receipt": "acceptable"
    },
    "atlas_refs": {
      "order_number": "ORD-1001",
      "patient_id": "PAT-2001",
      "shipment_number": "SHP-3001"
    }
  }'
```

### 4.6 Delete Biospecimen By EUID

Current deletion path:
- `DELETE /api/v1/content/{euid}`

Notes:
- This is the current delete route for specimens.
- There is no `DELETE /api/v1/external/specimens/{specimen_euid}` route yet.
- Soft delete is default.
- Hard delete uses `?hard_delete=true` and should be used with caution.

Soft delete request:

```bash
curl -X DELETE "https://<bloom-host>/api/v1/content/SP-901" \
  -H "Authorization: Bearer blm_<token>"
```

Hard delete request (caution):

```bash
curl -X DELETE "https://<bloom-host>/api/v1/content/SP-901?hard_delete=true" \
  -H "Authorization: Bearer blm_<token>"
```

### 4.7 Find Specimens By Order/Reference

Endpoint:
- `GET /api/v1/external/specimens/by-reference`

Supported query keys:
- `order_number`
- `patient_id`
- `shipment_number`
- `package_number` (alias; normalized to shipment internally)
- `kit_barcode`

Examples:

```bash
curl -X GET "https://<bloom-host>/api/v1/external/specimens/by-reference?order_number=ORD-1001" \
  -H "Authorization: Bearer blm_<token>"
```

```bash
curl -X GET "https://<bloom-host>/api/v1/external/specimens/by-reference?patient_id=PAT-2001&kit_barcode=KIT-4001" \
  -H "Authorization: Bearer blm_<token>"
```

## 5. Order Alerts: Polling Workaround (Current State)

Bloom does not currently provide a native order-alert subscription or webhook endpoint.

Recommended strategy:
1. Poll `GET /api/v1/external/specimens/by-reference?order_number=<ORDER>` every 30-120 seconds.
2. Use bounded exponential backoff for transient failures (for example: 30s, 60s, 120s max).
3. Deduplicate by `specimen_euid` plus a state hash (for example: status + atlas refs + selected properties).
4. Persist a local checkpoint (`last_polled_at`, last seen specimen states) in Atlas.
5. Treat empty results as "no linked specimens yet", not an error.

## 6. Error Handling Contract

| Endpoint Family | 400 | 401 | 404 | 424 | 500 |
|---|---|---|---|---|---|
| `/api/v1/object-creation/*` | invalid request fields/path components | missing/invalid auth | template/category/type/subtype not found | n/a | internal error |
| `/api/v1/external/specimens` (POST/PATCH) | invalid payload/template/reference values | missing/invalid `blm_` token | n/a | Atlas validation dependency failure | internal error |
| `/api/v1/external/specimens/{euid}` (GET) | n/a | missing/invalid `blm_` token | specimen not found | n/a | internal error |
| `/api/v1/content/{euid}` (DELETE) | invalid delete options | missing/invalid auth | content not found | n/a | internal error |

Retry guidance for Atlas:
- Retry with bounded backoff:
1. `5xx`
2. `424`
- Do not retry blindly:
1. `400` (fix payload)
2. `401` (fix token/auth)
3. `404` (verify identifiers)

## 7. Operational Notes

### 7.1 Data Atlas Must Persist

| Field | Why |
|---|---|
| `container_euid` | Required to re-link/update specimen placement later |
| `specimen_euid` | Primary key for Bloom specimen lifecycle operations |
| `specimen_uuid` | Secondary stable identifier for traceability |
| `atlas_refs` | Cross-system reconciliation and lookup |
| `idempotency_key` used | Safe retries without duplication |

### 7.2 Unsupported Currently

| Item | Current State |
|---|---|
| Saliva specimen template | Not currently present in Bloom template config |
| Order alert subscription/webhook | Not currently available; use polling workaround |

## 8. Verification Checklist (Manual/API Smoke)

1. Empty container creation returns `200` and valid container `euid`.
2. Fill-later flow links specimen to existing `container_euid`.
3. Query-by-EUID returns created specimen record.
4. Patch-by-EUID updates `status` and `properties`.
5. Delete-by-EUID soft deletes specimen via content endpoint.
6. By-reference lookup returns specimen for target order.
7. Polling workflow is operational using `by-reference` endpoint.
8. External specimen endpoints return `401` when token is missing/invalid.

## 9. Notes On Saliva

Atlas should not send saliva as a specimen template code in production integration until Bloom exposes a saliva-specific template.  
Current supported specimen template choices for this guide are blood and buccal only.

## 10. Bloom -> Atlas Query/Status Integration (Internal Bloom Flows)

Bloom-side Atlas query/status calls use:

1. `Authorization: Bearer <atlas_integration_token>`
2. `X-Atlas-Tenant-Id: <atlas.organization_id>`

In this phase, Bloom treats Atlas calls as single-tenant and resolves tenant UUID from Bloom config (`atlas.organization_id`).

### 10.1 Container EUID -> TRF Context

Bloom calls:

1. `GET /api/integrations/bloom/v1/lookups/containers/{container_euid}/trf-context`

This is used when container-linked specimen operations need Atlas TRF context for order/patient/test-order validation.

### 10.2 Manual Test-Order Status Push From Bloom

Bloom exposes:

1. `POST /api/v1/external/atlas/test-orders/{test_order_id}/status-events`

Request body mirrors Atlas status-event contract:

1. `event_id`
2. `status` (`IN_PROGRESS|COMPLETED|FAILED|ON_HOLD|CANCELED|REJECTED`)
3. `occurred_at`
4. optional: `reason`, `container_euid`, `specimen_euid`, `metadata`

Optional header:

1. `Idempotency-Key`

When omitted, Bloom computes:

1. `sha256("{tenant_id}:{test_order_id}:{event_id}:{status}")`

### 10.3 Status Push Retry Behavior

Bloom retries with exponential backoff + jitter on:

1. `429`
2. `500`
3. `502`
4. `503`
5. `504`

Bloom does not retry (without request/data/token changes) on:

1. `400`
2. `401`
3. `403`
4. `404`
5. `409`
