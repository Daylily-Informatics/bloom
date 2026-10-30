"""Focused, offline request/identity contracts. Authored; execution is separately gated."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from uuid import UUID

import pytest
from daylily_tapdb.factory import IdentityClaimOutcome, IdentityScope

from bloom_lims.domain import beta_lab_tubes as tubes
from bloom_lims.schemas.beta_lab import BetaTubeCreateRequest, BetaTubeIdentifier, BetaTubeRegisterExistingRequest


TENANT = "10000000-0000-0000-0000-000000000001"
OTHER_TENANT = "10000000-0000-0000-0000-000000000002"
TEMPLATE = "container/tube/tube-generic-10ml/1.0"


def request(*, tenant=TENANT, identifier=False, **changes):
    body = {"container_template_code": TEMPLATE, "atlas_context": {"atlas_tenant_id": tenant}, **changes}
    if identifier:
        body["identifier"] = {"tenant_id": tenant, "namespace": "outside-lab", "kind": "barcode", "value": "Ab-001"}
        return BetaTubeRegisterExistingRequest(**body)
    return BetaTubeCreateRequest(**body)


def test_exact_template_and_qualified_tenant_required():
    with pytest.raises(ValueError):
        BetaTubeCreateRequest(atlas_context={"atlas_tenant_id": TENANT})
    with pytest.raises(ValueError):
        request(container_template_code="container/tube/*/1.0")
    body = request(identifier=True).model_dump()
    body["identifier"]["tenant_id"] = OTHER_TENANT
    with pytest.raises(ValueError, match="tenant must agree"):
        BetaTubeRegisterExistingRequest(**body)


def test_only_uuid_identifier_values_are_normalized():
    value = BetaTubeIdentifier(tenant_id=TENANT, namespace="lab", kind="uuid",
                               value="{ABCDEFAB-1234-5678-9000-ABCDEF123456}")
    assert value.value == "abcdefab-1234-5678-9000-abcdef123456"
    assert request(identifier=True).identifier.value == "Ab-001"
    with pytest.raises(ValueError):
        BetaTubeIdentifier(tenant_id=TENANT, namespace="lab", kind="barcode", value=" Ab-001 ")


def test_digest_is_deterministic_and_covers_operation_tenant_template_and_properties():
    baseline, normalized = tubes.tube_request_digest("create", request())
    assert normalized == {"container_template_code": TEMPLATE, "atlas_context": {"atlas_tenant_id": TENANT}}
    assert tubes.tube_request_digest("create", request(status="active", properties={}))[0] == baseline
    for operation, payload in [
        ("register-existing", request()), ("create", request(tenant=OTHER_TENANT)),
        ("create", request(container_template_code="container/tube/other/1.0")),
        ("create", request(properties={"name": "changed"})),
    ]:
        assert tubes.tube_request_digest(operation, payload)[0] != baseline


@pytest.mark.parametrize("key", [None, "", " padded", "space key", "x" * 201])
def test_missing_or_unsafe_key_rejected(key):
    with pytest.raises(ValueError):
        tubes.tube_request_key(key)


class MemorySession:
    def __init__(self):
        self.rows, self.pending, self.commits, self.rollbacks = [], [], 0, 0
        self.active = False

    def in_transaction(self):
        return self.active

    def begin(self):
        self.active = True

    def flush(self):
        pass

    def commit(self):
        self.rows.extend(self.pending)
        self.pending.clear()
        self.commits += 1
        self.active = False

    def rollback(self):
        self.pending.clear()
        self.rollbacks += 1
        self.active = False


class Harness(tubes._BetaLabTubeRequestsMixin):
    def __init__(self, monkeypatch):
        self.session = MemorySession()
        self.bdb = SimpleNamespace(session=self.session, domain_code="TEST", app_username="actor@example.invalid",
                                   _conn=SimpleNamespace(tenant_id=None, transaction_context=lambda: SimpleNamespace(
                                       tenant_id=None, additional_tenant_ids=(TENANT, OTHER_TENANT))))
        self.claims, self.locks, self.attachments, self.context_writes = [], [], [], []
        self.matches = {"items": [], "page": {"next_cursor": None}}
        self.refs = SimpleNamespace(find_sources=lambda *args, **kwargs: self.matches)
        monkeypatch.setattr(tubes, "ExternalReferenceService", lambda session: self.refs)
        monkeypatch.setattr(tubes, "acquire_transaction_advisory_lock",
                            lambda session, namespace, *parts, **kwargs: self.locks.append((namespace, parts)))

    def _tube_factory(self):
        return SimpleNamespace(claim_instance_by_identity=self.claim)

    def claim(self, session, **kwargs):
        self.claims.append(kwargs)
        category, kind, subtype, version = kwargs["template_code"].split("/")
        row = SimpleNamespace(euid=f"<persisted-object-{len(self.claims)}>", uid=len(self.claims),
                              category=category, type=kind, subtype=subtype, version=version,
                              tenant_id=kwargs["tenant_id"], is_deleted=False,
                              json_addl={"properties": copy.deepcopy(kwargs["properties"])}, bstatus="active")
        self.session.pending.append(row)
        return SimpleNamespace(instance=row, outcome=IdentityClaimOutcome.CREATED)

    def _tube_request_record(self, key, tenant):
        return next((row for row in self.session.rows if row.type == "accession-request"
                     and row.tenant_id == tenant and self._props(row)["request_key"] == key), None)

    def _require_exact_tube_template(self, code):
        assert code == TEMPLATE

    def _reject_unreceipted_tube_key(self, key, tenant):
        pass

    def _validate_registration_properties(self, properties):
        pass

    def _explicit_tube_name(self, properties):
        return properties.get("name")

    def _props(self, row):
        return row.json_addl["properties"]

    def _write_props(self, row, props):
        row.json_addl = {"properties": props}

    def _replace_container_entity_references(self, row, *, atlas_context):
        self.context_writes.append((row, atlas_context))

    def _replace_fulfillment_item_references(self, row, *, atlas_context):
        self.context_writes.append((row, atlas_context))

    def _tube_owner_target(self, tube):
        return SimpleNamespace(target_service_id="bloom", target_object_euid=tube.euid, target_tenant_id=tube.tenant_id)

    def _attach_tube_reference(self, source, target, relationship, digest):
        self.attachments.append((source, target, relationship))
        return SimpleNamespace(reference=SimpleNamespace(euid="<persisted-reference>"),
                               lineage=SimpleNamespace(euid="<persisted-lineage>"))

    def _tube_response(self, tube, *, created):
        return {"container_euid": tube.euid, "status": tube.bstatus, "atlas_context": {"atlas_tenant_id": TENANT},
                "properties": copy.deepcopy(self._props(tube)), "created": created}

    def _record_action(self, **kwargs):
        pass


def test_create_replays_exact_original_receipt_even_if_container_changes(monkeypatch):
    service = Harness(monkeypatch)
    first = service.create_empty_tube(payload=request(), idempotency_key="same-key")
    service.session.rows[1].bstatus = "changed-after-response"
    replay = service.create_empty_tube(payload=request(), idempotency_key="same-key")
    assert replay == first
    assert len(service.claims) == 2
    assert service.get_tube_request(request_key="same-key", atlas_tenant_id=TENANT)["response"] == first
    assert service.claims[0]["scope"] is IdentityScope.TENANT
    assert service.claims[0]["tenant_id"] == UUID(TENANT)
    assert service.claims[1]["scope"] is IdentityScope.GLOBAL
    assert replay["tenant_id"] is None and replay["atlas_tenant_id"] == TENANT


def test_same_key_changed_request_fails_without_reallocation(monkeypatch):
    service = Harness(monkeypatch)
    service.create_empty_tube(payload=request(), idempotency_key="same-key")
    with pytest.raises(tubes.TubeRequestConflict, match="different tube request"):
        service.create_empty_tube(payload=request(properties={"name": "different"}), idempotency_key="same-key")
    assert len(service.claims) == 2
    assert service.session.rollbacks == 1


def test_tenant_reconciliation_cannot_read_other_receipt(monkeypatch):
    service = Harness(monkeypatch)
    service.create_empty_tube(payload=request(), idempotency_key="shared-key")
    with pytest.raises(tubes.TubeRequestNotFound):
        service.get_tube_request(request_key="shared-key", atlas_tenant_id=OTHER_TENANT)
    second = service.create_empty_tube(payload=request(tenant=OTHER_TENANT), idempotency_key="shared-key")
    assert second["atlas_tenant_id"] == OTHER_TENANT
    assert service.claims[1]["identity_key"] != service.claims[3]["identity_key"]


def test_existing_physical_registration_has_native_tenant_assertion_and_no_material(monkeypatch):
    service = Harness(monkeypatch)
    result = service.register_existing_tube(payload=request(identifier=True), idempotency_key="physical-key")
    assert result["identifier"]["value"] == "Ab-001"
    assert [claim["template_code"] for claim in service.claims] == [
        service.TUBE_REQUEST_TEMPLATE, TEMPLATE, service.TUBE_IDENTITY_TEMPLATE,
    ]
    source, target, relationship = service.attachments[0]
    assert source.tenant_id == UUID(TENANT)
    assert target.scope == "tenant" and target.tenant_id == UUID(TENANT)
    assert target.namespace == "outside-lab" and target.value == "Ab-001"
    assert relationship == service.TUBE_IDENTIFIER_RELATIONSHIP
    assert {item[0] for item in service.locks} == {"bloom.tube-request/v1", "bloom.physical-tube/v1"}
    assert service.session.commits == 1


def test_ambiguous_physical_identifier_rolls_back_receipt(monkeypatch):
    service = Harness(monkeypatch)
    service.matches["items"] = [{}, {}]
    with pytest.raises(tubes.TubeRequestConflict, match="ambiguous"):
        service.register_existing_tube(payload=request(identifier=True), idempotency_key="ambiguous-key")
    assert not service.session.rows and not service.session.pending
    assert len(service.claims) == 1
    assert service.session.commits == 0 and service.session.rollbacks == 1


def test_identifier_attach_failure_rolls_back_container_assertion_and_receipt(monkeypatch):
    service = Harness(monkeypatch)
    def fail(*args):
        raise RuntimeError("native reference write rejected")
    service._attach_tube_reference = fail
    with pytest.raises(RuntimeError, match="native reference"):
        service.register_existing_tube(payload=request(identifier=True), idempotency_key="failed-key")
    assert not service.session.rows and not service.session.pending
    assert service.session.commits == 0 and service.session.rollbacks == 1


def test_one_matching_physical_tube_returns_existing_without_mutation(monkeypatch):
    service = Harness(monkeypatch)
    existing = SimpleNamespace(euid="<persisted-existing-tube>", category="container", type="tube",
                               subtype="tube-generic-10ml", version="1.0", tenant_id=None,
                               bstatus="active", json_addl={"properties": {"name": "original"}})
    service.matches["items"] = [{"source": {"euid": "<persisted-assertion>"},
                                 "matched_external_reference": {
                                     "assertion_authority": service.TUBE_IDENTIFIER_AUTHORITY,
                                     "external_reference_euid": "<persisted-reference>",
                                     "lineage_euid": "<persisted-lineage>"}}]
    service._require_tube_assertion = lambda *args: object()
    service._tube_identifier_evidence = lambda *args: {"identifier": request(identifier=True).identifier.model_dump()}
    service._tube_from_assertion = lambda *args: existing
    response = service.register_existing_tube(payload=request(identifier=True, properties={"name": "ignored"}),
                                               idempotency_key="resolve-key")
    assert response["container_euid"] == existing.euid and response["created"] is False
    assert existing.json_addl["properties"]["name"] == "original"
    assert len(service.claims) == 1 and not service.context_writes


def test_unconfigured_tenant_is_rejected_before_claims(monkeypatch):
    service = Harness(monkeypatch)
    service.bdb._conn.transaction_context = lambda: SimpleNamespace(tenant_id=None, additional_tenant_ids=())
    with pytest.raises(PermissionError, match="explicitly configured"):
        service.create_empty_tube(payload=request(), idempotency_key="not-authorized")
    assert not service.claims and not service.session.active
    with pytest.raises(PermissionError):
        service.get_tube_request(request_key="not-authorized", atlas_tenant_id=TENANT)


def test_concurrent_same_key_waiter_replays_committed_winner(monkeypatch):
    """Offline transaction-lock simulation; real PostgreSQL contention remains a deployment gate."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    first, second = Harness(monkeypatch), Harness(monkeypatch)
    shared_rows, transaction_lock, start = [], Lock(), Barrier(2)
    for service in (first, second):
        service.session.rows = shared_rows
        original_commit = service.session.commit
        def commit(original=original_commit):
            original()
            transaction_lock.release()
        service.session.commit = commit
    def lock(session, namespace, *parts, **kwargs):
        assert namespace == "bloom.tube-request/v1"
        assert parts == (UUID(TENANT), "racing-key")
        assert transaction_lock.acquire(timeout=2)
    monkeypatch.setattr(tubes, "acquire_transaction_advisory_lock", lock)
    def run(service):
        start.wait(timeout=2)
        return service.create_empty_tube(payload=request(), idempotency_key="racing-key")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, (first, second)))
    assert results[0] == results[1]
    assert len(first.claims) + len(second.claims) == 2
    assert len(shared_rows) == 2
