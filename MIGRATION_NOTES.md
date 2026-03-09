## Bloom TapDB `0.1.32` EUID-only migration

### What changed

- Public API responses no longer expose TapDB internal primary keys via `uuid`.
- External specimen responses no longer expose `specimen_uuid`.
- Public Atlas/event payload helpers for containers and content no longer emit internal ID fields.
- Lineage APIs now return and delete by lineage `euid`.
- Search v1/v2 JSON and TSV exports no longer include `uuid` columns or fields.
- Lineage `relationship_type` now comes from `generic_instance_lineage.relationship_type`.
- Public Pydantic response schemas no longer declare TapDB internal ID fields.

### Endpoints affected

- `POST /api/v1/object-creation/create`
  - removed response field: `uuid`
- `GET|POST /api/v1/containers...`
  - removed response field: `uuid`
- `GET|POST /api/v1/content...`
  - removed response fields: `uuid`, `specimen_uuid`
- `GET|POST /api/v1/objects...`
  - removed response field: `uuid`
- `GET|POST /api/v1/subjects...`
  - removed response field: `uuid`
- `GET|POST /api/v1/equipment...`
  - removed response field: `uuid`
- `GET|POST /api/v1/external/specimens...`
  - removed response field: `specimen_uuid`
- `GET|POST /api/v1/files...`
  - removed response field: `uuid`
- `GET|POST /api/v1/file-sets...`
  - removed response field: `uuid`
- `GET /api/v1/templates...`
  - removed response field: `uuid`
- `/api/v1/workflows/*`
  - retired for queue-centric Bloom beta
- `GET /api/v1/worksets/{euid}`
  - removed response field: `uuid`
- `GET /api/v1/search/`
  - removed item field: `uuid`
- `POST /api/v1/search/v2/query`
  - removed item field: `uuid`
- `POST /api/v1/search/v2/export`
  - removed JSON and TSV `uuid`
- `GET|POST /api/v1/lineages/`
  - replaced response field `uuid` with `euid`
- `DELETE /api/v1/lineages/{lineage_euid}`
  - path identifier is now lineage `euid`

### Client migration

- Replace any use of response `uuid` with `euid`.
- Replace any use of response `specimen_uuid` with `specimen_euid`.
- For lineage deletion, store the lineage `euid` returned by create/list and call `DELETE /api/v1/lineages/{lineage_euid}`.
- For search consumers, use `metadata.parent_instance_euid` and `metadata.child_instance_euid` instead of internal lineage IDs.
- If clients introspect Bloom response models or generated OpenAPI, regenerate them so `uuid`/`specimen_uuid` removals are reflected.

### Compatibility note

- Bloom no longer preserves internal `.uuid`/`*_uuid` compatibility aliases for TapDB ORM models.
- Runtime code now uses canonical TapDB 0.1.32 fields directly: `uid`, `template_uid`, `parent_instance_uid`, and `child_instance_uid`.

### `json_addl` backfill / tolerance

- No persisted data migration is required.
- Older lineage records may still have `relationship_type` duplicated in `json_addl`; API responses now read the canonical column value.
