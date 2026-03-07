# Identifier Audit Report (`create_app()` Mounted Routes)

Generated: 2026-03-05 04:59:56 PST

## 1. Scope and Rules

- Route scope: mounted runtime routes from `bloom_lims.app.create_app()` only.
- Included ownership: routes whose handler module starts with `bloom_lims.`.
- Non-TapDB flagging rule: caller-supplied EUID used operationally for write/external flows before or without strict local resolution.
- This report is an audit artifact only; no API behavior changes are included.

## 2. Coverage Summary

| Metric | Value |
|---|---:|
| Total mounted routes audited | 203 |
| API routes (`/api/v1/*`) | 111 |
| GUI routes (all non-`/api/v1/*`) | 92 |
| API routes with identifier inputs | 77 |
| GUI routes with identifier inputs | 34 |

Coverage checks passed:
- Route row count == 203
- API row count == 111
- GUI row count == 92
- Each mounted method+path appears once in this report

## 3. High-Priority Findings (Non-TapDB EUID Operational Risk)

### 1. POST /api/v1/external/specimens

- Finding: `container_euid` is caller-supplied and can be used in Atlas TRF-context lookup before local Bloom container resolution.
- Evidence:
  - `bloom_lims/domain/external_specimens.py:43`
  - `bloom_lims/domain/external_specimens.py:45`
  - `bloom_lims/domain/external_specimens.py:274`
  - `bloom_lims/domain/external_specimens.py:276`
  - `bloom_lims/domain/external_specimens.py:179`
  - `bloom_lims/domain/external_specimens.py:180`

### 2. PATCH /api/v1/external/specimens/{specimen_euid}

- Finding: `payload.container_euid` can be consumed in Atlas validation path before container existence/type checks when `atlas_refs` is present.
- Evidence:
  - `bloom_lims/domain/external_specimens.py:113`
  - `bloom_lims/domain/external_specimens.py:116`
  - `bloom_lims/domain/external_specimens.py:274`
  - `bloom_lims/domain/external_specimens.py:276`
  - `bloom_lims/domain/external_specimens.py:122`
  - `bloom_lims/domain/external_specimens.py:123`

### 3. POST /api/v1/external/atlas/test-orders/{test_order_id}/status-events

- Finding: `container_euid` and `specimen_euid` are accepted in request body and forwarded to Atlas (`payload.model_dump(...)`) without local Bloom object resolution.
- Evidence:
  - `bloom_lims/schemas/atlas_bridge.py:23`
  - `bloom_lims/schemas/atlas_bridge.py:24`
  - `bloom_lims/api/v1/atlas_bridge.py:35`
  - `bloom_lims/api/v1/atlas_bridge.py:44`

### 4. POST /api/v1/external/containers/status/bulk

- Finding: Raw `container_euids` are operationally consumed for reconciliation lookups with only non-empty/dedup validation (no TapDB EUID format validation).
- Evidence:
  - `bloom_lims/api/v1/external_containers.py:18`
  - `bloom_lims/api/v1/external_containers.py:22`
  - `bloom_lims/api/v1/external_containers.py:51`
  - `bloom_lims/api/v1/external_containers.py:59`

## 4. API Inventory (111 routes)

