# Bloom APIs

This document describes the current HTTP surface that the Bloom app mounts today. It is grounded in `bloom_lims/api/v1/__init__.py`, the router modules under `bloom_lims/api/v1/`, and the current API-focused test suite.

## API Design Rules

Current API behavior has a few consistent patterns:

- The primary contract is versioned under `/api/v1`.
- Payloads are EUID-centered. Many tests explicitly assert that internal UUID fields are not exposed in response payloads.
- Read/write authorization is RBAC-based, with three main roles: `READ_ONLY`, `READ_WRITE`, and `ADMIN`.
- External integration routes add group gates on top of token auth, especially `API_ACCESS`, `ENABLE_ATLAS_API`, and `ENABLE_URSA_API`.
- Idempotency is used where duplicate external calls would be dangerous, especially external specimen creation and Atlas status-event push.
- Legacy search v1 routes are removed. Use `/api/v1/search/v2/*`.

## Auth Model

Bloom uses two main auth modes for HTTP APIs:

### General API Auth

Most `/api/v1` routes depend on `require_api_auth`, which resolves:

- the current user identity
- `role` and `roles`
- `groups`
- `permissions`
- `auth_source`

`GET /api/v1/auth/me` is the easiest way to inspect the resolved context:

```json
{
  "email": "user@example.com",
  "user_id": "user-123",
  "role": "READ_WRITE",
  "roles": ["READ_WRITE"],
  "groups": ["API_ACCESS"],
  "permissions": ["bloom:read", "bloom:write", "token:self_manage"],
  "auth_source": "token"
}
```

### External Integration Auth

External integration routes use bearer-token auth and then enforce additional gates:

- `require_external_token_auth`: token auth only, no browser session fallback
- `require_external_atlas_api_enabled`: token auth plus `ENABLE_ATLAS_API`
- `require_external_ursa_api_enabled`: token auth plus `ENABLE_URSA_API`

For Atlas-facing automation, a valid bearer token is necessary but not sufficient. The token owner also needs the right service groups.

## Route Groups

| Route group | Prefix | Auth shape | Stability |
| --- | --- | --- | --- |
| Auth | `/api/v1/auth` | general API auth | stable |
| Objects | `/api/v1/objects` | read or write depending on verb | stable |
| Containers | `/api/v1/containers` | read or write depending on verb | stable |
| Content | `/api/v1/content` | read or write depending on verb | stable |
| Templates | `/api/v1/templates` | general API auth | stable |
| Subjects | `/api/v1/subjects` | general API auth | stable |
| Lineages | `/api/v1/lineages` | general API auth | stable |
| Object creation | `/api/v1/object-creation` | general API auth | stable |
| Search v2 | `/api/v1/search/v2` | general API auth | stable |
| Stats | `/api/v1/stats` | general API auth | stable |
| Tracking | `/api/v1/tracking` | general API auth | stable, FedEx-centric |
| User tokens | `/api/v1/user-tokens` | general API auth | stable |
| Admin auth | `/api/v1/admin/groups`, `/api/v1/admin/user-tokens` | admin-oriented API auth | operator-facing |
| Execution queue | `/api/v1/execution` | read/write/admin by action | operator-facing |
| Batch jobs | `/api/v1/batch` | general API auth | operator-facing |
| Async tasks | `/api/v1/tasks` | general API auth | operator-facing |
| Graph v1 | `/api/v1/graph` | general API auth | minimal stable surface |
| External specimens | `/api/v1/external/specimens` | external token auth plus Atlas enablement | integration-specific |
| Atlas bridge | `/api/v1/external/atlas` | external token auth plus Atlas enablement | integration-specific |
| Beta lab | `/api/v1/external/atlas/beta` | external token auth plus Atlas enablement | beta/integration-specific |

Not mounted today:

- `/api/v1/workflows/*`
- `/api/v1/worksets/*`

The code still contains workflow/workset modules, but the current router does not include them.

## Core Object APIs

### Object Creation

`/api/v1/object-creation` is the template-aware creation helper surface. It exposes:

- `/categories`
- `/types`
- `/subtypes`
- `/template`
- `/create`

Example:

```bash
curl -k https://localhost:8912/api/v1/object-creation/create \
  -H "Authorization: Bearer <blm-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "container",
    "type": "tube",
    "subtype": "tube-generic-10ml",
    "version": "1.0",
    "name": "atlas-contract-tube"
  }'
```

This pattern is important for integrations because it lets callers create valid material objects without needing to know Bloom's internal template storage details.

### Objects, Containers, And Content

