"""Focused tests for operations route behavior changes."""

from __future__ import annotations

import os
import sys
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


def test_admin_start_zebra_reports_already_running():
    client = _client()
    with patch("bloom_lims.gui.routes.operations._zebra_command_status", return_value=("running", "ok")):
        response = client.post("/admin/zebra/start", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/admin?zebra_running=1"


def test_admin_start_zebra_returns_json_error_for_missing_command():
    client = _client()
    with patch("bloom_lims.gui.routes.operations._zebra_command_status", return_value=("stopped", "stopped")):
        with patch(
            "bloom_lims.gui.routes.operations._try_start_zebra_background",
            return_value=("command_not_found", "missing"),
        ):
            response = client.post(
                "/admin/zebra/start",
                headers={"accept": "application/json"},
            )

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "command_not_found"


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


def test_admin_zebra_start_returns_403_json_for_non_admin():
    client = _client()
    with patch("bloom_lims.gui.routes.operations._is_admin_session", return_value=False):
        response = client.post("/admin/zebra/start", headers={"accept": "application/json"})
    assert response.status_code == 403
    assert response.json().get("detail") == "Admin privileges required"