| Method | Path | Handler | Identifier Inputs (name + location) | Expected Identifier Type | Operational Usage | Validation/Resolution Gate | Non-TapDB Operational Flag | Evidence |
|---|---|---|---|---|---|---|---|---|
| GET | /api/v1/ | bloom_lims.api.v1.api_v1_info | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/__init__.py:76 |
| POST | /api/v1/actions/aliquot | bloom_lims.api.v1.actions.create_aliquot | source_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | source_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions.py:41<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions.py:67 |
| POST | /api/v1/actions/execute | bloom_lims.api.v1.actions_execute.execute_action | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions_execute.py:23 |
| POST | /api/v1/actions/pool | bloom_lims.api.v1.actions.pool_content | source_euids (body) | tapdb_euid_candidate | local-read operational + local-write operational | source_euids: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions.py:152<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions.py:57 |
| POST | /api/v1/actions/transfer | bloom_lims.api.v1.actions.transfer_content | destination_euid (body)<br>source_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | source_euid: no strict local validation<br>destination_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions.py:108<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions.py:49<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/actions.py:50 |
| GET | /api/v1/admin/groups | bloom_lims.api.v1.admin_auth.list_groups | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:84 |
| GET | /api/v1/admin/groups/{group_code}/members | bloom_lims.api.v1.admin_auth.list_group_members | group_code (path) | external_business_id | display/filter only | group_code: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:110 |
| POST | /api/v1/admin/groups/{group_code}/members | bloom_lims.api.v1.admin_auth.add_group_member | user_id (body)<br>group_code (path) | external_business_id<br>generic_identifier | local-write operational | group_code: n/a<br>user_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:137<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:27 |
| DELETE | /api/v1/admin/groups/{group_code}/members/{member_user_id} | bloom_lims.api.v1.admin_auth.remove_group_member | group_code (path)<br>member_user_id (path) | external_business_id<br>generic_identifier | local-write operational | group_code: n/a<br>member_user_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:166 |
| GET | /api/v1/admin/tool-api-users | bloom_lims.api.v1.admin_auth.list_tool_api_users | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:288 |
| POST | /api/v1/admin/tool-api-users | bloom_lims.api.v1.admin_auth.create_tool_api_user | initial_token (body)<br>issue_initial_token (body) | token_or_idempotency | local-read operational + local-write operational | issue_initial_token: n/a<br>initial_token: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:321<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:44<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:45 |
| POST | /api/v1/admin/tool-api-users/{tool_user_id}/tokens | bloom_lims.api.v1.admin_auth.grant_tool_api_user_token | atlas_tenant_uuid (body)<br>token_name (body)<br>tool_user_id (path) | external_business_id<br>generic_identifier<br>token_or_idempotency<br>uuid | local-read operational + local-write operational | tool_user_id: n/a<br>token_name: n/a<br>atlas_tenant_uuid: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:390<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:50<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:55 |
| GET | /api/v1/admin/user-tokens | bloom_lims.api.v1.admin_auth.list_admin_user_tokens | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:195 |
| DELETE | /api/v1/admin/user-tokens/{token_id} | bloom_lims.api.v1.admin_auth.revoke_admin_user_token | token_id (path) | generic_identifier<br>token_or_idempotency | local-write operational | token_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:226 |
| GET | /api/v1/admin/user-tokens/{token_id}/usage | bloom_lims.api.v1.admin_auth.get_admin_token_usage | token_id (path) | generic_identifier<br>token_or_idempotency | local-read operational | token_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/admin_auth.py:255 |
| POST | /api/v1/auth/logout | bloom_lims.api.v1.auth.logout | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/auth.py:34 |
| GET | /api/v1/auth/me | bloom_lims.api.v1.auth.get_current_user | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/auth.py:18 |
| POST | /api/v1/batch/create | bloom_lims.api.v1.batch.bulk_create_objects | template_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | template_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:28<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:77 |
| POST | /api/v1/batch/delete | bloom_lims.api.v1.batch.bulk_delete_objects | euids (body) | tapdb_euid_candidate | local-read operational + local-write operational | euids: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:165<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:51 |
| GET | /api/v1/batch/jobs | bloom_lims.api.v1.batch.list_batch_jobs | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:206 |
| GET | /api/v1/batch/jobs/{job_id} | bloom_lims.api.v1.batch.get_batch_job | job_id (path) | generic_identifier | local-read operational | job_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:229 |
| POST | /api/v1/batch/jobs/{job_id}/cancel | bloom_lims.api.v1.batch.cancel_batch_job | job_id (path) | generic_identifier | local-read operational + local-write operational | job_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:255 |
| POST | /api/v1/batch/update | bloom_lims.api.v1.batch.bulk_update_objects | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/batch.py:127 |
| GET | /api/v1/containers/ | bloom_lims.api.v1.containers.list_containers | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:64 |
| POST | /api/v1/containers/ | bloom_lims.api.v1.containers.create_container | parent_euid (body)<br>template_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational + external-call operational | template_euid: strict format validator<br>parent_euid: strict format validator | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:168<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/containers.py:89<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/containers.py:90 |
| POST | /api/v1/containers/bulk-create | bloom_lims.api.v1.containers.bulk_create_containers | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:459 |
| POST | /api/v1/containers/{container_euid}/contents | bloom_lims.api.v1.containers.add_content_to_container | container_euid (body)<br>object_euid (body)<br>container_euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | container_euid: no strict local validation<br>container_euid: strict format validator<br>object_euid: strict format validator | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:350<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/containers.py:140<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/containers.py:141 |
| DELETE | /api/v1/containers/{container_euid}/contents/{content_euid} | bloom_lims.api.v1.containers.remove_content_from_container | container_euid (path)<br>content_euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | container_euid: local existence resolution<br>content_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:371 |
| DELETE | /api/v1/containers/{euid} | bloom_lims.api.v1.containers.delete_container | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational + external-call operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:299 |
| GET | /api/v1/containers/{euid} | bloom_lims.api.v1.containers.get_container | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:117 |
| PATCH | /api/v1/containers/{euid} | bloom_lims.api.v1.containers.patch_container | euid (path) | tapdb_euid_candidate | local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:340 |
| PUT | /api/v1/containers/{euid} | bloom_lims.api.v1.containers.update_container | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational + external-call operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:207 |
| GET | /api/v1/containers/{euid}/layout | bloom_lims.api.v1.containers.get_container_layout | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/containers.py:404 |
| GET | /api/v1/content/ | bloom_lims.api.v1.content.list_content | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/content.py:56 |
| POST | /api/v1/content/reagents | bloom_lims.api.v1.content.create_reagent | template_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | template_euid: strict format validator | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/content.py:209<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/content.py:94 |
| POST | /api/v1/content/samples | bloom_lims.api.v1.content.create_sample | container_euid (body)<br>specimen_euid (body)<br>template_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | template_euid: strict format validator<br>specimen_euid: strict format validator<br>container_euid: strict format validator | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/content.py:139<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/content.py:42<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/content.py:44<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/content.py:45 |
| POST | /api/v1/content/specimens | bloom_lims.api.v1.content.create_specimen | source_id (body)<br>subject_id (body)<br>template_euid (body) | external_business_id<br>generic_identifier<br>tapdb_euid_candidate | local-read operational + local-write operational | template_euid: strict format validator<br>source_id: n/a<br>subject_id: n/a | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/content.py:174<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/content.py:64<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/content.py:71<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/content.py:74 |
| DELETE | /api/v1/content/{euid} | bloom_lims.api.v1.content.delete_content | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational + external-call operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/content.py:311 |
| GET | /api/v1/content/{euid} | bloom_lims.api.v1.content.get_content | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/content.py:106 |
| PUT | /api/v1/content/{euid} | bloom_lims.api.v1.content.update_content | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational + external-call operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/content.py:244 |
| GET | /api/v1/downloads/{token} | bloom_lims.api.v1.downloads.download_tmp_file | token (path) | token_or_idempotency | display/filter only | token: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/downloads.py:17 |
| GET | /api/v1/equipment/ | bloom_lims.api.v1.equipment.list_equipment | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/equipment.py:36 |
| POST | /api/v1/equipment/ | bloom_lims.api.v1.equipment.create_equipment | template_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | template_euid: strict format validator | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/equipment.py:122<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/equipment.py:70 |
| GET | /api/v1/equipment/{euid} | bloom_lims.api.v1.equipment.get_equipment | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/equipment.py:85 |
| POST | /api/v1/equipment/{euid}/maintenance | bloom_lims.api.v1.equipment.record_maintenance | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/equipment.py:150 |
| POST | /api/v1/external/atlas/test-orders/{test_order_id}/status-events | bloom_lims.api.v1.atlas_bridge.push_test_order_status_event | container_euid (body)<br>event_id (body)<br>specimen_euid (body)<br>idempotency_key (header)<br>test_order_id (path) | external_business_id<br>generic_identifier<br>tapdb_euid_candidate<br>token_or_idempotency | local-write operational + external-call operational | test_order_id: n/a<br>event_id: n/a<br>container_euid: no strict local validation<br>specimen_euid: no strict local validation<br>idempotency_key: n/a | Yes | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/atlas_bridge.py:29<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/atlas_bridge.py:12<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/atlas_bridge.py:23<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/atlas_bridge.py:24 |
| POST | /api/v1/external/containers/status/bulk | bloom_lims.api.v1.external_containers.bulk_container_status | container_euids (body) | tapdb_euid_candidate | local-read operational | container_euids: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/external_containers.py:18<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/external_containers.py:38 |
| POST | /api/v1/external/specimens | bloom_lims.api.v1.external_specimens.create_external_specimen | container_euid (body)<br>idempotency_key (header) | tapdb_euid_candidate<br>token_or_idempotency | local-write operational + external-call operational | container_euid: no strict local validation<br>idempotency_key: n/a | Yes | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/external_specimens.py:79<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/external_specimens.py:28 |
| GET | /api/v1/external/specimens/by-reference | bloom_lims.api.v1.external_specimens.find_external_specimens_by_reference | kit_barcode (query)<br>order_number (query)<br>package_number (query)<br>patient_id (query)<br>shipment_number (query) | external_business_id<br>generic_identifier | local-read operational | order_number: n/a<br>patient_id: n/a<br>shipment_number: n/a<br>package_number: n/a<br>kit_barcode: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/external_specimens.py:113 |
| GET | /api/v1/external/specimens/{specimen_euid} | bloom_lims.api.v1.external_specimens.get_external_specimen | specimen_euid (path) | tapdb_euid_candidate | local-read operational | specimen_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/external_specimens.py:140 |
| PATCH | /api/v1/external/specimens/{specimen_euid} | bloom_lims.api.v1.external_specimens.update_external_specimen | container_euid (body)<br>specimen_euid (path) | tapdb_euid_candidate | local-read operational + local-write operational + external-call operational | specimen_euid: local existence resolution<br>container_euid: no strict local validation | Yes | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/external_specimens.py:157<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/external_specimens.py:53 |
| GET | /api/v1/file-sets/ | bloom_lims.api.v1.file_sets.list_file_sets | parent_euid (query) | tapdb_euid_candidate | local-read operational | parent_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/file_sets.py:43 |
| POST | /api/v1/file-sets/ | bloom_lims.api.v1.file_sets.create_file_set | parent_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | parent_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/file_sets.py:130<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/file_sets.py:31 |
| GET | /api/v1/file-sets/{euid} | bloom_lims.api.v1.file_sets.get_file_set | euid (path) | tapdb_euid_candidate | local-read operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/file_sets.py:86 |
| GET | /api/v1/files/ | bloom_lims.api.v1.files.list_files | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/files.py:35 |
| POST | /api/v1/files/ | bloom_lims.api.v1.files.create_file | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/files.py:115 |
| GET | /api/v1/files/{euid} | bloom_lims.api.v1.files.get_file | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/files.py:81 |
| POST | /api/v1/files/{file_euid}/link/{parent_euid} | bloom_lims.api.v1.files.link_file_to_parent | file_euid (path)<br>parent_euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | file_euid: no strict local validation<br>parent_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/files.py:156 |
| GET | /api/v1/lineages/ | bloom_lims.api.v1.lineages.list_lineages | child_euid (query)<br>parent_euid (query) | tapdb_euid_candidate | local-read operational | parent_euid: no strict local validation<br>child_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/lineages.py:41 |
| POST | /api/v1/lineages/ | bloom_lims.api.v1.lineages.create_lineage | child_euid (body)<br>parent_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | parent_euid: no strict local validation<br>child_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/lineages.py:30<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/lineages.py:31<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/lineages.py:97 |
| DELETE | /api/v1/lineages/{lineage_euid} | bloom_lims.api.v1.lineages.delete_lineage | lineage_euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | lineage_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/lineages.py:139 |
| GET | /api/v1/object-creation/categories | bloom_lims.api.v1.object_creation.list_categories | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/object_creation.py:101 |
| POST | /api/v1/object-creation/create | bloom_lims.api.v1.object_creation.create_object | - | - | local-read operational + local-write operational + external-call operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/object_creation.py:331 |
| GET | /api/v1/object-creation/subtypes | bloom_lims.api.v1.object_creation.list_subtypes | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/object_creation.py:185 |
| GET | /api/v1/object-creation/template | bloom_lims.api.v1.object_creation.get_template_details | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/object_creation.py:254 |
| GET | /api/v1/object-creation/types | bloom_lims.api.v1.object_creation.list_types | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/object_creation.py:136 |
| GET | /api/v1/objects/ | bloom_lims.api.v1.objects.list_objects | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/objects.py:36 |
| POST | /api/v1/objects/ | bloom_lims.api.v1.objects.create_object | container_euid (body)<br>lineage_euid (body)<br>parent_euid (body) | tapdb_euid_candidate | local-write operational | parent_euid: strict format validator<br>lineage_euid: strict format validator<br>container_euid: strict format validator | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/objects.py:141<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/objects.py:74<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/objects.py:75<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/schemas/objects.py:76 |
| DELETE | /api/v1/objects/{euid} | bloom_lims.api.v1.objects.delete_object | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/objects.py:294 |
| GET | /api/v1/objects/{euid} | bloom_lims.api.v1.objects.get_object | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/objects.py:103 |
| PUT | /api/v1/objects/{euid} | bloom_lims.api.v1.objects.update_object | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/objects.py:210 |
| GET | /api/v1/search/ | bloom_lims.api.v1.search.search_objects | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/search.py:66 |
| GET | /api/v1/search/export | bloom_lims.api.v1.search.export_search_results | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/search.py:142 |
| POST | /api/v1/search/v2/export | bloom_lims.api.v1.search_v2.search_v2_export | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/search_v2.py:40 |
| POST | /api/v1/search/v2/query | bloom_lims.api.v1.search_v2.search_v2_query | sort_order (body) | external_business_id | local-read operational + local-write operational | sort_order: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/search_v2.py:25<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/search/contracts.py:65 |
| GET | /api/v1/stats/dashboard | bloom_lims.api.v1.stats.get_dashboard_stats | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/stats.py:34 |
| GET | /api/v1/subjects/ | bloom_lims.api.v1.subjects.list_subjects | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:43 |
| POST | /api/v1/subjects/ | bloom_lims.api.v1.subjects.create_subject | external_id (body)<br>template_euid (body) | generic_identifier<br>tapdb_euid_candidate | local-read operational + local-write operational | template_euid: no strict local validation<br>external_id: n/a | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:120<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:30<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:32 |
| DELETE | /api/v1/subjects/{euid} | bloom_lims.api.v1.subjects.delete_subject | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:225 |
| GET | /api/v1/subjects/{euid} | bloom_lims.api.v1.subjects.get_subject | euid (path) | tapdb_euid_candidate | local-read operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:90 |
| PUT | /api/v1/subjects/{euid} | bloom_lims.api.v1.subjects.update_subject | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:173 |
| GET | /api/v1/subjects/{euid}/specimens | bloom_lims.api.v1.subjects.get_subject_specimens | euid (path) | tapdb_euid_candidate | local-read operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/subjects.py:262 |
| GET | /api/v1/tasks/ | bloom_lims.api.v1.async_tasks.list_tasks | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/async_tasks.py:218 |
| POST | /api/v1/tasks/submit | bloom_lims.api.v1.async_tasks.submit_task | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/async_tasks.py:86 |
| GET | /api/v1/tasks/types | bloom_lims.api.v1.async_tasks.list_task_types | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/async_tasks.py:118 |
| GET | /api/v1/tasks/{task_id} | bloom_lims.api.v1.async_tasks.get_task_status | task_id (path) | generic_identifier | local-read operational | task_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/async_tasks.py:132 |
| POST | /api/v1/tasks/{task_id}/cancel | bloom_lims.api.v1.async_tasks.cancel_task | task_id (path) | generic_identifier | local-read operational + local-write operational | task_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/async_tasks.py:200 |
| GET | /api/v1/tasks/{task_id}/wait | bloom_lims.api.v1.async_tasks.wait_for_task | task_id (path) | generic_identifier | local-read operational | task_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/async_tasks.py:159 |
| GET | /api/v1/templates/ | bloom_lims.api.v1.templates.list_templates | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/templates.py:27 |
| GET | /api/v1/templates/by-category/{category} | bloom_lims.api.v1.templates.list_templates_by_category | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/templates.py:107 |
| GET | /api/v1/templates/{euid} | bloom_lims.api.v1.templates.get_template | euid (path) | tapdb_euid_candidate | local-read operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/templates.py:77 |
| GET | /api/v1/tracking/carriers | bloom_lims.api.v1.tracking.list_carriers | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/tracking.py:99 |
| POST | /api/v1/tracking/track | bloom_lims.api.v1.tracking.track_package_post | tracking_number (body) | external_business_id | local-write operational | tracking_number: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/tracking.py:115<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/tracking.py:28 |
| GET | /api/v1/tracking/track/{tracking_number} | bloom_lims.api.v1.tracking.track_package_get | tracking_number (path) | external_business_id | display/filter only | tracking_number: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/tracking.py:105 |
| GET | /api/v1/user-tokens | bloom_lims.api.v1.user_api_tokens.list_user_tokens | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/user_api_tokens.py:62 |
| POST | /api/v1/user-tokens | bloom_lims.api.v1.user_api_tokens.create_user_token | atlas_tenant_uuid (body)<br>token_name (body) | token_or_idempotency<br>uuid | local-write operational | token_name: n/a<br>atlas_tenant_uuid: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/user_api_tokens.py:20<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/user_api_tokens.py:25<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/user_api_tokens.py:82 |
| DELETE | /api/v1/user-tokens/{token_id} | bloom_lims.api.v1.user_api_tokens.revoke_user_token | token_id (path) | generic_identifier<br>token_or_idempotency | local-write operational | token_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/user_api_tokens.py:123 |
| GET | /api/v1/user-tokens/{token_id}/usage | bloom_lims.api.v1.user_api_tokens.get_user_token_usage | token_id (path) | generic_identifier<br>token_or_idempotency | local-read operational | token_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/user_api_tokens.py:159 |
| GET | /api/v1/workflows/ | bloom_lims.api.v1.workflows.list_workflows | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/workflows.py:21 |
| POST | /api/v1/workflows/ | bloom_lims.api.v1.workflows.create_workflow | template_euid (query) | tapdb_euid_candidate | local-write operational | template_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/workflows.py:138 |
| GET | /api/v1/workflows/{euid} | bloom_lims.api.v1.workflows.get_workflow | euid (path) | tapdb_euid_candidate | local-read operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/workflows.py:69 |
| PUT | /api/v1/workflows/{euid} | bloom_lims.api.v1.workflows.update_workflow | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/workflows.py:190 |
| POST | /api/v1/workflows/{euid}/advance | bloom_lims.api.v1.workflows.advance_workflow | euid (path) | tapdb_euid_candidate | local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/workflows.py:100 |
| GET | /api/v1/workflows/{euid}/steps | bloom_lims.api.v1.workflows.get_workflow_steps | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/workflows.py:245 |
| GET | /api/v1/worksets/ | bloom_lims.api.v1.worksets.list_worksets | workflow_euid (query) | tapdb_euid_candidate | local-read operational | workflow_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:54 |
| POST | /api/v1/worksets/ | bloom_lims.api.v1.worksets.create_workset | anchor_euid (body)<br>workflow_euid (body) | tapdb_euid_candidate | local-read operational + local-write operational | anchor_euid: no strict local validation<br>workflow_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:138<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:37<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:39 |
| GET | /api/v1/worksets/by-anchor/{anchor_euid} | bloom_lims.api.v1.worksets.get_workset_by_anchor | anchor_euid (path) | tapdb_euid_candidate | local-read operational | anchor_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:298 |
| GET | /api/v1/worksets/{euid} | bloom_lims.api.v1.worksets.get_workset | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:92 |
| PUT | /api/v1/worksets/{euid}/complete | bloom_lims.api.v1.worksets.complete_workset | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:255 |
| GET | /api/v1/worksets/{euid}/members | bloom_lims.api.v1.worksets.get_workset_members | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:218 |
| POST | /api/v1/worksets/{euid}/members | bloom_lims.api.v1.worksets.add_workset_members | member_euids (body)<br>euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution<br>member_euids: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:174<br>/Users/jmajor/projects/daylily/bloom/bloom_lims/api/v1/worksets.py:46 |

