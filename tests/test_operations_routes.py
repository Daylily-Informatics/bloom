"""Focused tests for operations route behavior changes."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402



def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_workflows_redirect_endpoint_is_retired():
    client = _client()
    response = client.get("/workflows")
    assert response.status_code == 410


def test_admin_zebra_start_route_is_removed():
    client = _client()
    response = client.post("/admin/zebra/start", follow_redirects=False)
    assert response.status_code == 404


def test_ui_actions_execute_endpoint_bound_to_operations_module():
    client = _client()
    payload = {
        "euid": "OB_TEST_123",
        "action_group": "state",
        "action_key": "/state/set-object-status/",
        "captured_data": {"object_status": "ready"},
    }
    with patch(
        "bloom_lims.gui.routes.operations.execute_action_for_instance",
        return_value={"status": "success", "message": "ok"},
    ) as mocked_execute:
        response = client.post("/ui/actions/execute", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mocked_execute.assert_called_once()


def test_admin_route_redirects_non_admin_users():
    client = _client()
    with patch("bloom_lims.gui.routes.operations._is_admin_session", return_value=False):
        response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/user_home?admin_required=1"


def test_admin_zebra_start_route_stays_absent_for_non_admin():
    client = _client()
    response = client.post("/admin/zebra/start", headers={"accept": "application/json"})
    assert response.status_code == 404


def test_save_json_addl_key_accepts_empty_json_payload():
    client = _client()
    fake_obj = SimpleNamespace(json_addl={})
    fake_repo = SimpleNamespace(
        get_by_euid=lambda _euid: fake_obj,
        session=SimpleNamespace(commit=lambda: None),
    )

    with patch("bloom_lims.gui.routes.operations.BLOOMdb3", return_value=SimpleNamespace()):
        with patch("bloom_lims.gui.routes.operations.BloomObj", return_value=fake_repo):
            with patch("bloom_lims.gui.routes.operations.flag_modified") as mocked_flag:
                response = client.post(
                    "/save_json_addl_key",
                    json={
                        "euid": "OB_TEST_123",
                        "json_addl_key": "properties",
                        "json_data": {},
                    },
                    follow_redirects=False,
                )

    assert response.status_code == 303
    assert fake_obj.json_addl["properties"] == {}
    mocked_flag.assert_called_once_with(fake_obj, "json_addl")


def test_save_json_addl_key_requires_json_data():
    client = _client()
    response = client.post(
        "/save_json_addl_key",
        json={
            "euid": "OB_TEST_123",
            "json_addl_key": "properties",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "EUID, JSON key, or JSON data missing"


def test_save_json_addl_key_preserves_not_found_status():
    client = _client()
    fake_repo = SimpleNamespace(get_by_euid=lambda _euid: None)

    with patch("bloom_lims.gui.routes.operations.BLOOMdb3", return_value=SimpleNamespace()):
        with patch("bloom_lims.gui.routes.operations.BloomObj", return_value=fake_repo):
            response = client.post(
                "/save_json_addl_key",
                json={
                    "euid": "OB_TEST_404",
                    "json_addl_key": "properties",
                    "json_data": {},
                },
                follow_redirects=False,
            )

    assert response.status_code == 404
    assert response.json()["detail"] == "Object not found"
