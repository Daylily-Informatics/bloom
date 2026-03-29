"""Focused tests for external specimen authorization guards."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from bloom_lims.api.v1.dependencies import APIUser, require_external_atlas_api_enabled
from bloom_lims.auth.rbac import ENABLE_ATLAS_API_GROUP


def _token_user(groups: list[str]) -> APIUser:
    return APIUser(
        email="token-user@example.com",
        user_id="token-user",
        roles=["READ_WRITE"],
        groups=groups,
        auth_source="token",
    )


def test_require_external_atlas_api_enabled_rejects_missing_group():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_external_atlas_api_enabled(_token_user(groups=[])))
    assert exc.value.status_code == 403
    assert "ENABLE_ATLAS_API" in str(exc.value.detail)


def test_require_external_atlas_api_enabled_allows_group_member():
    user = _token_user(groups=[ENABLE_ATLAS_API_GROUP])
    resolved = asyncio.run(require_external_atlas_api_enabled(user))
    assert resolved.user_id == "token-user"