## 5. GUI Inventory (92 routes)

| Method | Path | Handler | Identifier Inputs (name + location) | Expected Identifier Type | Operational Usage | Validation/Resolution Gate | Non-TapDB Operational Flag | Evidence |
|---|---|---|---|---|---|---|---|---|
| GET | / | bloom_lims.gui.routes.modern.modern_dashboard | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/modern.py:63 |
| POST | /add_new_edge | bloom_lims.gui.routes.graph.add_new_edge | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:365 |
| GET | /admin | bloom_lims.gui.routes.legacy.admin | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:329 |
| POST | /admin | bloom_lims.gui.routes.legacy.admin_update_preferences | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:483 |
| GET | /admin/metrics | bloom_lims.gui.routes.legacy.admin_metrics | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:469 |
| POST | /admin/zebra/start | bloom_lims.gui.routes.legacy.admin_start_zebra_service | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:509 |
| GET | /admin_template | bloom_lims.gui.routes.files.get_admin_template | euid (query) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:910 |
| POST | /admin_template | bloom_lims.gui.routes.files.post_admin_template | euid (form) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:934 |
| GET | /api/graph/data | bloom_lims.gui.routes.graph.api_graph_data | start_euid (query) | tapdb_euid_candidate | display/filter only | start_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:227 |
| POST | /api/lineage | bloom_lims.gui.routes.graph.api_create_lineage | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:467 |
| DELETE | /api/object/{euid} | bloom_lims.gui.routes.graph.api_delete_object | euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:553 |
| GET | /api/object/{euid} | bloom_lims.gui.routes.graph.api_graph_object_detail | euid (path) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:267 |
| GET | /assays | bloom_lims.gui.routes.legacy.assays | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:192 |
| GET | /auth/callback | bloom_lims.gui.routes.auth.auth_callback_get | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/auth.py:190 |
| POST | /auth/callback | bloom_lims.gui.routes.auth.auth_callback | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/auth.py:195 |
| GET | /bloom_schema_report | bloom_lims.gui.routes.legacy.bloom_schema_report | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1193 |
| GET | /bulk_create_containers | bloom_lims.gui.routes.modern.modern_bulk_create_containers | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/modern.py:217 |
| GET | /bulk_create_files | bloom_lims.gui.routes.files.bulk_create_files | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:311 |
| POST | /bulk_create_files_from_tsv | bloom_lims.gui.routes.files.bulk_create_files_from_tsv | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:1017 |
| GET | /calculate_cogs_children | bloom_lims.gui.routes.legacy.Acalculate_cogs_children | euid (query) | tapdb_euid_candidate | local-read operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:301 |
| GET | /calculate_cogs_parents | bloom_lims.gui.routes.legacy.calculate_cogs_parents | euid (query) | tapdb_euid_candidate | local-read operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:311 |
| GET | /control_overview | bloom_lims.gui.routes.legacy.control_overview | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:794 |
| GET | /controls | bloom_lims.gui.routes.legacy.controls_redirect | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:648 |
| POST | /create_file | bloom_lims.gui.routes.files.create_file | clinician_id (form)<br>health_event_id (form)<br>patient_id (form)<br>study_id (form) | external_business_id<br>generic_identifier | local-read operational + local-write operational | study_id: n/a<br>clinician_id: n/a<br>health_event_id: n/a<br>patient_id: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:330 |
| POST | /create_file_set | bloom_lims.gui.routes.files.create_file_set | file_euids (form) | tapdb_euid_candidate | local-write operational | file_euids: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:674 |
| GET | /create_from_template | bloom_lims.gui.routes.legacy.create_from_template_get | euid (unknown) | tapdb_euid_candidate | local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:820 |
| POST | /create_from_template | bloom_lims.gui.routes.legacy.create_from_template_post | euid (form) | tapdb_euid_candidate | local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:827 |
| POST | /create_instance | bloom_lims.gui.routes.files.create_instance | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:849 |
| GET | /create_instance/{template_euid} | bloom_lims.gui.routes.files.create_instance_form | template_euid (path) | tapdb_euid_candidate | local-read operational + local-write operational | template_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:811 |
| GET | /create_object | bloom_lims.gui.routes.modern.create_object_wizard | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/modern.py:126 |
| GET | /dag | bloom_lims.gui.routes.legacy.dag_redirect | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:653 |
| GET | /dag_explorer | bloom_lims.gui.routes.legacy.dag_explorer_redirect | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:660 |
| GET | /dagg | bloom_lims.gui.routes.graph.dagg | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:188 |
| GET | /database_statistics | bloom_lims.gui.routes.legacy.database_statistics | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:975 |
| GET | /delete_by_euid | bloom_lims.gui.routes.legacy.delete_by_euid | euid (query) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1218 |
| POST | /delete_edge | bloom_lims.gui.routes.graph.delete_edge | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:395 |
| POST | /delete_node | bloom_lims.gui.routes.graph.delete_node | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:378 |
| POST | /delete_object | bloom_lims.gui.routes.legacy.delete_object | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1230 |
| GET | /delete_temp_file | bloom_lims.gui.routes.files.delete_temp_file | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:610 |
| GET | /dewey | bloom_lims.gui.routes.files.dewey | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:213 |
| GET | /dindex2 | bloom_lims.gui.routes.graph.dindex2 | globalStartNodeEUID (query)<br>start_euid (query) | tapdb_euid_candidate | local-read operational | globalStartNodeEUID: no strict local validation<br>start_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:194 |
| POST | /download_file | bloom_lims.gui.routes.files.download_file | euid (form) | tapdb_euid_candidate | local-read operational + local-write operational | euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:536 |
| GET | /equipment | bloom_lims.gui.routes.legacy.equipment_redirect | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:638 |
| GET | /equipment_overview | bloom_lims.gui.routes.legacy.equipment_overview | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:742 |
| GET | /euid_details | bloom_lims.gui.routes.legacy.euid_details | euid (query) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1066 |
| GET | /favicon.ico | bloom_lims.gui.routes.base.favicon | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/base.py:30 |
| GET | /file_set_urls | bloom_lims.gui.routes.files.file_set_urls | fs_euid (query) | tapdb_euid_candidate | local-read operational | fs_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:861 |
| POST | /generic_templates | bloom_lims.gui.routes.legacy.generic_templates | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:615 |
| GET | /get_dagv2 | bloom_lims.gui.routes.graph.get_dagv2 | _euid (unknown) | tapdb_euid_candidate | local-read operational | _euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:321 |
| GET | /get_node_info | bloom_lims.gui.routes.graph.get_node_info | euid (query) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:431 |
| GET | /get_node_property | bloom_lims.gui.routes.graph.get_node_property | euid (query) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:449 |
| GET | /get_related_plates | bloom_lims.gui.routes.legacy.get_related_plates | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:901 |
| GET | /graph | bloom_lims.gui.routes.legacy.graph_redirect | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:667 |
| GET | /help | bloom_lims.gui.routes.modern.help_page | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/modern.py:139 |
| GET | /index2 | bloom_lims.gui.routes.legacy.index2 | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:164 |
| GET | /lims | bloom_lims.gui.routes.legacy.lims | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:178 |
| GET | /list-scripts | bloom_lims.gui.routes.base.list_scripts | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/base.py:13 |
| GET | /login | bloom_lims.gui.routes.auth.get_login_page | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/auth.py:19 |
| POST | /login | bloom_lims.gui.routes.auth.login | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/auth.py:200 |
| GET | /logout | bloom_lims.gui.routes.auth.logout | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/auth.py:214 |
| GET | /oauth_callback | bloom_lims.gui.routes.auth.oauth_callback_get | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/auth.py:110 |
| POST | /oauth_callback | bloom_lims.gui.routes.auth.oauth_callback | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/auth.py:178 |
| GET | /object_templates_summary | bloom_lims.gui.routes.legacy.object_templates_summary | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1042 |
| GET | /plate_carosel2 | bloom_lims.gui.routes.legacy.plate_carosel | plate_euid (query) | tapdb_euid_candidate | local-read operational | plate_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:874 |
| GET | /plate_visualization | bloom_lims.gui.routes.legacy.plate_visualization | plate_euid (query) | tapdb_euid_candidate | local-read operational + local-write operational | plate_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:940 |
| GET | /protected_content | bloom_lims.gui.routes.files.protected_content | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:1011 |
| POST | /query_by_euids | bloom_lims.gui.routes.legacy.query_by_euids | file_euids (form) | tapdb_euid_candidate | local-read operational + local-write operational | file_euids: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:682 |
| GET | /queue_details | bloom_lims.gui.routes.legacy.queue_details | queue_euid (query) | tapdb_euid_candidate | local-read operational | queue_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:583 |
| GET | /reagent_overview | bloom_lims.gui.routes.legacy.reagent_overview | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:768 |
| GET | /reagents | bloom_lims.gui.routes.legacy.reagents_redirect | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:643 |
| POST | /save_json_addl_key | bloom_lims.gui.routes.legacy.save_json_addl_key | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1013 |
| GET | /search | bloom_lims.gui.routes.modern.modern_search | sort_order (query) | external_business_id | local-read operational | sort_order: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/modern.py:151 |
| POST | /search | bloom_lims.gui.routes.modern.modern_search_from_dewey | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/modern.py:191 |
| POST | /search_file_sets | bloom_lims.gui.routes.files.search_file_sets | file_euids (form) | tapdb_euid_candidate | local-read operational + local-write operational | file_euids: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:740 |
| POST | /search_files | bloom_lims.gui.routes.files.search_files | clinician_id (form)<br>euid (form)<br>patient_id (form) | external_business_id<br>generic_identifier<br>tapdb_euid_candidate | local-read operational + local-write operational | euid: no strict local validation<br>patient_id: n/a<br>clinician_id: n/a | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:623 |
| GET | /serve_endpoint/{file_path:path} | bloom_lims.gui.routes.files.serve_files | file_path (path) | file_path_identifier | display/filter only | file_path: n/a | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:956 |
| GET | /set_filter | bloom_lims.gui.routes.legacy.set_filter | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:321 |
| GET | /un_delete_by_uuid | retired | - | - | retired | - | n/a | retired |
| POST | /update_accordion_state | bloom_lims.gui.routes.workflows.update_accordion_state | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/workflows.py:178 |
| POST | /update_dag | bloom_lims.gui.routes.graph.update_dag | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/graph.py:340 |
| POST | /update_obj_json_addl_properties | bloom_lims.gui.routes.workflows.update_obj_json_addl_properties | obj_euid (form) | tapdb_euid_candidate | local-read operational + local-write operational | obj_euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/workflows.py:187 |
| GET | /update_object_name | bloom_lims.gui.routes.legacy.update_object_name | euid (query) | tapdb_euid_candidate | local-read operational + local-write operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:730 |
| POST | /update_preference | bloom_lims.gui.routes.legacy.update_preference | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:564 |
| GET | /user_audit_logs | bloom_lims.gui.routes.legacy.user_audit_logs | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1265 |
| GET | /user_home | bloom_lims.gui.routes.legacy.user_home | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:1284 |
| GET | /uuid_details | retired | - | - | retired | - | n/a | retired |
| GET | /vertical_exp | bloom_lims.gui.routes.legacy.vertical_exp | euid (unknown) | tapdb_euid_candidate | local-read operational | euid: local existence resolution | No | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:861 |
| GET | /visual_report | bloom_lims.gui.routes.files.visual_report | - | - | local-read operational + local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/files.py:763 |
| GET | /workflow_details | bloom_lims.gui.routes.workflows.workflow_details | workflow_euid (query) | tapdb_euid_candidate | local-read operational | workflow_euid: no strict local validation | Potential | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/workflows.py:77 |
| POST | /workflow_step_action | bloom_lims.gui.routes.workflow_actions.workflow_step_action | - | - | local-write operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/workflow_actions.py:20 |
| GET | /workflow_summary | bloom_lims.gui.routes.workflows.workflow_summary | - | - | local-read operational | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/workflows.py:27 |
| GET | /workflows | bloom_lims.gui.routes.legacy.workflows_redirect | - | - | display/filter only | - | No (no EUID input) | /Users/jmajor/projects/daylily/bloom/bloom_lims/gui/routes/legacy.py:633 |

