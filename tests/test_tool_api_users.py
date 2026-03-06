"""Tests for admin-managed Tool API user provisioning and token grants."""

import os
import sys
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, get_api_user

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def non_admin_user_override():
    def _override_get_api_user():
        return APIUser(
            email="non-admin@example.com",
            user_id=str(uuid.uuid4()),
            roles=["INTERNAL_READ_WRITE"],
            groups=["INTERNAL_READ_WRITE"],
            auth_source="session",
        )

    app.dependency_overrides[get_api_user] = _override_get_api_user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_api_user, None)


def _create_tool_user(
    client: TestClient,
    *,
    role: str = "INTERNAL_READ_WRITE",
    issue_initial_token: bool = True,
    external_key: str | None = None,
    initial_token: dict | None = None,
):
    key = external_key or f"atlas-{uuid.uuid4().hex[:12]}"
    payload = {
        "display_name": f"Atlas Tool {uuid.uuid4().hex[:6]}",
        "external_system_key": key,
        "role": role,
        "description": "pytest tool user",
        "issue_initial_token": issue_initial_token,
    }
    if initial_token is not None:
        payload["initial_token"] = initial_token
    response = client.post(
        "/api/v1/admin/tool-api-users",
        json=payload,
    )
    return response


def test_create_tool_user_assigns_default_rw_and_initial_token(client: TestClient):
    response = _create_tool_user(client)
    assert response.status_code == 200
    payload = response.json()

    assert payload["tool_user"]["role"] == "INTERNAL_READ_WRITE"
    assert payload["plaintext_token"].startswith("blm_")
    assert payload["token"]["scope"] == "internal_rw"

    created_user_id = payload["tool_user"]["user_id"]
    rw_members = client.get("/api/v1/admin/groups/INTERNAL_READ_WRITE/members").json()["items"]
    api_access_members = client.get("/api/v1/admin/groups/API_ACCESS/members").json()["items"]

    assert any(row["user_id"] == created_user_id and row["is_active"] for row in rw_members)
    assert any(row["user_id"] == created_user_id and row["is_active"] for row in api_access_members)


def test_create_tool_user_without_initial_token(client: TestClient):
    response = _create_tool_user(client, issue_initial_token=False)
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_user"]["user_id"]
    assert "token" not in payload
    assert "plaintext_token" not in payload


def test_duplicate_external_system_key_returns_conflict(client: TestClient):
    duplicate_key = f"atlas-dup-{uuid.uuid4().hex[:8]}"
    first = _create_tool_user(client, external_key=duplicate_key)
    assert first.status_code == 200

    second = _create_tool_user(client, external_key=duplicate_key)
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"].lower()


def test_admin_can_grant_additional_token(client: TestClient):
    create_response = _create_tool_user(client, issue_initial_token=False)
    assert create_response.status_code == 200
    tool_user_id = create_response.json()["tool_user"]["user_id"]

    grant_response = client.post(
        f"/api/v1/admin/tool-api-users/{tool_user_id}/tokens",
        json={
            "token_name": f"atlas-extra-{uuid.uuid4().hex[:6]}",
            "scope": "internal_rw",
            "note": "extra token for integration",
        },
    )
    assert grant_response.status_code == 200
    payload = grant_response.json()
    assert payload["plaintext_token"].startswith("blm_")
    assert payload["token"]["scope"] == "internal_rw"

    listed = client.get("/api/v1/admin/tool-api-users").json()["items"]
    listed_user = next(row for row in listed if row["user_id"] == tool_user_id)
    assert listed_user["token_count"] >= 1


