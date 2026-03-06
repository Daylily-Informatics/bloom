"""Tests for /api/v1/actions/execute and /workflow_step_action alias."""

import os
import sys
import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402
from bloom_lims.api.v1.dependencies import APIUser, require_read, require_write  # noqa: E402
from bloom_lims.db import BLOOMdb3  # noqa: E402
from bloom_lims.domain.base import BloomObj  # noqa: E402

TERMINAL_STATUSES = {"complete", "abandoned", "failed"}


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver",  raise_server_exceptions=False)


@pytest.fixture
def write_user_override():
    async def _override() -> APIUser:
        return APIUser(
            email="actions-rw@example.com",
            user_id=str(uuid.uuid4()),
            roles=["INTERNAL_READ_WRITE"],
            auth_source="session",
        )

    app.dependency_overrides[require_write] = _override
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_write, None)


@pytest.fixture
def read_user_override():
    async def _override() -> APIUser:
        return APIUser(
            email="actions-ro@example.com",
            user_id=str(uuid.uuid4()),
            roles=["INTERNAL_READ_WRITE"],
            auth_source="session",
        )

    app.dependency_overrides[require_read] = _override
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_read, None)


def _iter_instance_actions(limit: int = 2000):
    bdb = BLOOMdb3(app_username="pytest-actions")
    try:
        query = (
            bdb.session.query(bdb.Base.classes.generic_instance)
            .filter(bdb.Base.classes.generic_instance.is_deleted == False)
            .limit(limit)
        )
        for instance in query:
            json_addl = instance.json_addl if isinstance(instance.json_addl, dict) else {}
            action_groups = json_addl.get("action_groups", {})
            if not isinstance(action_groups, dict):
                continue
            for group_name, group_data in action_groups.items():
                actions = group_data.get("actions", {}) if isinstance(group_data, dict) else {}
                if not isinstance(actions, dict):
                    continue
                for action_key, action_ds in actions.items():
                    if not isinstance(action_ds, dict):
                        continue
                    yield instance, group_name, action_key, action_ds
    finally:
        bdb.close()


def _find_any_action_target() -> tuple[str, str, str]:
    for instance, group_name, action_key, _action_ds in _iter_instance_actions():
        return instance.euid, group_name, action_key

    # Fresh test databases may have templates but no instances yet. Create a
    # minimal instance so the execute endpoint can be exercised deterministically.
    _create_instance("container", "tube", "tube-generic-10ml", "1.0")

    for instance, group_name, action_key, _action_ds in _iter_instance_actions():
        return instance.euid, group_name, action_key
    raise RuntimeError("No action-bearing instance found after creating a fixture instance")


def _inject_required_test_action(euid: str) -> tuple[str, str, str]:
    action_group = "pytest_required"
    action_key = "action/pytest/required-validation/1.0"
    required_field = "required_input"

    bdb = BLOOMdb3(app_username="pytest-actions")
    try:
        bobj = BloomObj(bdb)
        instance = bobj.get_by_euid(euid)
        json_addl = instance.json_addl if isinstance(instance.json_addl, dict) else {}
        action_groups = json_addl.setdefault("action_groups", {})
        action_groups[action_group] = {
            "group_name": "Pytest Required",
            "group_order": "999",
            "actions": {
                action_key: {
                    "action_name": "Pytest Required Validation",
                    "method_name": "do_action_set_object_status",
                    "action_executed": "0",
                    "max_executions": "-1",
                    "action_enabled": "1",
                    "capture_data": "yes",
                    "captured_data": {},
                    "deactivate_actions_when_executed": [],
                    "executed_datetime": [],
                    "action_order": "0",
                    "action_simple_value": "",
                    "action_user": [],
                    "curr_user": "",
                    "ui_schema": {
                        "title": "Pytest Required Validation",
                        "fields": [
                            {
                                "name": required_field,
                                "label": "Required Input",
                                "type": "text",
                                "required": True,
                            }
                        ],
                    },
                }
            },
        }
        instance.json_addl = json_addl
        flag_modified(instance, "json_addl")
        bdb.session.commit()
    finally:
        bdb.close()

    return action_group, action_key, required_field


def _find_set_status_target() -> tuple[str, str, str, str]:
    for instance, group_name, action_key, action_ds in _iter_instance_actions(limit=4000):
        if action_ds.get("method_name") != "do_action_set_object_status":
            continue
        current_status = str(getattr(instance, "bstatus", "") or "")
        if current_status in TERMINAL_STATUSES:
            continue
        next_status = "complete" if current_status == "in_progress" else "in_progress"
        return instance.euid, group_name, action_key, next_status

    # Ensure a deterministic target exists in fresh databases.
    _create_instance("container", "tube", "tube-generic-10ml", "1.0")
    for instance, group_name, action_key, action_ds in _iter_instance_actions(limit=4000):
        if action_ds.get("method_name") != "do_action_set_object_status":
            continue
        current_status = str(getattr(instance, "bstatus", "") or "")
        if current_status in TERMINAL_STATUSES:
            continue
        next_status = "complete" if current_status == "in_progress" else "in_progress"
        return instance.euid, group_name, action_key, next_status

    raise RuntimeError("No suitable do_action_set_object_status target found after creating a fixture instance")


