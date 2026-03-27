"""Bloom RBAC roles and permissions."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    """Supported Bloom roles."""

    INTERNAL_READ_ONLY = "INTERNAL_READ_ONLY"
    INTERNAL_READ_WRITE = "INTERNAL_READ_WRITE"
    ADMIN = "ADMIN"


class Permission(StrEnum):
    """Supported Bloom permissions."""

    BLOOM_READ = "bloom:read"
    BLOOM_WRITE = "bloom:write"
    BLOOM_ADMIN = "bloom:admin"
    TOKEN_SELF_MANAGE = "token:self_manage"
    TOKEN_ADMIN_MANAGE = "token:admin_manage"


API_ACCESS_GROUP = "API_ACCESS"
ENABLE_ATLAS_API_GROUP = "ENABLE_ATLAS_API"
ENABLE_URSA_API_GROUP = "ENABLE_URSA_API"

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.INTERNAL_READ_ONLY: {
        Permission.BLOOM_READ,
        Permission.TOKEN_SELF_MANAGE,
    },
    Role.INTERNAL_READ_WRITE: {
        Permission.BLOOM_READ,
        Permission.BLOOM_WRITE,
        Permission.TOKEN_SELF_MANAGE,
    },
    Role.ADMIN: set(Permission),
}

ROLE_RANK: dict[Role, int] = {
    Role.INTERNAL_READ_ONLY: 1,
    Role.INTERNAL_READ_WRITE: 2,
    Role.ADMIN: 3,
}

SCOPE_ROLE_CAP: dict[str, Role] = {
    "internal_ro": Role.INTERNAL_READ_ONLY,
    "internal_rw": Role.INTERNAL_READ_WRITE,
    "admin": Role.ADMIN,
}

DEFAULT_ROLE = Role.INTERNAL_READ_WRITE


def _normalize_role(role_value: str | Role | None) -> Role | None:
    if role_value is None:
        return None
    if isinstance(role_value, Role):
        return role_value
    candidate = str(role_value).strip()
    if not candidate:
        return None
    for role in Role:
        if candidate == role.value:
            return role
    # Backward compatibility aliases used by existing Bloom auth.
    alias_map = {
        "user": Role.INTERNAL_READ_WRITE,
        "service": Role.ADMIN,
        "admin": Role.ADMIN,
        "read_only": Role.INTERNAL_READ_ONLY,
        "read-write": Role.INTERNAL_READ_WRITE,
        "read_write": Role.INTERNAL_READ_WRITE,
    }
    return alias_map.get(candidate.lower())


def normalize_roles(
    roles: Iterable[str | Role] | None,
    *,
    fallback: str | Role | None = DEFAULT_ROLE,
) -> list[str]:
    """Normalize role values to canonical role-name strings."""
    normalized: list[str] = []
    seen: set[str] = set()
    values = list(roles or [])
    if not values and fallback is not None:
        values = [fallback]
    for item in values:
        parsed = _normalize_role(item)
        if parsed is None:
            continue
        if parsed.value in seen:
            continue
        normalized.append(parsed.value)
        seen.add(parsed.value)
    if not normalized and fallback is not None:
        parsed = _normalize_role(fallback)
        if parsed is not None:
            normalized = [parsed.value]
    return normalized


def effective_permissions(roles: Iterable[str | Role]) -> set[str]:
    """Return all effective permissions for a user role-set."""
    role_values = normalize_roles(roles, fallback=None)
    perms: set[str] = set()
    for role_value in role_values:
        role_obj = _normalize_role(role_value)
        if role_obj is None:
            continue
        perms.update(permission.value for permission in ROLE_PERMISSIONS.get(role_obj, set()))
    return perms


def has_role(roles: Iterable[str | Role], required_role: Role | str) -> bool:
    """Return True when the required role is present."""
    required = _normalize_role(required_role)
    if required is None:
        return False
    return required.value in normalize_roles(roles, fallback=None)


def has_permission(roles: Iterable[str | Role], permission: Permission | str) -> bool:
    """Return True when any role grants the requested permission."""
    if isinstance(permission, Permission):
        perm = permission.value
    else:
        perm = str(permission).strip()
    if not perm:
        return False
    return perm in effective_permissions(roles)


def can_write(roles: Iterable[str | Role]) -> bool:
    return has_permission(roles, Permission.BLOOM_WRITE)


def is_admin(roles: Iterable[str | Role]) -> bool:
    return has_role(roles, Role.ADMIN)


def constrain_roles_by_scope(roles: Iterable[str | Role], scope: str | None) -> list[str]:
    """Constrain effective roles to a token scope maximum privilege."""
    normalized = normalize_roles(roles, fallback=None)
    if scope is None:
        return normalized

    cap_role = SCOPE_ROLE_CAP.get(str(scope).strip().lower())
    if cap_role is None:
        return []

    cap_rank = ROLE_RANK[cap_role]
    constrained = []
    for role_name in normalized:
        role_obj = _normalize_role(role_name)
        if role_obj is None:
            continue
        if ROLE_RANK[role_obj] <= cap_rank:
            constrained.append(role_obj.value)

    if not constrained:
        constrained = [cap_role.value]
    return normalize_roles(constrained, fallback=cap_role.value)
