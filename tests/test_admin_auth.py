"""Focused tests for admin group and token management routes."""

from __future__ import annotations

import os
import sys
from typing import Any
from time import time_ns

from fastapi.testclient import TestClient


os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402



def _client() -> TestClient:
    return TestClient(app)


def _props(instance) -> dict[str, Any]:
    payload = instance.json_addl or {}
    if not isinstance(payload, dict):
        return {}
    properties = payload.get("properties")
    return properties if isinstance(properties, dict) else {}


def _matching_instances(session, subtype: str, key: str, value: str):
    from bloom_lims.db import generic_instance

    rows = (
        session.query(generic_instance)
        .filter(
            generic_instance.subtype == subtype,
            generic_instance.is_deleted.is_(False),
        )
        .all()
    )
    return [row for row in rows if str(_props(row).get(key)) == value]


def _revision_children(session, parent_uid: int):
    from bloom_lims.db import generic_instance_lineage

    return (
        session.query(generic_instance_lineage)
        .filter(
            generic_instance_lineage.parent_instance_uid == parent_uid,
            generic_instance_lineage.relationship_type == "revision",
        )
        .all()
    )


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


def test_token_updates_mutate_single_canonical_object_without_revision_children():
    client = _client()
    owner_user_id = f"canonical-token-owner-{time_ns()}"

    response = client.post(
        "/api/v1/admin/user-tokens/issue",
        json={
            "user_id": owner_user_id,
            "token_name": f"canonical-token-{time_ns()}",
            "scope": "internal_ro",
            "expires_in_days": 30,
        },
    )
    assert response.status_code == 200
    token_id = response.json()["token"]["token_id"]

    from bloom_lims.auth.services.user_api_tokens import UserAPITokenService
    from bloom_lims.db import BLOOMdb3

    bdb = BLOOMdb3(app_username="pytest-token-canonical")
    try:
        service = UserAPITokenService(bdb.session)
        token, state = service.get_token(token_id=token_id)
        token_euid = token.euid
        assert state.euid == token_euid
        assert state.object_version == 1

        service.mark_token_used(token_id=token_id)
        token_after_use, state_after_use = service.get_token(token_id=token_id)
        assert token_after_use.euid == token_euid
        assert state_after_use.euid == token_euid
        assert state_after_use.last_used_at is not None
        assert state_after_use.object_version == 2

        token_after_revoke, state_after_revoke = service.revoke_token(
            token_id=token_id,
            actor_user_id="dev-bypass-admin",
            actor_roles=["ADMIN"],
        )
        assert token_after_revoke.euid == token_euid
        assert state_after_revoke.euid == token_euid
        assert state_after_revoke.status == "REVOKED"
        assert state_after_revoke.object_version == 3

        token_instances = _matching_instances(
            bdb.session, "user-api-token", "id", token_id
        )
        assert [row.euid for row in token_instances] == [token_euid]
        assert _matching_instances(
            bdb.session, "user-api-token-revision", "token_id", token_id
        ) == []
        assert _revision_children(bdb.session, token_instances[0].uid) == []
    finally:
        bdb.close()


def test_group_update_mutates_single_canonical_object_without_revision_children():
    client = _client()
    group_code = f"TEST_AUTH_GROUP_{time_ns()}"

    from bloom_lims.auth.repositories.tapdb.groups import TapdbGroupRepository
    from bloom_lims.db import BLOOMdb3

    bdb = BLOOMdb3(app_username="pytest-group-canonical")
    try:
        repo = TapdbGroupRepository(bdb.session)
        repo.ensure_system_groups([group_code])
        before = repo.get_group_by_code(group_code)
        assert before is not None
        group_euid = before.euid
        assert before.object_version == 1

        response = client.patch(
            f"/api/v1/admin/groups/{group_code}",
            json={
                "name": "Canonical Test Group",
                "description": "Updated without revision lineage",
                "is_active": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["object_version"] == 2

        bdb.session.expire_all()
        updated = repo.get_group_by_code(group_code)
        assert updated is not None
        assert updated.euid == group_euid
        assert updated.name == "Canonical Test Group"
        assert updated.description == "Updated without revision lineage"
        assert updated.object_version == 2

        group_instances = _matching_instances(
            bdb.session, "user-group", "group_code", group_code
        )
        assert [row.euid for row in group_instances] == [group_euid]
        assert _matching_instances(
            bdb.session, "user-group-revision", "group_id", updated.id
        ) == []
        assert _revision_children(bdb.session, group_instances[0].uid) == []
    finally:
        bdb.close()
