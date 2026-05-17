from __future__ import annotations

import pytest

from bloom_lims.auth.services.groups import GroupService, require_canonical_role


def test_resolve_user_roles_and_groups_uses_persisted_role_not_membership(monkeypatch):
    service = object.__new__(GroupService)
    monkeypatch.setattr(
        GroupService,
        "get_group_codes_for_user",
        lambda self, user_id: ["bloom-admin", "API_ACCESS"],
    )

    resolution = service.resolve_user_roles_and_groups(
        user_id="johnm@lsmc.com",
        role_hint="ADMIN",
    )

    assert resolution.roles == ["ADMIN"]
    assert resolution.groups == ["API_ACCESS", "bloom-admin"]


def test_require_canonical_role_rejects_missing_and_old_role_spelling():
    assert require_canonical_role("ADMIN") == "ADMIN"
    with pytest.raises(PermissionError):
        require_canonical_role("admin")
    with pytest.raises(PermissionError):
        require_canonical_role(None)
