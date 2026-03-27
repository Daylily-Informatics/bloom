"""Focused tests for admin group and token management routes."""

from __future__ import annotations

import os
import sys
from time import time_ns

from fastapi.testclient import TestClient


os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402



def _client() -> TestClient:
    return TestClient(app)


def test_add_group_member_is_deterministic_for_duplicates():
    client = _client()
    group_code = "API_ACCESS"
    user_id = f"api-user-{time_ns()}"

    first = client.post(
        f"/api/v1/admin/groups/{group_code}/members",
        json={"user_id": user_id},
    )
    assert first.status_code == 200
    assert first.json()["result"] in {"added", "reactivated"}

    second = client.post(
        f"/api/v1/admin/groups/{group_code}/members",
        json={"user_id": user_id},
    )
    assert second.status_code == 200
    assert second.json()["result"] == "exists"


def test_admin_can_issue_token_for_selected_user():
    client = _client()
    owner_user_id = f"selected-owner-{time_ns()}"

    response = client.post(
        "/api/v1/admin/user-tokens/issue",
        json={
            "user_id": owner_user_id,
            "token_name": f"selected-user-token-{time_ns()}",
            "scope": "internal_ro",
            "expires_in_days": 30,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token"]["user_id"] == owner_user_id
    assert payload["plaintext_token"].startswith("blm_")
