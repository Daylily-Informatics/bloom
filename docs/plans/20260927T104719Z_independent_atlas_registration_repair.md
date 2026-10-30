# Independent Atlas tube/material registration repair

## Current continuation state

Source prepared on `codex/bloom-accession-config-20260927`, based on Bloom `10.0.13` / `8809ab88b15d7956a4ca880333a282398045648a`. Parent accession coordinator owns publication/deployment approval and the controlling Dayhoff ledger. No release, deployment, live mutation, template import, dependency/lock update, or historical repair occurred in this workstream. TapDB remains pinned to `10.1.4`.

The approved fresh D01 request `f058204f-7dd1-4be8-b486-1278a1e7bb0d` created tube `M-BCT-A1E9` and success action `M-BAC-9YKN` at `2026-09-27T10:31:25.027242Z`, then returned HTTP 400. Read-only replay of response projection proved `Bloom Atlas context requires explicit atlas_tenant_id on a reachable reference`. The request explicitly supplied tenant `74ed40e0-09cd-4704-b2c3-0beb8b09d9ca` without business-object references. Parent retains sanitized owner and HTTP evidence. The existing tube is untouched; no POST retry or replacement was issued.

Next: coordinator reviews this bounded source repair and the separate Atlas owner-receipt reconciliation interface. Any deployment remains coordinator-controlled. The existing failed tube must be reconciled against its exact owner receipt; this patch does not infer context from historical actions or amend that object.

## Requirements and design

- **Requirement:** valid independent tubes and material need no patient, order, collection, package, kit, or site relationship.
- **Source-established defect:** beta tube creation committed before `_tube_response`; that response demanded an Atlas tenant on a reachable business reference. The creation factory also committed individual objects during template-tree construction.
- **Proposed implementation:** `properties.atlas_registration_tenant_id` records the explicitly supplied Atlas tenant UUID. It is registration scope only, never an Atlas object identity or relationship. Typed external references and native lineages remain authoritative for all business associations.
- **Integrity:** explicit registration scope and typed reference tenant facts on the supported reachable-parent relationships must agree. Invalid UUIDs, conflicting tenant facts, and attempts to override this managed scalar through arbitrary object properties fail. Missing context fails; no receipt/history fallback is introduced.
- **Transactions:** `BloomObj` template-tree creation has an explicit caller-owned `commit=False` option. Only the two beta registration operations select it. Descendant creation flushes in the same caller transaction. Both registrations construct and validate the response before the final commit; update responses also precede their final commit.
- **Name:** an explicitly supplied tube `properties.name` is validated and assigned to the native node name as well. New and updated tubes retain consistent native and displayed names. No existing object is rewritten.

## Source changes

| Path | Change |
| --- | --- |
| `bloom_lims/domain/base.py` | Propagate caller-owned commit selection through instance and recursive template-tree creation. Existing other callers keep their prior transaction behavior. |
| `bloom_lims/domain/beta_lab_store.py` | Pass the explicit transaction selection through container creation. |
| `bloom_lims/domain/beta_lab_refs.py` | Bind explicit registration tenant and reconcile tenant facts against typed owner references and supported parent relationships. |
| `bloom_lims/domain/beta_lab_materials.py` | Use caller-owned creation, preserve tenant-only context, reject arbitrary scope overrides, keep tube names consistent, and validate responses before final commit. |
| `tests/accession_feature/conftest.py` | Explicit local configuration only; excludes inherited bootstrap fixtures. |
| `tests/accession_feature/test_independent_registration.py` | Nineteen scoped regression tests. |

A bounded source audit found no explicit commit in the called Atlas-reference reconciliation, beta action recorder, graph metadata, reference helpers, or beta store helper files. Native `ExternalReferenceService` composes with the supplied session. The two intake paths do not call the separately committing `create_instances` convenience method.

## Focused verification receipt

Isolated environment: `/tmp/bloom-accession-20260927-py312-venv`, Python `3.12.12`, frozen repository dependency lock, TapDB `10.1.4`. Editable local package metadata was installed only in that temporary environment. No container build occurred.

```text
/tmp/bloom-accession-20260927-py312-venv/bin/python -m pytest -o addopts='' --confcutdir=tests/accession_feature tests/accession_feature/test_independent_registration.py -q
19 passed in 0.41s
```

Coverage includes independent tube and material, absence of invented business relationships, response and response-schema failure before commit, consistent native names, missing/conflicting tenant context including a parent tube, managed-scalar override rejection, commit selection in native instance construction and nested template creation, and rollback of all staged test writes through a real local SQLite SQLAlchemy transaction. The SQLite check is **not** PostgreSQL/native TapDB rollback evidence. No live API or database was called by these tests.

The first invocation collected only eleven new tests, all passing, but inherited repository `addopts` enabled whole-package coverage and failed its unrelated 39% floor. It lasted 9.1 seconds. No additional tests or database provisioning ran. Subsequent invocations explicitly disabled inherited `addopts`; no system-wide test/coverage campaign was performed. Token and monetary costs are unavailable and are not estimated.

## Stop boundaries

No automatic publication, deployment, new TapDB work, destructive cleanup, old-data compatibility, workflow execution, or historical-data repair. The failed live D01 identity stays preserved for the coordinator's separately guarded reconciliation.