def _get_status(euid: str) -> str:
    bdb = BLOOMdb3(app_username="pytest-actions")
    try:
        bobj = BloomObj(bdb)
        return str(bobj.get_by_euid(euid).bstatus)
    finally:
        bdb.close()


def _create_instance(category: str, type_name: str, subtype: str, version: str = "1.0") -> str:
    bdb = BLOOMdb3(app_username="pytest-actions")
    try:
        bob = BloomObj(bdb)
        templates = bob.query_template_by_component_v2(category, type_name, subtype, version)
        if not templates:
            raise RuntimeError(f"Template not found for {category}/{type_name}/{subtype}/{version}")
        parent_parts = bob.create_instances(templates[0].euid)
        parent = parent_parts[0][0]
        return str(parent.euid)
    finally:
        bdb.close()


def _inject_action(euid: str, *, action_group: str, action_key: str, action_ds: dict[str, Any]) -> None:
    bdb = BLOOMdb3(app_username="pytest-actions")
    try:
        bob = BloomObj(bdb)
        instance = bob.get_by_euid(euid)
        json_addl = instance.json_addl if isinstance(instance.json_addl, dict) else {}
        action_groups = json_addl.setdefault("action_groups", {})
        action_groups[action_group] = {
            "group_name": action_group,
            "group_order": "999",
            "actions": {action_key: action_ds},
        }
        instance.json_addl = json_addl
        flag_modified(instance, "json_addl")
        bdb.session.commit()
    finally:
        bdb.close()


def test_execute_action_requires_auth(client):
    async def _deny_auth() -> APIUser:
        raise HTTPException(status_code=401, detail="Authentication required")

    app.dependency_overrides[require_write] = _deny_auth
    try:
        response = client.post("/api/v1/actions/execute", json={})
    finally:
        app.dependency_overrides.pop(require_write, None)

    assert response.status_code == 401


def test_execute_action_requires_write_permission(client):
    async def _deny_write() -> APIUser:
        raise HTTPException(status_code=403, detail="Write permission required")

    app.dependency_overrides[require_write] = _deny_write
    try:
        response = client.post("/api/v1/actions/execute", json={})
    finally:
        app.dependency_overrides.pop(require_write, None)

    assert response.status_code == 403


def test_execute_action_unknown_euid_returns_404(client, write_user_override):
    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": "NONEXISTENT-EUID-XYZ",
            "action_group": "core",
            "action_key": "set_status",
            "captured_data": {},
        },
    )
    assert response.status_code == 404
    payload = response.json()
    assert "Object not found" in payload.get("detail", "")


def test_execute_action_unknown_action_returns_404(client, write_user_override):
    euid, action_group, _action_key = _find_any_action_target()
    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": euid,
            "action_group": action_group,
            "action_key": "action/does-not-exist/1.0",
            "captured_data": {},
        },
    )
    assert response.status_code == 404
    payload = response.json()
    assert "Action not found" in payload.get("detail", "")


def test_execute_action_missing_required_field_returns_400(client, write_user_override):
    euid, _group, _action_key = _find_any_action_target()
    action_group, action_key, required_field = _inject_required_test_action(euid)
    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": euid,
            "action_group": action_group,
            "action_key": action_key,
            "captured_data": {},
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert "Missing required fields" in payload.get("detail", "")
    assert required_field in payload.get("error_fields", [])


def test_execute_action_set_object_status_success(client, write_user_override):
    euid, action_group, action_key, target_status = _find_set_status_target()

    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": euid,
            "action_group": action_group,
            "action_key": action_key,
            "captured_data": {"object_status": target_status},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "success"
    assert payload.get("euid") == euid
    assert _get_status(euid) == target_status


def test_workflow_step_action_alias_returns_json_error(client):
    response = client.post("/workflow_step_action", json={})
    assert response.status_code == 400
    assert response.headers.get("content-type", "").startswith("application/json")
    payload = response.json()
    assert payload.get("detail") == "Missing required field: euid"
    assert payload.get("error_fields") == ["euid"]


def test_workflow_step_action_alias_success(client):
    euid, action_group, action_key, target_status = _find_set_status_target()
    response = client.post(
        "/workflow_step_action",
        json={
            "euid": euid,
            "action_group": action_group,
            "action_key": action_key,
            "captured_data": {"object_status": target_status},
        },
    )
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload.get("status") == "success"
    assert payload.get("euid") == euid


