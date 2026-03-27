"""Focused tests for user token APIs."""

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


def test_user_token_create_returns_plaintext_once():
    client = _client()
    response = client.post(
        "/api/v1/user-tokens",
        json={
            "token_name": f"self-token-{time_ns()}",
            "scope": "internal_ro",
            "expires_in_days": 7,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token"]["token_name"].startswith("self-token-")
    assert payload["plaintext_token"].startswith("blm_")


def test_admin_issue_token_validates_selected_user_id():
    client = _client()
    response = client.post(
        "/api/v1/admin/user-tokens/issue",
        json={
            "user_id": "   ",
            "token_name": f"bad-owner-{time_ns()}",
            "scope": "internal_ro",
            "expires_in_days": 7,
        },
    )
    assert response.status_code == 400
    assert response.json().get("detail") == "Invalid user_id"
