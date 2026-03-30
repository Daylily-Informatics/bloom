from __future__ import annotations

from bloom_lims.auth.services.groups import GroupService


def test_resolve_user_roles_and_groups_maps_uppercase_system_group_codes(monkeypatch):
    service = GroupService(db=None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        GroupService,
        "get_group_codes_for_user",
        lambda self, user_id: ["BLOOM-ADMIN"],
    )

    resolution = service.resolve_user_roles_and_groups(
        user_id="johnm@lsmc.com",
        fallback_role=None,
    )

    assert resolution.roles == ["ADMIN"]
    assert resolution.groups == ["BLOOM-ADMIN"]
