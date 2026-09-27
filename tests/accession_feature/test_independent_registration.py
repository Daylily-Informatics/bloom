"""Independent Atlas registration and caller-owned commits, with no live services."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bloom_lims.domain import beta_lab_refs
from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.beta_lab_materials import _BetaLabMaterialsMixin
from bloom_lims.domain.beta_lab_refs import _BetaLabReferenceMixin
from bloom_lims.domain.beta_lab_store import _BetaLabStoreMixin
from bloom_lims.schemas.beta_lab import BetaAcceptedMaterialCreateRequest, BetaTubeCreateRequest

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"


class Session:
    def __init__(self):
        self.commits = 0
        self.flushes = 0
        self.rows = []

    def commit(self):
        self.commits += 1

    def flush(self):
        self.flushes += 1

    def add(self, row):
        self.rows.append(row)

    def rollback(self):
        self.rows.clear()


class Registration(_BetaLabMaterialsMixin, _BetaLabReferenceMixin, _BetaLabStoreMixin):
    PROCESS_ITEM_REFERENCE_TYPE = "atlas_test_fulfillment_item"
    PATIENT_REFERENCE_TYPE = "atlas_patient"
    TRF_REFERENCE_TYPE = "atlas_trf"
    TEST_REFERENCE_TYPE = "atlas_test"
    TESTKIT_REFERENCE_TYPE = "atlas_testkit"
    SHIPMENT_REFERENCE_TYPE = "atlas_shipment"
    ORGANIZATION_SITE_REFERENCE_TYPE = "atlas_organization_site"
    COLLECTION_EVENT_REFERENCE_TYPE = "atlas_collection_event"

    def __init__(self):
        self.session = Session()
        self.bdb = SimpleNamespace(session=self.session, app_username="example:actor")
        self.records, self.calls, self.refs = {}, [], {}
        self.bobj = SimpleNamespace(create_instance_by_code=self.create)
        self._record_action = Mock()
        self._ensure_container_link = Mock()
        self._replace_container_entity_references = Mock()
        self._replace_fulfillment_item_references = Mock()
        self._replace_collection_event_reference = Mock()
        self._replace_patient_reference = Mock()
        self._write_graph_metadata = Mock()
        self._graph_expected_fanout_entry = lambda **kw: kw
        self._current_queue_for_instance = lambda row: None
        self._linked_container_euid = lambda row: "example:tube"
        self._require_instance = lambda euid: self.records[euid]
        self._reachable_fulfillment_item_refs = lambda row: []
        self._patient_ref_for_instance = lambda row: None
        self._collection_event_ref_for_instance = lambda row: None
        self._first_reachable_reference_value = lambda *a, **kw: ""
        self._reachable_reference_values = lambda *a, **kw: []
        self._atlas_reference_payloads_for_instance = lambda row: self.refs.get(row.uid, [])
        self._has_collection_event_context = lambda context: False
        self._find_container_record = lambda **kw: None
        self._find_content_record = lambda **kw: None

    def create(self, code, overrides, *, commit=True):
        self.calls.append((code, commit))
        alias = "example:tube" if code.startswith("container/") else "example:material"
        row = SimpleNamespace(euid=alias, uid=alias, name=alias, bstatus="active",
            json_addl=deepcopy(overrides.get("json_addl", {})), category=code.split('/')[0],
            type=code.split('/')[1], subtype=code.split('/')[2], version="1.0", is_deleted=False)
        self.records[alias] = row
        if commit:
            self.session.commit()
        return row

    @staticmethod
    def _props(row):
        return deepcopy(row.json_addl.get("properties", {}))

    @staticmethod
    def _write_props(row, props):
        row.json_addl = {**row.json_addl, "properties": props}


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(beta_lab_refs, "get_child_lineages", lambda row: [])
    return Registration()


def tube_payload():
    return BetaTubeCreateRequest(atlas_context={"atlas_tenant_id": TENANT},
        properties={"name": "Independent synthetic tube"})


def material_payload():
    return BetaAcceptedMaterialCreateRequest(atlas_context={"atlas_tenant_id": TENANT},
        specimen_name="Unknown source material")


def test_tenant_only_tube_returns_valid_context_without_invented_relationships(service):
    result = service.create_empty_tube(payload=tube_payload(), idempotency_key="example:request")
    assert result["container_euid"] == "example:tube"
    assert service.records["example:tube"].name == "Independent synthetic tube"
    assert result["atlas_context"]["atlas_tenant_id"] == TENANT
    assert result["atlas_context"]["atlas_order_euid"] == ""
    assert result["atlas_context"]["atlas_collection_event_euid"] == ""
    assert result["atlas_context"]["fulfillment_items"] == []
    assert service._props(service.records["example:tube"])["atlas_registration_tenant_id"] == TENANT
    assert service.calls == [("container/tube/tube-generic-10ml/1.0", False)]
    assert service.session.commits == 1


def test_unknown_source_material_and_its_tube_retain_explicit_tenant_only(service):
    result = service.register_accepted_material(payload=material_payload(), idempotency_key="example:material-request")
    assert result.specimen_euid == "example:material"
    assert result.container_euid == "example:tube"
    assert result.atlas_context["atlas_tenant_id"] == TENANT
    assert result.atlas_context["atlas_collection_event_euid"] == ""
    assert all(not commit for _, commit in service.calls)
    assert set(service.records) == {"example:tube", "example:material"}
    assert all(service._props(row)["atlas_registration_tenant_id"] == TENANT for row in service.records.values())
    assert service.session.commits == 1


@pytest.mark.parametrize("operation", ["tube", "material"])
def test_response_failure_occurs_before_any_commit(service, operation):
    def fail(*a, **kw):
        raise ValueError("Unrenderable response")
    service._atlas_context_for_instance = fail
    with pytest.raises(ValueError, match="Unrenderable"):
        if operation == "tube":
            service.create_empty_tube(payload=tube_payload(), idempotency_key="example:request")
        else:
            service.register_accepted_material(payload=material_payload(), idempotency_key="example:request")
    assert service.session.commits == 0
    assert all(not commit for _, commit in service.calls)


def test_response_schema_failure_occurs_before_tube_commit(service):
    service._tube_response = lambda *a, **kw: {"container_euid": None}
    with pytest.raises(ValueError):
        service.create_empty_tube(payload=tube_payload(), idempotency_key="example:request")
    assert service.session.commits == 0


def test_supplied_tenant_cannot_change_explicit_registration_tenant(service):
    row = service.create("container/tube/test/1.0", {"json_addl": {}}, commit=False)
    service._bind_atlas_registration_tenant(row, {"atlas_tenant_id": TENANT})
    with pytest.raises(ValueError, match="supplied tenant contexts disagree"):
        service._bind_atlas_registration_tenant(row, {"atlas_tenant_id": OTHER_TENANT})
    assert service._props(row)["atlas_registration_tenant_id"] == TENANT


def test_typed_reference_cannot_contradict_registration_tenant(service):
    row = service.create("container/tube/test/1.0", {"json_addl": {}}, commit=False)
    service._bind_atlas_registration_tenant(row, {"atlas_tenant_id": TENANT})
    service.refs[row.uid] = [{"atlas_tenant_id": OTHER_TENANT}]
    with pytest.raises(ValueError, match="reference tenant contexts disagree"):
        service._atlas_context_for_instance(row)


def test_missing_context_is_not_reconstructed_from_action_history(service):
    row = service.create("container/tube/test/1.0", {"json_addl": {}}, commit=False)
    with pytest.raises(ValueError, match="explicit registration tenant or typed reference"):
        service._atlas_context_for_instance(row)


@pytest.mark.parametrize("commit", [False, True])
def test_base_instance_creation_obeys_caller_owned_commit_flag(commit):
    obj = BloomObj.__new__(BloomObj)
    obj.session = Session()
    obj.logger = Mock()
    template = SimpleNamespace(euid="example:template", uid="example:template", name="Tube",
        polymorphic_discriminator="generic_template", category="container", type="tube", subtype="test",
        version="1.0", bstatus="active", json_addl={})
    obj.get_by_euid = lambda euid: template
    obj.Base = SimpleNamespace(classes=SimpleNamespace(generic_instance=lambda **kw: SimpleNamespace(**kw)))
    obj._apply_default_graph_metadata = lambda row: None
    result = obj.create_instance(template.euid, commit=commit)
    assert result.name == "Tube"
    assert obj.session.commits == int(commit)
    assert obj.session.flushes == int(not commit)


def test_template_tree_propagates_caller_transaction_to_child_creation():
    obj = BloomObj.__new__(BloomObj)
    obj.session = Session()
    root = SimpleNamespace(euid="example:root-template", uid="example:root-template", category="container",
        type="tube", subtype="root", version="1.0", json_addl={"instantiation_layouts": [{
            "relationship_type": "contains", "child_templates": [{"template_code": "container/well/child/1.0"}]}]})
    child = SimpleNamespace(euid="example:child-template", uid="example:child-template", category="container",
        type="well", subtype="child", version="1.0", json_addl={})
    obj.get_by_euid = lambda euid: root if euid == root.euid else child
    obj.query_template_by_component_v2 = lambda *a: [child]
    calls = []
    def create(template_euid, **kwargs):
        calls.append((template_euid, kwargs["commit"]))
        return SimpleNamespace(euid="example:instance-" + str(len(calls)))
    obj.create_instance = create
    obj._new_instantiation_lineage = lambda *a: SimpleNamespace()
    obj._create_instance_tree(template_euid=root.euid, json_addl_overrides={}, ret_objs=[[], []],
        depth=0, template_stack=(), max_depth=5, max_instances=5, state={"created_count": 0}, commit=False)
    assert calls == [(root.euid, False), (child.euid, False)]
    assert obj.session.commits == 0


def test_parent_tube_explicit_tenant_cannot_conflict_with_material(service, monkeypatch):
    tube = service.create("container/tube/test/1.0", {"json_addl": {}}, commit=False)
    material = service.create("material/specimen/test/1.0", {"json_addl": {}}, commit=False)
    service._bind_atlas_registration_tenant(tube, {"atlas_tenant_id": TENANT})
    service._bind_atlas_registration_tenant(material, {"atlas_tenant_id": OTHER_TENANT})
    lineage = SimpleNamespace(is_deleted=False, relationship_type="HOLDS_MATERIAL", parent_instance=tube)
    monkeypatch.setattr(beta_lab_refs, "get_child_lineages", lambda row: [lineage] if row is material else [])
    with pytest.raises(ValueError, match="reference tenant contexts disagree"):
        service._atlas_context_for_instance(material)


def test_blank_explicit_tube_name_fails_before_creating_object(service):
    payload = tube_payload()
    payload.properties["name"] = "  "
    with pytest.raises(ValueError, match="nonblank"):
        service.create_empty_tube(payload=payload, idempotency_key="example:request")
    assert service.records == {}
    assert service.session.commits == 0


def test_update_keeps_native_tube_name_and_display_property_consistent(service):
    from bloom_lims.schemas.beta_lab import BetaTubeUpdateRequest
    service.create_empty_tube(payload=tube_payload(), idempotency_key="example:create")
    service._require_template = lambda code: SimpleNamespace(category="container", json_addl={})
    service.update_tube(container_euid="example:tube", payload=BetaTubeUpdateRequest(properties={"name": "Renamed tube"}))
    row = service.records["example:tube"]
    assert row.name == service._props(row)["name"] == "Renamed tube"


@pytest.mark.parametrize("operation", ["tube", "material"])
def test_failed_response_rolls_back_complete_caller_transaction_on_local_sqlite(service, operation):
    # A real SQLAlchemy transaction proves the caller does not commit our staged
    # rows. This is deliberately not PostgreSQL/native TapDB rollback evidence.
    from sqlalchemy import Column, Integer, String, create_engine, select, func
    from sqlalchemy.orm import Session as SQLSession, declarative_base
    base = declarative_base()
    class WriteRecord(base):
        __tablename__ = "scoped_registration_test"
        id = Column(Integer, primary_key=True)
        kind = Column(String)
    engine = create_engine("sqlite://")
    base.metadata.create_all(engine)
    with SQLSession(engine) as session:
        service.session = session
        service.bdb.session = session
        original_create = service.create
        def create(*args, **kwargs):
            session.add(WriteRecord(kind="object"))
            session.flush()
            return original_create(*args, **kwargs)
        service.bobj.create_instance_by_code = create
        service._ensure_container_link = lambda *args: session.add(WriteRecord(kind="lineage"))
        service._record_action = lambda **kwargs: session.add(WriteRecord(kind="action"))
        def fail(*args, **kwargs):
            raise ValueError("Response failure before commit")
        service._atlas_context_for_instance = fail
        with pytest.raises(ValueError, match="Response failure"):
            if operation == "tube":
                service.create_empty_tube(payload=tube_payload(), idempotency_key="example:request")
            else:
                service.register_accepted_material(payload=material_payload(), idempotency_key="example:request")
        assert session.scalar(select(func.count()).select_from(WriteRecord)) >= 2
        session.rollback()
    with SQLSession(engine) as verifier:
        assert verifier.scalar(select(func.count()).select_from(WriteRecord)) == 0
    engine.dispose()


@pytest.mark.parametrize("operation", ["tube", "material"])
def test_properties_cannot_override_authoritative_registration_tenant(service, operation):
    payload = tube_payload() if operation == "tube" else material_payload()
    payload.properties["atlas_registration_tenant_id"] = OTHER_TENANT
    with pytest.raises(ValueError, match="managed by atlas_context"):
        if operation == "tube":
            service.create_empty_tube(payload=payload, idempotency_key="example:request")
        else:
            service.register_accepted_material(payload=payload, idempotency_key="example:request")
    assert service.records == {}
    assert service.session.commits == 0


def test_tube_update_without_context_cannot_reassign_registration_tenant(service):
    from bloom_lims.schemas.beta_lab import BetaTubeUpdateRequest
    service.create_empty_tube(payload=tube_payload(), idempotency_key="example:create")
    with pytest.raises(ValueError, match="managed by atlas_context"):
        service.update_tube(container_euid="example:tube", payload=BetaTubeUpdateRequest(
            properties={"atlas_registration_tenant_id": OTHER_TENANT}))
    assert service._props(service.records["example:tube"])["atlas_registration_tenant_id"] == TENANT