def test_execute_action_set_verification_state_one_click(client, write_user_override):
    euid, _group, _action_key = _find_any_action_target()
    _inject_action(
        euid,
        action_group="pytest_verify",
        action_key="action/test_requisitions/set_verification_state/1.0",
        action_ds={
            "action_name": "Verify Test Req",
            "method_name": "do_action_set_verification_state",
            "action_executed": "0",
            "max_executions": "1",
            "action_enabled": "1",
            "capture_data": "no",
            "captured_data": {},
            "deactivate_actions_when_executed": [],
            "executed_datetime": [],
            "action_order": "0",
            "action_simple_value": "",
            "action_user": [],
            "curr_user": "",
            "ui_schema": {"title": "Verify", "fields": []},
        },
    )

    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": euid,
            "action_group": "pytest_verify",
            "action_key": "action/test_requisitions/set_verification_state/1.0",
            "captured_data": {},
        },
    )
    assert response.status_code == 200

    bdb = BLOOMdb3(app_username="pytest-actions")
    try:
        bob = BloomObj(bdb)
        inst = bob.get_by_euid(euid)
        props = inst.json_addl.get("properties", {}) if isinstance(inst.json_addl, dict) else {}
        assert props.get("verification_status") == "verified"
    finally:
        bdb.close()


def test_equipment_location_add_and_remove_container(client, write_user_override):
    parent_euid = _create_instance("container", "tube", "tube-generic-10ml", "1.0")
    child_euid = _create_instance("container", "tube", "tube-generic-10ml", "1.0")

    _inject_action(
        parent_euid,
        action_group="pytest_equipment_add",
        action_key="action/equipment/add-container-to/1.0",
        action_ds={
            "action_name": "Add Container To",
            "method_name": "do_action_add_container_to",
            "action_executed": "0",
            "max_executions": "-1",
            "action_enabled": "1",
            "capture_data": "yes",
            "captured_data": {},
            "deactivate_actions_when_executed": [],
            "executed_datetime": [],
            "action_order": "0",
            "action_simple_value": "",
            "action_user": [],
            "curr_user": "",
            "ui_schema": {
                "title": "Add Container",
                "fields": [
                    {"name": "container_euids", "type": "textarea", "required": True},
                ],
            },
        },
    )

    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": parent_euid,
            "action_group": "pytest_equipment_add",
            "action_key": "action/equipment/add-container-to/1.0",
            "captured_data": {"container_euids": child_euid},
        },
    )
    assert response.status_code == 200

    def _has_active_location():
        bdb = BLOOMdb3(app_username="pytest-actions")
        try:
            bob = BloomObj(bdb)
            child = bob.get_by_euid(child_euid)
            for lin in child.child_of_lineages:
                if lin.is_deleted:
                    continue
                if lin.relationship_type != "location":
                    continue
                if lin.parent_instance and lin.parent_instance.euid == parent_euid:
                    return True
            return False
        finally:
            bdb.close()

    assert _has_active_location() is True

    _inject_action(
        parent_euid,
        action_group="pytest_equipment_remove",
        action_key="action/equipment/remove-container-from/1.0",
        action_ds={
            "action_name": "Remove Container",
            "method_name": "do_action_remove_container_from",
            "action_executed": "0",
            "max_executions": "-1",
            "action_enabled": "1",
            "capture_data": "yes",
            "captured_data": {},
            "deactivate_actions_when_executed": [],
            "executed_datetime": [],
            "action_order": "0",
            "action_simple_value": "",
            "action_user": [],
            "curr_user": "",
            "ui_schema": {
                "title": "Remove Container",
                "fields": [
                    {"name": "container_euids", "type": "textarea", "required": True},
                ],
            },
        },
    )

    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": parent_euid,
            "action_group": "pytest_equipment_remove",
            "action_key": "action/equipment/remove-container-from/1.0",
            "captured_data": {"container_euids": child_euid},
        },
    )
    assert response.status_code == 200
    assert _has_active_location() is False


def test_execute_action_download_url_and_download_endpoint(client, write_user_override, read_user_override):
    euid, _group, _action_key = _find_any_action_target()
    _inject_action(
        euid,
        action_group="pytest_download",
        action_key="action/equipment/download-inventory-tsv/1.0",
        action_ds={
            "action_name": "Download Inventory TSV",
            "method_name": "do_action_generate_inventory_tsv",
            "action_executed": "0",
            "max_executions": "-1",
            "action_enabled": "1",
            "capture_data": "no",
            "captured_data": {},
            "deactivate_actions_when_executed": [],
            "executed_datetime": [],
            "action_order": "0",
            "action_simple_value": "",
            "action_user": [],
            "curr_user": "",
            "ui_schema": {"title": "Download", "fields": []},
        },
    )

    response = client.post(
        "/api/v1/actions/execute",
        json={
            "euid": euid,
            "action_group": "pytest_download",
            "action_key": "action/equipment/download-inventory-tsv/1.0",
            "captured_data": {},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("download_url")

    download = client.get(payload["download_url"])
    assert download.status_code == 200
    assert b"euid\ttype\tsubtype\tversion\tstatus\tname" in download.content.splitlines()[0]
