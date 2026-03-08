"""Focused tests for Bloom's modern beta action path and graph-first queue reads."""

from __future__ import annotations

import os
import secrets
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.core import action_execution as action_exec
from bloom_lims.core.tapdb_action_dispatcher import (
    BloomTapDBActionDispatcher,
    _normalize_action_slug,
)
from bloom_lims.tapdb_adapter import action_instance, action_instance_lineage, generic_instance

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _external_rw_user() -> APIUser:
    token = secrets.token_hex(8)
    return APIUser(
        email="beta-modern-actions@example.com",
        user_id=f"user-{token}",
        roles=["INTERNAL_READ_WRITE"],
        auth_source="token",
        is_service_account=True,
        token_scope="internal_rw",
        token_id=f"token-{token}",
    )


def _opaque(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _props(instance) -> dict:
    payload = instance.json_addl or {}
    props = payload.get("properties") if isinstance(payload, dict) else {}
    return dict(props) if isinstance(props, dict) else {}


def _clear_current_queue(bdb, euid: str) -> None:
    instance = (
        bdb.session.query(bdb.Base.classes.generic_instance)
        .filter(
            bdb.Base.classes.generic_instance.euid == euid,
            bdb.Base.classes.generic_instance.is_deleted.is_(False),
        )
        .one()
    )
    payload = instance.json_addl or {}
    props = dict(payload.get("properties") or {})
    props.pop("current_queue", None)
    payload["properties"] = props
    instance.json_addl = payload
    bdb.session.commit()


def test_action_key_slug_normalization():
    assert _normalize_action_slug("/workflow/step/set-object-status/") == "set_object_status"
    assert _normalize_action_slug("custom-action") == "custom_action"
    assert _normalize_action_slug("") == ""


def test_bloom_dispatcher_dynamic_handler_mapping():
    calls: dict[str, object] = {}

    class _Executor:
        def do_action_create_label(self, euid, action_ds):
            calls["create_label"] = (euid, action_ds)
            return {"status": "success", "message": "created"}

        def do_action_set_object_status(self, euid, action_ds, action_group, raw_key):
            calls["set_status"] = (euid, action_ds, action_group, raw_key)
            return {"status": "success", "message": "updated"}

    instance = SimpleNamespace(euid="OB_TEST")
    dispatcher = BloomTapDBActionDispatcher(_Executor())

    generic = getattr(dispatcher, "do_action_create-label")
    generic_result = generic(instance, {"captured_data": {"a": 1}}, {"b": 2})
    assert generic_result["status"] == "success"
    assert calls["create_label"][0] == "OB_TEST"
    assert calls["create_label"][1]["captured_data"] == {"a": 1, "b": 2}

    set_status = getattr(dispatcher, "do_action_/workflow/step/set-object-status/")
    status_result = set_status(
        instance,
        {"captured_data": {"status": "ready"}, "action_group": "state"},
        {"note": "ok"},
    )
    assert status_result["status"] == "success"
    _, payload, group, raw_key = calls["set_status"]
    assert payload["captured_data"]["note"] == "ok"
    assert group == "state"
    assert raw_key == "/workflow/step/set-object-status/"


def test_bloom_dispatcher_updates_nested_action_groups(monkeypatch):
    dispatcher = BloomTapDBActionDispatcher(SimpleNamespace())
    instance = SimpleNamespace(
        json_addl={
            "action_groups": {
                "state": {
                    "actions": {
                        "/set-status/": {
                            "action_executed": "0",
                            "executed_datetime": [],
                        }
                    }
                }
            }
        }
    )
    monkeypatch.setattr("bloom_lims.core.tapdb_action_dispatcher.flag_modified", lambda *_: None)
    dispatcher._update_action_tracking(instance, "state", "/set-status/", {"status": "success"})
    action_entry = instance.json_addl["action_groups"]["state"]["actions"]["/set-status/"]
    assert action_entry["action_executed"] == "1"
    assert len(action_entry["executed_datetime"]) == 1


def test_action_execute_payload_validation():
    payload = action_exec.normalize_action_execute_payload(
        {
            "euid": "OB1",
            "action_group": "state",
            "action_key": "/set-status/",
            "captured_data": {"status": "ready"},
        }
    )
    assert payload.euid == "OB1"
    assert payload.action_group == "state"

    with pytest.raises(action_exec.ActionExecutionError) as missing_euid:
        action_exec.normalize_action_execute_payload(
            {"action_group": "state", "action_key": "k", "captured_data": {}}
        )
    assert missing_euid.value.status_code == 400
    assert "euid" in missing_euid.value.error_fields

    with pytest.raises(action_exec.ActionExecutionError) as missing_captured:
        action_exec.normalize_action_execute_payload(
            {"euid": "OB1", "action_group": "state", "action_key": "k"}
        )
    assert missing_captured.value.status_code == 400
    assert "captured_data" in missing_captured.value.error_fields


def test_action_execute_payload_rejects_non_dict_and_missing_fields():
    with pytest.raises(action_exec.ActionExecutionError) as non_dict:
        action_exec.normalize_action_execute_payload("bad-payload")  # type: ignore[arg-type]
    assert non_dict.value.status_code == 400

    with pytest.raises(action_exec.ActionExecutionError) as missing_group:
        action_exec.normalize_action_execute_payload(
            {"euid": "OB1", "action_key": "k", "captured_data": {}}
        )
    assert "action_group" in missing_group.value.error_fields

    with pytest.raises(action_exec.ActionExecutionError) as missing_key:
        action_exec.normalize_action_execute_payload(
            {"euid": "OB1", "action_group": "g", "captured_data": {}}
        )
    assert "action_key" in missing_key.value.error_fields


def test_action_required_field_extraction_and_missing_detection():
    ui_required = action_exec._extract_required_fields_from_ui_schema(
        {
            "ui_schema": {
                "fields": [
                    {"name": "status", "required": True},
                    {"name": "note", "required": False},
                ]
            }
        }
    )
    assert ui_required == ["status"]

    legacy_required = action_exec._extract_required_fields_from_legacy_markup(
        {
            "captured_data": {
                "status": '<input name="status" required>',
                "optional": '<input name="optional">',
            }
        }
    )
    assert legacy_required == ["status"]

    assert action_exec._missing_required_fields({"status": ""}, ["status"]) == ["status"]
    assert action_exec._missing_required_fields({"status": "ready"}, ["status"]) == []


def test_action_safe_get_by_euid_swallow_not_found():
    class _Obj:
        def get_by_euid(self, _euid):
            raise RuntimeError("Object not found")

    assert action_exec._safe_get_by_euid(_Obj(), "missing") is None


def test_action_safe_get_by_euid_raises_unexpected_errors():
    class _Obj:
        def get_by_euid(self, _euid):
            raise RuntimeError("database offline")

    with pytest.raises(RuntimeError):
        action_exec._safe_get_by_euid(_Obj(), "anything")


def test_action_required_field_extractors_handle_non_schema():
    assert action_exec._extract_required_fields_from_ui_schema({"ui_schema": None}) == []
    assert action_exec._extract_required_fields_from_legacy_markup({"captured_data": None}) == []


def test_action_extract_legacy_required_uses_key_fallback_and_collection_missing():
    required = action_exec._extract_required_fields_from_legacy_markup(
        {"captured_data": {"batch_id": "<input required>"}}
    )
    assert required == ["batch_id"]

    missing = action_exec._missing_required_fields(
        {"batch_id": [], "other": None, "meta": {}},
        ["batch_id", "other", "meta"],
    )
    assert missing == ["batch_id", "other", "meta"]


def test_action_definition_resolution_errors():
    instance = SimpleNamespace(
        euid="OB3",
        json_addl={"action_groups": {"state": {"actions": {"go": {"captured_data": {}}}}}},
    )

    with pytest.raises(action_exec.ActionExecutionError) as missing_group:
        action_exec._resolve_action_definition(instance, "missing", "go")
    assert missing_group.value.status_code == 404

    with pytest.raises(action_exec.ActionExecutionError) as missing_action:
        action_exec._resolve_action_definition(instance, "state", "missing")
    assert missing_action.value.status_code == 404

    with pytest.raises(action_exec.ActionExecutionError) as missing_meta:
        action_exec._resolve_action_definition(instance, "state", "go")
    assert missing_meta.value.status_code == 409


def test_action_build_ds_sets_actor_and_preferences():
    built = action_exec._build_action_ds(
        {
            "action_template_uid": str(uuid.uuid4()),
            "captured_data": {"existing": "x"},
        },
        {"entered": "y"},
        actor_email="actor@example.com",
        actor_user_id="user-1",
        user_preferences={
            "print_lab": "BETA",
            "printer_name": "printer-1",
            "label_style": "tube",
            "alt_a": "A",
            "alt_b": "B",
            "alt_c": "C",
            "alt_d": "D",
            "alt_e": "E",
        },
    )
    assert built["captured_data"] == {"existing": "x", "entered": "y"}
    assert built["curr_user"] == "actor@example.com"
    assert built["curr_user_id"] == "user-1"
    assert built["lab"] == "BETA"
    assert built["printer_name"] == "printer-1"
    assert built["label_style"] == "tube"
    assert built["label_zpl_style"] == "tube"
    assert built["alt_e"] == "E"


def test_action_execute_success_and_not_found(monkeypatch):
    class _FakeBdb:
        def __init__(self):
            self.session = object()
            self.closed = False

        def close(self):
            self.closed = True

    fake_bdb = _FakeBdb()
    monkeypatch.setattr(action_exec, "BLOOMdb3", lambda app_username=None: fake_bdb)
    monkeypatch.setattr(action_exec, "BloomObj", lambda *_: SimpleNamespace())

    request_data = action_exec.ActionExecuteRequest(
        euid="OB2",
        action_group="state",
        action_key="/set-status/",
        captured_data={"status": "ready"},
    )

    monkeypatch.setattr(action_exec, "_safe_get_by_euid", lambda *_: None)
    with pytest.raises(action_exec.ActionExecutionError) as missing:
        action_exec.execute_action_for_instance(
            request_data,
            app_username="tester",
            actor_email="tester@example.com",
            actor_user_id="u-1",
            user_preferences={},
        )
    assert missing.value.status_code == 404

    target_instance = SimpleNamespace(
        euid="OB2",
        category="object",
        type="generic",
        subtype="x",
        version="1.0",
    )
    monkeypatch.setattr(action_exec, "_safe_get_by_euid", lambda *_: target_instance)
    monkeypatch.setattr(
        action_exec,
        "_resolve_action_definition",
        lambda *_: {"action_template_uid": str(uuid.uuid4()), "captured_data": {}, "ui_schema": {"fields": []}},
    )
    monkeypatch.setattr(
        action_exec,
        "_build_action_ds",
        lambda *_args, **_kwargs: {"action_template_uid": str(uuid.uuid4()), "captured_data": {}},
    )

    class _Executor:
        def set_actor_context(self, user_id=None, email=None):
            self.user_id = user_id
            self.email = email

    monkeypatch.setattr(action_exec, "_resolve_executor", lambda *_: _Executor())

    class _Dispatcher:
        def __init__(self, _executor):
            self.executor = _executor

        def execute_action(self, **_kwargs):
            return {"status": "success", "message": "ok"}

    monkeypatch.setattr(action_exec, "BloomTapDBActionDispatcher", _Dispatcher)
    response = action_exec.execute_action_for_instance(
        request_data,
        app_username="tester",
        actor_email="tester@example.com",
        actor_user_id="u-1",
        user_preferences={"print_lab": "BLOOM"},
    )
    assert response["status"] == "success"
    assert response["euid"] == "OB2"
    assert fake_bdb.closed is True


def test_action_execute_missing_required_fields_and_message_fallback(monkeypatch):
    class _FakeBdb:
        def __init__(self):
            self.session = object()

        def close(self):
            raise RuntimeError("close failure should be swallowed")

    fake_bdb = _FakeBdb()
    monkeypatch.setattr(action_exec, "BLOOMdb3", lambda app_username=None: fake_bdb)
    monkeypatch.setattr(action_exec, "BloomObj", lambda *_: SimpleNamespace())

    request_data = action_exec.ActionExecuteRequest(
        euid="OB4",
        action_group="state",
        action_key="/set-status/",
        captured_data={},
    )
    target_instance = SimpleNamespace(
        euid="OB4",
        category="object",
        type="generic",
        subtype="x",
        version="1.0",
    )
    monkeypatch.setattr(action_exec, "_safe_get_by_euid", lambda *_: target_instance)
    monkeypatch.setattr(
        action_exec,
        "_resolve_action_definition",
        lambda *_: {
            "action_template_uid": str(uuid.uuid4()),
            "captured_data": {},
            "ui_schema": {"fields": [{"name": "status", "required": True}]},
        },
    )

    with pytest.raises(action_exec.ActionExecutionError) as missing_required:
        action_exec.execute_action_for_instance(
            request_data,
            app_username="tester",
            actor_email="tester@example.com",
            actor_user_id="u-1",
            user_preferences={},
        )
    assert missing_required.value.status_code == 400
    assert missing_required.value.error_fields == ["status"]

    ready_request = action_exec.ActionExecuteRequest(
        euid="OB4",
        action_group="state",
        action_key="/set-status/",
        captured_data={"status": "ready"},
    )
    monkeypatch.setattr(
        action_exec,
        "_build_action_ds",
        lambda *_args, **_kwargs: {"action_template_uid": str(uuid.uuid4()), "captured_data": {}},
    )

    class _Executor:
        def set_actor_context(self, **_kwargs):
            return None

    monkeypatch.setattr(action_exec, "_resolve_executor", lambda *_: _Executor())

    class _Dispatcher:
        def __init__(self, _executor):
            pass

        def execute_action(self, **_kwargs):
            return "custom success message"

    monkeypatch.setattr(action_exec, "BloomTapDBActionDispatcher", _Dispatcher)
    response = action_exec.execute_action_for_instance(
        ready_request,
        app_username="tester",
        actor_email="tester@example.com",
        actor_user_id="u-1",
        user_preferences={},
    )
    assert response["message"] == "custom success message"


def test_action_map_exception_variants():
    mapped_key = action_exec._map_exception(KeyError("status"))
    assert mapped_key.status_code == 400
    assert mapped_key.error_fields == ["status"]

    mapped_validation = action_exec._map_exception(
        action_exec.BloomValidationError("invalid", details={"field": "status"})
    )
    assert mapped_validation.status_code == 400
    assert mapped_validation.error_fields == ["status"]

    mapped_ref = action_exec._map_exception(Exception("No instance refs were provided for action"))
    assert mapped_ref.status_code == 400
    assert mapped_ref.error_fields == ["instance_refs"]

    mapped_missing_field = action_exec._map_exception(Exception("Missing required field: alpha"))
    assert mapped_missing_field.status_code == 400
    assert mapped_missing_field.error_fields == ["alpha"]

    mapped_invalid = action_exec._map_exception(Exception("invalid payload"))
    assert mapped_invalid.status_code == 400

    mapped_unhandled = action_exec._map_exception(Exception("unexpected"))
    assert mapped_unhandled.status_code == 500
    assert "error_id" in mapped_unhandled.to_payload()


def test_action_map_exception_passthrough_for_structured_errors():
    structured = action_exec.ActionExecutionError(status_code=409, detail="conflict")
    mapped = action_exec._map_exception(structured)
    assert mapped is structured


def test_action_resolve_executor_branches(monkeypatch):
    class _Workflow:
        def __init__(self, bdb):
            self.bdb = bdb

    class _WorkflowStep:
        def __init__(self, bdb):
            self.bdb = bdb

    class _Obj:
        def __init__(self, bdb):
            self.bdb = bdb

    monkeypatch.setattr("bloom_lims.domain.workflows.BloomWorkflow", _Workflow)
    monkeypatch.setattr("bloom_lims.domain.workflows.BloomWorkflowStep", _WorkflowStep)
    monkeypatch.setattr(action_exec, "BloomObj", _Obj)

    fake_bdb = object()
    wf_exec = action_exec._resolve_executor(SimpleNamespace(category="workflow"), fake_bdb)
    step_exec = action_exec._resolve_executor(SimpleNamespace(category="workflow_step"), fake_bdb)
    obj_exec = action_exec._resolve_executor(SimpleNamespace(category="container"), fake_bdb)

    assert isinstance(wf_exec, _Workflow)
    assert isinstance(step_exec, _WorkflowStep)
    assert isinstance(obj_exec, _Obj)


def test_dispatcher_execute_action_persists_tapdb_action_lineage(bdb):
    target = (
        bdb.session.query(generic_instance)
        .filter(generic_instance.is_deleted.is_(False))
        .first()
    )
    assert target is not None

    payload = dict(target.json_addl or {})
    payload["action_groups"] = {
        "state": {
            "actions": {
                "create-label": {"action_executed": "0", "executed_datetime": []},
            }
        }
    }
    target.json_addl = payload
    flag_modified(target, "json_addl")
    bdb.session.commit()

    class _Executor:
        def do_action_create_label(self, euid, action_ds):
            assert euid == target.euid
            return {"status": "success", "message": "ok"}

    dispatcher = BloomTapDBActionDispatcher(_Executor())
    result = dispatcher.execute_action(
        session=bdb.session,
        instance=target,
        action_group="state",
        action_key="create-label",
        action_ds={"action_template_uid": target.template_uid, "captured_data": {}},
        captured_data={"note": "pytest"},
        create_action_record=True,
        user="pytest@example.com",
    )
    assert result["status"] == "success"

    record = (
        bdb.session.query(action_instance)
        .filter(
            action_instance.subtype == "create_label",
            action_instance.is_deleted.is_(False),
        )
        .order_by(action_instance.created_dt.desc())
        .first()
    )
    assert record is not None
    assert record.json_addl["action_key"] == "create-label"
    assert record.json_addl["captured_data"]["note"] == "pytest"

    linkage = (
        bdb.session.query(action_instance_lineage)
        .filter(
            action_instance_lineage.parent_instance_uid == record.uid,
            action_instance_lineage.child_instance_uid == target.uid,
            action_instance_lineage.relationship_type == "executed_on",
            action_instance_lineage.is_deleted.is_(False),
        )
        .first()
    )
    assert linkage is not None


def test_legacy_actions_surface_is_not_available():
    with TestClient(app) as client:
        info = client.get("/api/v1/")
        assert info.status_code == 200
        assert "actions" not in info.json()["endpoints"]

        actions = client.get("/api/v1/actions/")
        assert actions.status_code == 404

        aliquot = client.post("/api/v1/actions/aliquot", json={})
        assert aliquot.status_code == 404


def test_beta_flow_records_modern_action_instances(bdb):
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    atlas_context = {
        "atlas_tenant_id": _opaque("tenant"),
        "atlas_trf_euid": _opaque("trf"),
        "process_items": [
            {
                "atlas_test_euid": _opaque("test"),
                "atlas_test_process_item_euid": _opaque("proc"),
            }
        ],
    }

    with TestClient(app) as client:
        material = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": _opaque("idem-material")},
            json={
                "specimen_name": "beta-action-material",
                "properties": {"source": "pytest-modern-actions"},
                "atlas_context": atlas_context,
            },
        )
        assert material.status_code == 200, material.text
        specimen_euid = material.json()["specimen_euid"]

        queued = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{specimen_euid}",
            headers={"Idempotency-Key": _opaque("idem-queue")},
            json={"metadata": {"reason": "accepted-material"}},
        )
        assert queued.status_code == 200, queued.text

        extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract")},
            json={
                "source_specimen_euid": specimen_euid,
                "plate_name": "beta-action-plate",
                "well_name": "A1",
                "extraction_type": "cfdna",
                "output_name": "beta-action-output",
                "atlas_test_process_item_euid": atlas_context["process_items"][0]["atlas_test_process_item_euid"],
            },
        )
        assert extraction.status_code == 200, extraction.text
        extraction_output_euid = extraction.json()["extraction_output_euid"]

        qc = client.post(
            "/api/v1/external/atlas/beta/post-extract-qc",
            headers={"Idempotency-Key": _opaque("idem-qc")},
            json={
                "extraction_output_euid": extraction_output_euid,
                "passed": True,
                "next_queue": "ilmn_lib_prep",
            },
        )
        assert qc.status_code == 200, qc.text

        library_prep = client.post(
            "/api/v1/external/atlas/beta/library-prep",
            headers={"Idempotency-Key": _opaque("idem-libprep")},
            json={
                "source_extraction_output_euid": extraction_output_euid,
                "platform": "ILMN",
                "output_name": "beta-action-lib",
            },
        )
        assert library_prep.status_code == 200, library_prep.text
        lib_output_euid = library_prep.json()["library_prep_output_euid"]

        pool = client.post(
            "/api/v1/external/atlas/beta/pools",
            headers={"Idempotency-Key": _opaque("idem-pool")},
            json={
                "member_euids": [lib_output_euid],
                "platform": "ILMN",
                "pool_name": "beta-action-pool",
            },
        )
        assert pool.status_code == 200, pool.text
        pool_euid = pool.json()["pool_euid"]

        run = client.post(
            "/api/v1/external/atlas/beta/runs",
            headers={"Idempotency-Key": _opaque("idem-run")},
            json={
                "pool_euid": pool_euid,
                "platform": "ILMN",
                "flowcell_id": "FLOW-ACTION-01",
                "run_name": "beta-action-run",
                "status": "completed",
                "assignments": [
                    {
                        "lane": "1",
                        "library_barcode": "IDX-ACT-1",
                        "library_prep_output_euid": lib_output_euid,
                    }
                ],
                "artifacts": [],
            },
        )
        assert run.status_code == 200, run.text
        run_euid = run.json()["run_euid"]

    subtypes = {
        row.subtype
        for row in bdb.session.query(action_instance)
        .filter(action_instance.type == "beta_lab", action_instance.is_deleted.is_(False))
        .all()
    }
    assert {
        "register_accepted_material",
        "move_material_to_queue",
        "create_extraction",
        "record_post_extract_qc",
        "create_library_prep",
        "create_pool",
        "create_run",
    }.issubset(subtypes)

    run_action = (
        bdb.session.query(action_instance)
        .filter(
            action_instance.type == "beta_lab",
            action_instance.subtype == "create_run",
            action_instance.is_deleted.is_(False),
        )
        .order_by(action_instance.created_dt.desc())
        .first()
    )
    assert run_action is not None
    assert "target_instance_euid" not in (run_action.json_addl or {})
    assert "target_instance_uid" not in (run_action.json_addl or {})

    link = (
        bdb.session.query(action_instance_lineage)
        .filter(
            action_instance_lineage.parent_instance_uid == run_action.uid,
            action_instance_lineage.relationship_type == "executed_on",
            action_instance_lineage.is_deleted.is_(False),
        )
        .first()
    )
    assert link is not None
    assert link.child_instance.euid == run_euid


