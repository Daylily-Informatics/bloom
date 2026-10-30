# Bloom owner API contract

Owner: orchestrator. Parent: [campaign owner ledger](20260918T135200Z_campaign_owner_contract_ledger.md). Source reviewed; production acceptance remains OPEN.

`POST /api/v1/graph/snapshot` uses existing `require_read` authorization. The request contains exact unique `object_euids` (1–128) and exact unique `lineage_selectors` (0–128), each with `parent_euid`, `child_euid`, `relationship_type`. Both edge endpoints must be in the object set. There is no traversal, guessed identity, partial result, pagination or per-object fallback.

One fresh native scoped read-only repeatable-read transaction returns exactly the requested live objects and exactly one persisted live edge per selector. Missing or ambiguous objects/edges return409. The response has `schema=bloom.owner_snapshot/1`, `request_sha256`, database transaction `observed_at`, `transaction_isolation=repeatable read`, `read_only=true`, `complete=true`, `objects`, `lineages`, `snapshot_sha256`.

Object fields are exactly `euid,name,type,subtype,status,json_addl,created_at,is_deleted`; edge fields are exactly `euid,parent_euid,child_euid,relationship_type,is_deleted`. Both deleted flags are false. Objects sort by EUID; edges sort by parent,child,relationship,EUID. Canonical hashing uses UTF-8 JSON with sorted keys, compact comma/colon separators, ensure_ascii=false and allow_nan=false. The request hash first sorts EUIDs and selector triples; the snapshot hash omits only snapshot_sha256.

`PATCH /api/v1/objects/{euid}/properties/{namespace}` uses existing `require_write`. Request fields are exactly `expected_json_addl_sha256` and object-valued `value` (canonical JSON maximum64KiB). Namespace names are explicit lowercase letters/digits/underscores starting with a letter, maximum128characters.

The native transaction locks the exact live object. An absent namespace is added only when the current complete json_addl digest equals the supplied precondition. Other top-level and property fields are preserved. A different existing namespace or stale absent precondition returns409. An identical namespace returns `already_present` without mutation, even when other fields have changed since the original request. This is retry reconciliation, not authorization to replace another writer's data.

The committed response has schema `bloom.property_namespace_write/1`, actual `euid`, `namespace`, `outcome=created|already_present`, `changed`, `expected_json_addl_sha256`, `before_json_addl_sha256`, `after_json_addl_sha256`, `value_sha256`, `observed_at`, and canonical `receipt_sha256` over every other field. Native audit attribution uses the authenticated actor. Callers retain the actual receipt and perform owner readback; uncertain requests must be reconciled before retry. Existing general-purpose PUT behavior is unchanged and is not used by this campaign.

Acceptance requires native deployed identity, successful real owner snapshots within the submission deadline, exact preserved relationships, guarded metadata persistence/readback, and retained receipts. No local tests or intermediate container images are part of this change.