## 6. Validation Scenario Results

1. Coverage test:
- Recomputed mounted runtime routes from `create_app()` and asserted `203` total rows (`111` API + `92` GUI) in report generation.
- Assertion checks are enforced in generation logic before write.

2. Identifier extraction spot-checks:
- Path + body: `POST /api/v1/containers/{container_euid}/contents` includes path `container_euid` and body `container_euid`/`object_euid`.
- Path + header + body: `POST /api/v1/external/atlas/test-orders/{test_order_id}/status-events` includes path `test_order_id`, header `idempotency_key`, and body `container_euid`/`specimen_euid`.
- Query-only: `GET /api/v1/external/specimens/by-reference` includes `order_number`, `patient_id`, `shipment_number`, `package_number`, `kit_barcode`.
- Form-driven GUI: `/search_files` and `/create_file` include form identifiers (`euid`, `patient_id`, `clinician_id`, `study_id`, `health_event_id`).

3. Non-TapDB classification checks:
- Confirmed explicit `Yes` findings for the four high-priority external flows identified in scope.
- Confirmed core CRUD routes with `get_by_euid(...)` gating are classified `No` where local existence resolution is present.

## 7. Appendix: Methodology and Caveats

Methodology:
- Runtime route extraction via `create_app()`.
- Identifier input extraction via function type hints/signatures plus Pydantic body model fields.
- Identifier classes tagged by parameter/field naming patterns (e.g., `*euid*`, `*uid*`, `*token*`, business IDs, file/path IDs).
- Operational usage and gate classification inferred from handler and model source inspection (`inspect.getsource(...)`) and key call-pattern matching.
- Non-TapDB flag application: explicit high-priority overrides for confirmed external flows, otherwise conservative heuristic classification.

Caveats:
- Route-level static analysis cannot fully prove call-order inside all downstream services; findings use direct source evidence where available.
- Some legacy routes use loosely typed params (`inspect._empty`), so location/type tags are best-effort (`query`/`unknown`) when FastAPI metadata is implicit.
- This report focuses on mounted runtime surface only; unmounted decorators or dead code are intentionally excluded.
