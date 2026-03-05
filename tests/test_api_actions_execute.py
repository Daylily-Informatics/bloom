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
from bloom_lims.api.v1.dependencies import APIUser, require_write  # noqa: E402
from bloom_lims.db import BLOOMdb3  # noqa: E402
from bloom_lims.domain.base import BloomObj  # noqa: E402

TERMINAL_STATUSES = {"complete", "abandoned", "failed"}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


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
    raise RuntimeError("No action-bearing instance found in seeded test DB")


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
    raise RuntimeError("No suitable do_action_set_object_status target found")


def _get_status(euid: str) -> str:
    bdb = BLOOMdb3(app_username="pytest-actions")
    try:
        bobj = BloomObj(bdb)
        return str(bobj.get_by_euid(euid).bstatus)
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
