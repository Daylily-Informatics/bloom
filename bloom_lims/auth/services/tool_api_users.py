"""Service layer for API-only tool user management."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from bloom_lims.auth.rbac import API_ACCESS_GROUP, Role
from bloom_lims.auth.repositories.tapdb.tool_api_users import (
    TapdbToolAPIUserRepository,
    ToolAPIUserRecord,
    normalize_external_system_key,
)
from bloom_lims.auth.services.groups import GroupService
from bloom_lims.auth.services.user_api_tokens import (
    TOKEN_STATUS_ACTIVE,
    TokenCreateInput,
    TokenCreateResult,
    UserAPITokenService,
)

_ALLOWED_TOOL_USER_ROLES = {
    Role.INTERNAL_READ_ONLY.value,
    Role.INTERNAL_READ_WRITE.value,
}


@dataclass(frozen=True)
class ToolAPIUserCreateInput:
    display_name: str
    external_system_key: str
    description: str | None = None
    role: str = Role.INTERNAL_READ_WRITE.value
    metadata: dict[str, Any] | None = None
    issue_initial_token: bool = True
    initial_token_name: str | None = None
    initial_token_scope: str | None = None
    initial_token_expires_in_days: int | None = None
    initial_token_note: str | None = None
    initial_token_atlas_callback_uri: str | None = None
    initial_token_atlas_tenant_uuid: str | None = None


@dataclass(frozen=True)
class ToolAPIUserTokenGrantInput:
    token_name: str
    scope: str
    expires_in_days: int | None = None
    note: str | None = None
    atlas_callback_uri: str | None = None
    atlas_tenant_uuid: str | None = None


@dataclass(frozen=True)
class ToolAPIUserSummary:
    tool_user: ToolAPIUserRecord
    token_count: int
    active_token_count: int
    last_token_issued_at: datetime | None


@dataclass(frozen=True)
class ToolAPIUserCreateResult:
    tool_user: ToolAPIUserRecord
    token_result: TokenCreateResult | None


class ToolAPIUserService:
    """Create/list API-only tool users and grant scoped API tokens."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TapdbToolAPIUserRepository(db)
        self.groups = GroupService(db)
        self.tokens = UserAPITokenService(db)

    @staticmethod
    def normalize_role(role_value: str | None) -> str:
        candidate = str(role_value or "").strip()
        if not candidate:
            candidate = Role.INTERNAL_READ_WRITE.value
        if candidate not in _ALLOWED_TOOL_USER_ROLES:
            raise ValueError("Tool user role must be INTERNAL_READ_ONLY or INTERNAL_READ_WRITE")
        return candidate

    @staticmethod
    def default_scope_for_role(role: str) -> str:
        if role == Role.INTERNAL_READ_ONLY.value:
            return "internal_ro"
        return "internal_rw"

    @staticmethod
    def allowed_scopes_for_role(role: str) -> set[str]:
        if role == Role.INTERNAL_READ_ONLY.value:
            return {"internal_ro"}
        if role == Role.INTERNAL_READ_WRITE.value:
            return {"internal_ro", "internal_rw"}
        return set()

    @staticmethod
    def resolve_expires_in_days(
        *,
        requested_days: int | None,
        default_days: int,
        max_days: int,
    ) -> int:
        if max_days < 1:
            raise ValueError("Configured auth.tool_api_max_token_days must be >= 1")
        fallback = max(1, min(int(default_days), max_days))
        if requested_days is None:
            return fallback
        parsed = int(requested_days)
        if parsed < 1:
            raise ValueError("expires_in_days must be >= 1")
        if parsed > max_days:
            raise ValueError(f"expires_in_days cannot exceed {max_days}")
        return parsed

    def create_tool_user(
        self,
        *,
        actor_user_id: uuid.UUID,
        actor_roles: list[str],
        actor_groups: list[str],
        payload: ToolAPIUserCreateInput,
        default_token_days: int,
        max_token_days: int,
    ) -> ToolAPIUserCreateResult:
        role = self.normalize_role(payload.role)
        tool_user = self.repo.create_tool_user(
            display_name=payload.display_name,
            external_system_key=normalize_external_system_key(payload.external_system_key),
            description=payload.description,
            role=role,
            created_by=actor_user_id,
            metadata=payload.metadata,
        )

        self.groups.ensure_system_groups()
        self.groups.add_user_to_group(
            group_code=role,
            user_id=tool_user.id,
            added_by=actor_user_id,
        )
        self.groups.add_user_to_group(
            group_code=API_ACCESS_GROUP,
            user_id=tool_user.id,
            added_by=actor_user_id,
        )

        token_result: TokenCreateResult | None = None
        if payload.issue_initial_token:
            token_name = str(payload.initial_token_name or "").strip()
            if not token_name:
                token_name = f"{tool_user.external_system_key}-initial"
            scope = str(payload.initial_token_scope or self.default_scope_for_role(role)).strip().lower()
            expires_in_days = self.resolve_expires_in_days(
                requested_days=payload.initial_token_expires_in_days,
                default_days=default_token_days,
                max_days=max_token_days,
            )
            token_result = self.grant_token(
                tool_user_id=tool_user.id,
                actor_user_id=actor_user_id,
                actor_roles=actor_roles,
                actor_groups=actor_groups,
                payload=ToolAPIUserTokenGrantInput(
                    token_name=token_name,
                    scope=scope,
                    expires_in_days=expires_in_days,
                    note=payload.initial_token_note,
                    atlas_callback_uri=payload.initial_token_atlas_callback_uri,
                    atlas_tenant_uuid=payload.initial_token_atlas_tenant_uuid,
                ),
                default_token_days=default_token_days,
                max_token_days=max_token_days,
            )

        return ToolAPIUserCreateResult(tool_user=tool_user, token_result=token_result)

    def grant_token(
        self,
        *,
        tool_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_roles: list[str],
        actor_groups: list[str],
        payload: ToolAPIUserTokenGrantInput,
        default_token_days: int,
        max_token_days: int,
    ) -> TokenCreateResult:
        tool_user = self.repo.get_tool_user(tool_user_id)
        if tool_user is None:
            raise LookupError("Tool API user not found")
        if not tool_user.is_active:
            raise ValueError("Tool API user is inactive")

        token_name = str(payload.token_name or "").strip()
        if not token_name:
            raise ValueError("token_name is required")

        scope = str(payload.scope or "").strip().lower()
        allowed_scopes = self.allowed_scopes_for_role(tool_user.role)
        if scope not in allowed_scopes:
            raise ValueError(
                f"Scope '{scope}' is not allowed for tool user role {tool_user.role}"
            )

        expires_in_days = self.resolve_expires_in_days(
            requested_days=payload.expires_in_days,
            default_days=default_token_days,
            max_days=max_token_days,
        )

        return self.tokens.create_token(
            owner_user_id=tool_user.id,
            actor_user_id=actor_user_id,
            actor_roles=actor_roles,
            actor_groups=actor_groups,
            payload=TokenCreateInput(
                token_name=token_name,
                scope=scope,
                expires_in_days=expires_in_days,
                note=payload.note,
                atlas_callback_uri=payload.atlas_callback_uri,
                atlas_tenant_uuid=payload.atlas_tenant_uuid,
            ),
        )

    def list_tool_users_with_token_summary(
        self,
        *,
        include_inactive: bool = True,
    ) -> list[ToolAPIUserSummary]:
        users = self.repo.list_tool_users(include_inactive=include_inactive)
        now = datetime.now(UTC)
        rows: list[ToolAPIUserSummary] = []
        for user in users:
            token_rows = self.tokens.list_user_tokens(user_id=user.id)
            token_count = len(token_rows)
            active_token_count = sum(
                1
                for token, revision in token_rows
                if revision.status == TOKEN_STATUS_ACTIVE and revision.expires_at >= now
            )
            last_token_issued_at = None
            if token_rows:
                created_values = [token.created_at for token, _ in token_rows if token.created_at is not None]
                last_token_issued_at = max(created_values) if created_values else None

            rows.append(
                ToolAPIUserSummary(
                    tool_user=user,
                    token_count=token_count,
                    active_token_count=active_token_count,
                    last_token_issued_at=last_token_issued_at,
                )
            )
        return rows

    def get_tool_user(self, *, tool_user_id: uuid.UUID) -> ToolAPIUserRecord | None:
        return self.repo.get_tool_user(tool_user_id)