def test_tool_token_stores_atlas_callback_and_tenant_context(client: TestClient):
    create_response = _create_tool_user(
        client,
        initial_token={
            "token_name": f"atlas-context-{uuid.uuid4().hex[:6]}",
            "scope": "internal_rw",
            "atlas_callback_uri": "https://localhost:8915/api/integrations/bloom/v1/events",
            "atlas_tenant_uuid": "11111111-2222-3333-4444-555555555555",
        },
    )
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["token"]["atlas_callback_uri"] == "https://localhost:8915/api/integrations/bloom/v1/events"
    assert payload["token"]["atlas_tenant_uuid"] == "11111111-2222-3333-4444-555555555555"

    tool_user_id = payload["tool_user"]["user_id"]
    grant_response = client.post(
        f"/api/v1/admin/tool-api-users/{tool_user_id}/tokens",
        json={
            "token_name": f"atlas-grant-context-{uuid.uuid4().hex[:6]}",
            "scope": "internal_rw",
            "atlas_callback_uri": "https://localhost:8915/api/integrations/bloom/v1/status-events",
            "atlas_tenant_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
    )
    assert grant_response.status_code == 200
    grant_payload = grant_response.json()
    assert (
        grant_payload["token"]["atlas_callback_uri"]
        == "https://localhost:8915/api/integrations/bloom/v1/status-events"
    )
    assert grant_payload["token"]["atlas_tenant_uuid"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_role_scope_cap_enforced_for_read_only_tool_users(client: TestClient):
    create_response = _create_tool_user(client, role="INTERNAL_READ_ONLY", issue_initial_token=False)
    assert create_response.status_code == 200
    tool_user_id = create_response.json()["tool_user"]["user_id"]

    grant_response = client.post(
        f"/api/v1/admin/tool-api-users/{tool_user_id}/tokens",
        json={
            "token_name": f"invalid-scope-{uuid.uuid4().hex[:5]}",
            "scope": "internal_rw",
        },
    )
    assert grant_response.status_code == 400
    assert "not allowed" in grant_response.json()["detail"].lower()


def test_non_admin_calls_are_forbidden(client: TestClient, non_admin_user_override):
    list_response = client.get("/api/v1/admin/tool-api-users")
    assert list_response.status_code == 403

    create_response = client.post(
        "/api/v1/admin/tool-api-users",
        json={
            "display_name": "No Admin",
            "external_system_key": f"no-admin-{uuid.uuid4().hex[:8]}",
            "role": "INTERNAL_READ_WRITE",
            "issue_initial_token": False,
        },
    )
    assert create_response.status_code == 403


def test_tool_user_token_ttl_defaults_and_overrides(client: TestClient):
    create_response = _create_tool_user(client, issue_initial_token=False)
    assert create_response.status_code == 200
    tool_user_id = create_response.json()["tool_user"]["user_id"]

    default_ttl_response = client.post(
        f"/api/v1/admin/tool-api-users/{tool_user_id}/tokens",
        json={
            "token_name": f"ttl-default-{uuid.uuid4().hex[:6]}",
            "scope": "internal_rw",
        },
    )
    assert default_ttl_response.status_code == 200
    default_payload = default_ttl_response.json()["token"]
    default_created = datetime.fromisoformat(default_payload["created_at"])
    default_expires = datetime.fromisoformat(default_payload["expires_at"])
    default_lifetime = default_expires - default_created
    assert timedelta(days=29, hours=23) <= default_lifetime <= timedelta(days=30, hours=1)

    custom_ttl_response = client.post(
        f"/api/v1/admin/tool-api-users/{tool_user_id}/tokens",
        json={
            "token_name": f"ttl-custom-{uuid.uuid4().hex[:6]}",
            "scope": "internal_rw",
            "expires_in_days": 7,
        },
    )
    assert custom_ttl_response.status_code == 200
    custom_payload = custom_ttl_response.json()["token"]
    custom_created = datetime.fromisoformat(custom_payload["created_at"])
    custom_expires = datetime.fromisoformat(custom_payload["expires_at"])
    custom_lifetime = custom_expires - custom_created
    assert timedelta(days=6, hours=23) <= custom_lifetime <= timedelta(days=7, hours=1)


def test_tool_user_token_revocation_works_with_existing_admin_endpoint(client: TestClient):
    create_response = _create_tool_user(client, issue_initial_token=True)
    assert create_response.status_code == 200
    token_id = create_response.json()["token"]["token_id"]

    revoke_response = client.delete(f"/api/v1/admin/user-tokens/{token_id}")
    assert revoke_response.status_code == 200
    payload = revoke_response.json()
    assert payload["token_id"] == token_id
    assert payload["status"] == "REVOKED"
