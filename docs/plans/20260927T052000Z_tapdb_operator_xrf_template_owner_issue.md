# TapDB issue draft: operator XRF template lookup can select another issuer

Prepared 2026-09-27T05:20Z for coordinator review and posting. No issue was posted here.

## Observed behavior

Bloom's bounded canonical XRF conversion used published TapDB 10.1.4 `ExternalReferenceService.attach` in one operator transaction. The source owned all 174 old assertions. The new `tapdb_object` XRF insert failed at the native allocator trigger with `Missing template instance_prefix for generic_instance template_uid 242 (domain=M, owner_repo=bloom)`. Read-only reconciliation after the exception selected all 174 original active assertions unchanged; no committed data corruption was demonstrated. The transaction outcome receipt was conservatively `apply_outcome_unknown`, and the writer remained stopped pending reconciliation.

Read-only catalog inspection found two active exact canonical `reference/external_identifier/tapdb_object/2.0` templates in domain `M`: UID 242 issued by `daylily-tapdb`, and UID 244 issued by `bloom`; both have `instance_prefix=XRF`. The operator saw both and selected UID 242. Under Bloom's bound runtime role, native RLS exposes only the Bloom-owned UID 244. No template rewrite, RLS bypass, or new package build was performed to resolve this.

## Source cause

In tagged TapDB 10.1.4, `ExternalReferenceService._claim_reference` constructs `InstanceFactory(TemplateManager(), domain_code=source.domain_code)` in `daylily_tapdb/external_references.py`. `TemplateManager.get_template` in `daylily_tapdb/templates/manager.py` filters template code, domain and active state, then calls `.first()` without filtering the transaction's `issuer_app_code`. Its cache key also omits issuer. The operator can see multiple issuers' core templates. The insert trigger `set_generic_instance_euid` in `schema/allocator_functions.sql` correctly requires the selected template UID to belong to the current domain and owner; it rejects UID 242 under owner `bloom`. The same unscoped manager lookup remains present in tagged 10.1.10. Existing persisted XRF reads do not perform this new-template lookup, which explains why they succeeded.

## Expected behavior and acceptance

The native XRF writer should deterministically select the exact active canonical template for the transaction's domain **and issuer**, or fail explicitly if that issuer's template is absent or ambiguous. Cache identity must include issuer. It must retain the allocator's owner guard and canonical XRF invariants; no copied EUID, metadata field, or cross-service edge should be inferred. A focused test should cover two issuers in one schema with an operator-visible session, asserting the chosen template matches the transaction owner and that new XRF/lineage remains canonical. It should also cover the constrained runtime role without changing existing template or historical XRF rows.

## Current client containment

The bounded Bloom repair can use TapDB's public `TAPDBConnection` as its already bound `bloom_runtime_10` role with the unchanged runtime config identity. Forced native template RLS then exposes only UID 244. The operator runner's failed transaction is not retried; a separate runtime-role preflight, one reviewed transaction, and post-commit readback remain required. This containment does not change the native operator defect, which can affect any shared-schema operator XRF writer with more than one issuer's matching core template.