def test_beta_flow_does_not_call_legacy_do_action(monkeypatch):
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    def _fail(*args, **kwargs):  # pragma: no cover - assertion path only
        raise AssertionError("legacy do_action must not be called by beta endpoints")

    from bloom_lims.domain.base import BloomObj

    monkeypatch.setattr(BloomObj, "do_action", _fail)

    atlas_context = {
        "atlas_tenant_id": _opaque("tenant"),
        "atlas_trf_euid": _opaque("trf"),
        "process_items": [
            {
                "atlas_test_euid": _opaque("test"),
                "atlas_test_process_item_euid": _opaque("proc"),
            }
        ],
    }

    with TestClient(app) as client:
        material = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": _opaque("idem-material")},
            json={"specimen_name": "beta-no-do-action", "atlas_context": atlas_context},
        )
        assert material.status_code == 200, material.text

        specimen_euid = material.json()["specimen_euid"]
        queued = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{specimen_euid}",
            headers={"Idempotency-Key": _opaque("idem-queue")},
            json={"metadata": {}},
        )
        assert queued.status_code == 200, queued.text


def test_queue_reads_work_without_current_queue_cache(bdb):
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    atlas_context = {
        "atlas_tenant_id": _opaque("tenant"),
        "atlas_trf_euid": _opaque("trf"),
        "process_items": [
            {
                "atlas_test_euid": _opaque("test"),
                "atlas_test_process_item_euid": _opaque("proc"),
            }
        ],
    }

    with TestClient(app) as client:
        material = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": _opaque("idem-material")},
            json={"specimen_name": "beta-graph-queue", "atlas_context": atlas_context},
        )
        assert material.status_code == 200, material.text
        specimen_euid = material.json()["specimen_euid"]

        queued = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{specimen_euid}",
            headers={"Idempotency-Key": _opaque("idem-queue")},
            json={"metadata": {"reason": "graph-fallback"}},
        )
        assert queued.status_code == 200, queued.text
        _clear_current_queue(bdb, specimen_euid)

        extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract")},
            json={
                "source_specimen_euid": specimen_euid,
                "plate_name": "beta-graph-plate",
                "well_name": "A1",
                "extraction_type": "gdna",
                "atlas_test_process_item_euid": atlas_context["process_items"][0]["atlas_test_process_item_euid"],
            },
        )
        assert extraction.status_code == 200, extraction.text
        extraction_output_euid = extraction.json()["extraction_output_euid"]

        qc = client.post(
            "/api/v1/external/atlas/beta/post-extract-qc",
            headers={"Idempotency-Key": _opaque("idem-qc")},
            json={
                "extraction_output_euid": extraction_output_euid,
                "passed": True,
                "next_queue": "ont_lib_prep",
            },
        )
        assert qc.status_code == 200, qc.text

        library_prep = client.post(
            "/api/v1/external/atlas/beta/library-prep",
            headers={"Idempotency-Key": _opaque("idem-libprep")},
            json={
                "source_extraction_output_euid": extraction_output_euid,
                "platform": "ONT",
            },
        )
        assert library_prep.status_code == 200, library_prep.text
        lib_output_euid = library_prep.json()["library_prep_output_euid"]
        _clear_current_queue(bdb, lib_output_euid)

        pool = client.post(
            "/api/v1/external/atlas/beta/pools",
            headers={"Idempotency-Key": _opaque("idem-pool")},
            json={
                "member_euids": [lib_output_euid],
                "platform": "ONT",
            },
        )
        assert pool.status_code == 200, pool.text
        pool_euid = pool.json()["pool_euid"]
        _clear_current_queue(bdb, pool_euid)

        run = client.post(
            "/api/v1/external/atlas/beta/runs",
            headers={"Idempotency-Key": _opaque("idem-run")},
            json={
                "pool_euid": pool_euid,
                "platform": "ONT",
                "flowcell_id": "FLOW-GRAPH-01",
                "status": "completed",
                "assignments": [
                    {
                        "lane": "2",
                        "library_barcode": "IDX-GRAPH-1",
                        "library_prep_output_euid": lib_output_euid,
                    }
                ],
                "artifacts": [],
            },
        )
        assert run.status_code == 200, run.text

        resolved = client.get(
            f"/api/v1/external/atlas/beta/runs/{run.json()['run_euid']}/resolve",
            params={
                "flowcell_id": "FLOW-GRAPH-01",
                "lane": "2",
                "library_barcode": "IDX-GRAPH-1",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert (
            resolved.json()["atlas_test_process_item_euid"]
            == atlas_context["process_items"][0]["atlas_test_process_item_euid"]
        )