These route families cover the concrete material graph:

- `/api/v1/objects`
- `/api/v1/containers`
- `/api/v1/content`

Representative examples:

```bash
curl -k https://localhost:8912/api/v1/containers/ \
  -H "Authorization: Bearer <blm-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "template_euid": "BGT-123",
    "name": "coverage-container",
    "container_type": "tube"
  }'
```

```bash
curl -k https://localhost:8912/api/v1/content/samples \
  -H "Authorization: Bearer <blm-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "template_euid": "BGT-456",
    "name": "gdna-sample"
  }'
```

Container-content placement is handled through:

- `POST /api/v1/containers/{container_euid}/contents`
- `DELETE /api/v1/containers/{container_euid}/contents/{content_euid}`
- `GET /api/v1/containers/{euid}/layout`

## Search

Bloom's current search surface is unified search v2 under `/api/v1/search/v2`.

### Query

```bash
curl -k https://localhost:8912/api/v1/search/v2/query \
  -H "Authorization: Bearer <blm-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "sample",
    "record_types": ["instance", "template"],
    "page": 1,
    "page_size": 25
  }'
```

Current behavior from code and tests:

- returns `items`, `facets`, `page`, `page_size`, `total`, and `total_pages`
- supports mixed record types such as `instance`, `template`, `lineage`, and `audit`
- drives the modern GUI search page

### Export

`POST /api/v1/search/v2/export` supports:

- `format: "json"` or `format: "tsv"`
- `include_metadata`
- `max_export_rows`

Legacy `/api/v1/search` and `/api/v1/search/export` routes are removed.

## Graph And Lineage

### Versioned Graph API

The versioned graph router is intentionally small:

- `GET /api/v1/graph/data`
- `GET /api/v1/graph/object/{euid}`

Lineage management lives separately under `/api/v1/lineages`.

### GUI Graph Helper API

The richer graph viewer used by the GUI is not under `/api/v1`. It currently lives at:

- `GET /api/graph/data`
- `GET /api/object/{euid}`
- `GET /api/graph/external`
- `GET /api/graph/external/object`
- `POST /api/lineage`
- `DELETE /api/object/{euid}`

That split matters for clients. If you are writing service-to-service code, prefer the versioned routes. If you are extending the graph browser, you will also touch the GUI helper endpoints.

Example graph data response shape from tests:

```json
{
  "elements": {
    "nodes": [{"data": {"id": "N1", "category": "container", "color": "#8B00FF"}}],
    "edges": [{"data": {"id": "E1", "source": "N1", "target": "N2"}}]
  },
  "meta": {
    "start_euid": "AY1",
    "depth": 3
  }
}
```

## Execution Queue And Batch Surfaces

Queue-centric operator behavior is exposed under `/api/v1/execution`.

Representative reads:

- `GET /api/v1/execution/queues`
- `GET /api/v1/execution/queues/{queue_key}`
- `GET /api/v1/execution/queues/{queue_key}/items`
- `GET /api/v1/execution/workers`
- `GET /api/v1/execution/leases`
- `GET /api/v1/execution/dead-letter`

Representative actions:

- `POST /api/v1/execution/actions/register-worker`
- `POST /api/v1/execution/actions/heartbeat-worker`
- `POST /api/v1/execution/actions/claim`
- `POST /api/v1/execution/actions/complete`
- `POST /api/v1/execution/actions/fail`
- `POST /api/v1/execution/actions/hold`
- `POST /api/v1/execution/actions/requeue`

Example worker registration:

```bash
curl -k https://localhost:8912/api/v1/execution/actions/register-worker \
  -H "Authorization: Bearer <blm-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_key": "worker://pytest/demo-worker",
    "display_name": "Pytest Execution Worker",
    "worker_type": "SERVICE",
    "status": "ONLINE",
    "capabilities": ["wetlab.extraction"],
    "max_concurrent_leases": 2,
    "heartbeat_ttl_seconds": 120
  }'
```

Write actions on this surface require write permission. Tests explicitly check that read-only users get `403`.

`/api/v1/batch` and `/api/v1/tasks` are adjacent operator-facing surfaces for bulk operations and async task status, not the main public integration contract.

## External Atlas And Specimen APIs

These are the most important service-to-service endpoints in current Bloom.

### External Specimens

Current routes:

- `POST /api/v1/external/specimens`
- `GET /api/v1/external/specimens/by-reference`
- `GET /api/v1/external/specimens/{specimen_euid}`
- `PATCH /api/v1/external/specimens/{specimen_euid}`

Example create:

```bash
curl -k https://localhost:8912/api/v1/external/specimens \
  -H "Authorization: Bearer <blm-token>" \
  -H "Idempotency-Key: atlas-specimen-001" \
  -H "Content-Type: application/json" \
  -d '{
    "specimen_template_code": "content/specimen/blood-whole/1.0",
    "specimen_name": "specimen-demo",
    "status": "active",
    "container_template_code": "container/tube/tube-generic-10ml/1.0",
    "properties": {"source": "atlas-contract-test"},
    "atlas_refs": {
      "order_number": "ORD-123",
      "patient_id": "PAT-123",
      "kit_barcode": "KIT-123"
    }
  }'
```

Current behavior worth knowing:

- reference lookups support `trf_euid`, `patient_id`, `shipment_number`, `kit_barcode`, `atlas_tenant_id`, `atlas_trf_euid`, and `atlas_test_euid`
- specimen create and update trigger best-effort outbound Bloom events to Atlas
- container-context mismatches map to `400`
- upstream dependency failures map to `424`

### Atlas Status Event Push

Current route:

- `POST /api/v1/external/atlas/tests/{test_euid}/status-events`

This is a synchronous Bloom-to-Atlas bridge that wraps `AtlasService.push_test_status_event(...)`.

Example:

```bash
curl -k https://localhost:8912/api/v1/external/atlas/tests/TST-100/status-events \
  -H "Authorization: Bearer <blm-token>" \
  -H "Idempotency-Key: idem-123" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "bloom-status-evt-0001",
    "status": "IN_PROGRESS",
    "occurred_at": "2026-03-03T01:00:00Z",
    "reason": "Lab processing started",
    "container_euid": "BCN-RT",
    "specimen_euid": "BCT-B4",
    "metadata": {"source": "bloom", "workflow": "wgs"}
  }'
```

Current error mapping:

- malformed payload or missing event fields -> `400`
- missing Atlas tenant or upstream Atlas dependency problems -> `424`
- insufficient role -> `403`
- missing token auth -> `401`

### Beta Lab Surface

`/api/v1/external/atlas/beta` contains a richer queue-centric integration surface for beta lab flows. Current route families include:

- materials
- tubes
- queue item claim/release paths
- extractions
- post-extract QC
- library prep
- pools
- runs and run resolution

This is a real mounted surface with substantial tests, but its route naming and placement clearly mark it as beta/integration-specific rather than the most conservative public contract.

## Tokens And Admin APIs

### User Token Self-Service

Current routes:

- `GET /api/v1/user-tokens`
- `POST /api/v1/user-tokens`
- `DELETE /api/v1/user-tokens/{token_id}`
- `GET /api/v1/user-tokens/{token_id}/usage`

Tokens currently default to about 48 hours of lifetime when no explicit expiry is supplied.

### Admin Group And Token Management

Current routes:

- `GET /api/v1/admin/groups`
- `GET /api/v1/admin/groups/{group_code}/members`
- `POST /api/v1/admin/groups/{group_code}/members`
- `DELETE /api/v1/admin/groups/{group_code}/members/{member_user_id}`
- `GET /api/v1/admin/user-tokens`
- `POST /api/v1/admin/user-tokens/issue`
- `DELETE /api/v1/admin/user-tokens/{token_id}`
- `GET /api/v1/admin/user-tokens/{token_id}/usage`

These are operator-facing administrative APIs, not the main public integration entrypoint.

## Tracking And Other Supporting APIs

The remaining route groups round out the current service:

- `/api/v1/stats/dashboard`: dashboard rollup data
- `/api/v1/tracking/carriers`, `/api/v1/tracking/track/*`: carrier lookup surface
- `/api/v1/templates/by-category/{category}`: template browsing
- `/api/v1/subjects/{euid}/specimens`: subject-to-specimen lookup

Carrier tracking is currently pragmatic rather than deep. FedEx has the most concrete implementation; other carriers are placeholders or return "not yet implemented."

## Messaging And Integration Boundaries

Bloom's current messaging/integration story is narrow and explicit:

- synchronous HTTP APIs for service-to-service interaction
- outbound Atlas event emission through `bloom_lims.integrations.atlas.events`
- synchronous Atlas status-event push through the Atlas bridge API
- synchronous Dewey artifact registration through a client wrapper
- synchronous Zebra Day printer and print-job interactions

What Bloom does **not** have today is a generalized asynchronous event backbone that external consumers subscribe to directly. If you need state, call Bloom. If you need Bloom to notify Atlas, that happens through the specific Atlas event bridge paths described above.
