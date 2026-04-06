"""Focused tests for Bloom RBAC/token auth additions."""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from time import time_ns
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth, require_write
from bloom_lims.domain.external_specimens import ExternalSpecimenService
from bloom_lims.schemas.external_specimens import AtlasReferences

# Ensure auth bypass is active for API-client tests.
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def _create_token(client: TestClient) -> str:
    token_name = f"pytest-token-{time_ns()}"
    create_response = client.post(
        "/api/v1/user-tokens",
        json={
            "token_name": token_name,
            "scope": "internal_ro",
            "expires_in_days": 30,
        },
    )
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["token"]["token_name"] == token_name
    assert payload["plaintext_token"].startswith("blm_")
    return payload["token"]["token_id"]


def test_require_write_blocks_read_only_user():
    user = APIUser(
        email="ro@example.com",
        user_id="ro-user-1",
        roles=["READ_ONLY"],
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_write(user))
    assert exc.value.status_code == 403
    assert "Write permission required" in exc.value.detail


def test_require_external_token_auth_blocks_non_token_user():
    user = APIUser(
        email="session@example.com",
        user_id="session-user-1",
        roles=["READ_WRITE"],
        auth_source="session",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_external_token_auth(user))
    assert exc.value.status_code == 401


def test_auth_me_includes_rbac_fields(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    payload = response.json()
    assert "roles" in payload
    assert "groups" in payload
    assert "permissions" in payload
    assert "auth_source" in payload


def test_api_root_lists_new_auth_endpoints(client):
    response = client.get("/api/v1/")
    assert response.status_code == 200
    endpoints = response.json()["endpoints"]
    assert "user_tokens" in endpoints
    assert "admin_auth" in endpoints


def test_external_specimen_endpoints_require_external_token_auth(client):
    response = client.get("/api/v1/external/specimens/by-reference?order_number=ORD-1")
    assert response.status_code == 401
    assert "requires Bloom API bearer token" in response.json()["detail"]


def test_external_specimen_lookup_does_not_require_atlas_client(monkeypatch):
    def _unexpected_atlas_service():
        raise AssertionError("AtlasService should not be constructed for lookup-only queries")

    monkeypatch.setattr(
        "bloom_lims.domain.external_specimens.AtlasService",
        _unexpected_atlas_service,
    )

    service = object.__new__(ExternalSpecimenService)
    service._atlas = None
    service.bdb = SimpleNamespace()
    service.bobj = SimpleNamespace()
    service._find_parent_uids_for_reference = lambda **_kwargs: set()

    result = ExternalSpecimenService.find_by_references(
        service,
        AtlasReferences(atlas_tenant_id="tenant-1"),
    )

    assert result == []
    assert service._atlas is None


def test_user_tokens_endpoints_create_list_usage_revoke(client):
    token_id = _create_token(client)

    list_response = client.get("/api/v1/user-tokens")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert any(item["token_id"] == token_id for item in list_payload["items"])

    usage_response = client.get(f"/api/v1/user-tokens/{token_id}/usage")
    assert usage_response.status_code == 200
    usage_payload = usage_response.json()
    assert "items" in usage_payload
    assert "total" in usage_payload

    revoke_response = client.delete(f"/api/v1/user-tokens/{token_id}")
    assert revoke_response.status_code == 200
    revoked = revoke_response.json()
    assert revoked["token"]["status"] == "REVOKED"


def test_user_tokens_default_expiry_is_48_hours(client):
    response = client.post(
        "/api/v1/user-tokens",
        json={
            "token_name": f"pytest-default-expiry-{time_ns()}",
            "scope": "internal_ro",
        },
    )
    assert response.status_code == 200
    payload = response.json()

    created_at = datetime.fromisoformat(payload["token"]["created_at"])
    expires_at = datetime.fromisoformat(payload["token"]["expires_at"])
    lifetime = expires_at - created_at
    assert timedelta(hours=47, minutes=55) <= lifetime <= timedelta(hours=48, minutes=5)


def test_admin_group_membership_endpoints_list_add_get_delete(client):
    list_groups_response = client.get("/api/v1/admin/groups")
    assert list_groups_response.status_code == 200
    groups_payload = list_groups_response.json()
    assert groups_payload["total"] >= 1

    target_group = "API_ACCESS"
    member_user_id = f"member-user-{time_ns()}"

    add_response = client.post(
        f"/api/v1/admin/groups/{target_group}/members",
        json={"user_id": member_user_id},
    )
    assert add_response.status_code == 200
    add_payload = add_response.json()
    assert add_payload["group_code"] == target_group
    assert add_payload["user_id"] == member_user_id

    list_members_response = client.get(f"/api/v1/admin/groups/{target_group}/members")
    assert list_members_response.status_code == 200
    members_payload = list_members_response.json()
    assert any(item["user_id"] == member_user_id for item in members_payload["items"])

    remove_response = client.delete(f"/api/v1/admin/groups/{target_group}/members/{member_user_id}")
    assert remove_response.status_code == 200
    remove_payload = remove_response.json()
    assert remove_payload["group_code"] == target_group
    assert remove_payload["user_id"] == member_user_id


def test_admin_user_token_endpoints_list_usage_delete(client):
    token_id = _create_token(client)

    list_response = client.get("/api/v1/admin/user-tokens")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert any(item["token_id"] == token_id for item in list_payload["items"])

    usage_response = client.get(f"/api/v1/admin/user-tokens/{token_id}/usage")
    assert usage_response.status_code == 200
    usage_payload = usage_response.json()
    assert "items" in usage_payload
    assert "total" in usage_payload

    revoke_response = client.delete(f"/api/v1/admin/user-tokens/{token_id}")
    assert revoke_response.status_code == 200
    revoke_payload = revoke_response.json()
    assert revoke_payload["token_id"] == token_id
    assert revoke_payload["status"] == "REVOKED"
