from __future__ import annotations

from bloom_lims.auth.services.groups import GroupService, map_legacy_role


def test_resolve_user_roles_and_groups_uses_persisted_role_not_membership(monkeypatch):
    service = GroupService(db=None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        GroupService,
        "get_group_codes_for_user",
        lambda self, user_id: ["BLOOM-ADMIN", "API_ACCESS"],
    )

    resolution = service.resolve_user_roles_and_groups(
        user_id="johnm@lsmc.com",
        fallback_role="ADMIN",
    )

    assert resolution.roles == ["ADMIN"]
    assert resolution.groups == ["API_ACCESS", "BLOOM-ADMIN"]


def test_map_legacy_role_accepts_only_canonical_roles():
    assert map_legacy_role("ADMIN") == "ADMIN"
    assert map_legacy_role("admin") == "READ_WRITE"
    assert map_legacy_role(None) == "READ_WRITE"
