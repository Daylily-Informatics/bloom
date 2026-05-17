"""Group and role resolution services for Bloom auth."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from bloom_lims.auth.rbac import (
    API_ACCESS_GROUP,
    BLOOM_ADMIN_GROUP,
    BLOOM_AUDITOR_GROUP,
    BLOOM_CLINICAL_GROUP,
    BLOOM_READONLY_GROUP,
    BLOOM_READWRITE_GROUP,
    BLOOM_RND_GROUP,
    ENABLE_ATLAS_API_GROUP,
    ENABLE_URSA_API_GROUP,
    Role,
    normalize_roles,
)
from bloom_lims.auth.repositories.tapdb.groups import (
    GroupMembershipRecord,
    GroupRecord,
    TapdbGroupRepository,
)

SYSTEM_GROUP_CODES = [
    BLOOM_READONLY_GROUP,
    BLOOM_READWRITE_GROUP,
    BLOOM_ADMIN_GROUP,
    BLOOM_RND_GROUP,
    BLOOM_CLINICAL_GROUP,
    BLOOM_AUDITOR_GROUP,
    API_ACCESS_GROUP,
    ENABLE_ATLAS_API_GROUP,
    ENABLE_URSA_API_GROUP,
]


ROLE_GROUPS: dict[str, str] = {
    BLOOM_READONLY_GROUP: Role.READ_ONLY.value,
    BLOOM_READWRITE_GROUP: Role.READ_WRITE.value,
    BLOOM_ADMIN_GROUP: Role.ADMIN.value,
}


def require_canonical_role(role_value: str | None) -> str:
    candidate = str(role_value or "").strip()
    if candidate in {role.value for role in Role}:
        return candidate
    raise PermissionError(f"Bloom role must be explicit and canonical: {role_value!r}")


@dataclass(frozen=True)
class GroupResolution:
    roles: list[str]
    groups: list[str]


class GroupService:
    """Convenience wrapper around TapDB group repository."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TapdbGroupRepository(db)

    def ensure_system_groups(self) -> None:
        self.repo.ensure_system_groups(SYSTEM_GROUP_CODES)

    def list_groups(self, include_inactive: bool = False) -> list[GroupRecord]:
        self.ensure_system_groups()
        return self.repo.list_groups(include_inactive=include_inactive)

    def list_group_members(self, group_code: str) -> list[GroupMembershipRecord]:
        self.ensure_system_groups()
        return self.repo.list_group_members(group_code=group_code)

    def add_user_to_group(
        self,
        *,
        group_code: str,
        user_id: str,
        added_by: str | None,
    ) -> GroupMembershipRecord:
        self.ensure_system_groups()
        return self.repo.add_user_to_group(
            group_code=group_code, user_id=user_id, added_by=added_by
        )

    def remove_user_from_group(
        self,
        *,
        group_code: str,
        user_id: str,
        removed_by: str | None,
    ) -> GroupMembershipRecord | None:
        self.ensure_system_groups()
        return self.repo.remove_user_from_group(
            group_code=group_code, user_id=user_id, removed_by=removed_by
        )

    def get_group_codes_for_user(self, user_id: str | None) -> list[str]:
        self.ensure_system_groups()
        if not user_id:
            return []
        return self.repo.get_user_group_codes(user_id=user_id)

    def resolve_user_roles_and_groups(
        self,
        *,
        user_id: str | None,
        role_hint: str | None,
    ) -> GroupResolution:
        groups = self.get_group_codes_for_user(user_id)
        roles = [ROLE_GROUPS[group] for group in groups if group in ROLE_GROUPS]
        if role_hint:
            roles.append(require_canonical_role(role_hint))
        roles = normalize_roles(roles)
        if not roles:
            raise PermissionError(
                f"Bloom user {user_id!r} has no explicit Bloom role or role group"
            )
        return GroupResolution(roles=roles, groups=sorted(groups))
