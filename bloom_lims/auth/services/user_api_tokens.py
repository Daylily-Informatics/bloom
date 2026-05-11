"""User API token service for Bloom external integrations."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from bloom_lims.auth.rbac import (
    API_ACCESS_GROUP,
    Role,
    constrain_roles_by_scope,
    is_admin,
    normalize_roles,
)
from bloom_lims.auth.repositories.tapdb.user_api_tokens import (
    TapdbUserAPITokenRepository,
    UserTokenRecord,
    UserTokenStateRecord,
    UserTokenUsageRecord,
)
from bloom_lims.auth.repositories.tapdb.users import resolve_user_record
from bloom_lims.auth.services.groups import GroupService

TOKEN_PREFIX = "blm_"
TOKEN_STATUS_ACTIVE = "ACTIVE"
TOKEN_STATUS_EXPIRED = "EXPIRED"
TOKEN_STATUS_REVOKED = "REVOKED"


@dataclass(frozen=True)
class TokenCreateInput:
    token_name: str
    scope: str
    expires_in_days: int = 2
    note: str | None = None


@dataclass(frozen=True)
class TokenCreateResult:
    token: UserTokenRecord
    state: UserTokenStateRecord
    plaintext_token: str


@dataclass(frozen=True)
class TokenValidationResult:
    is_valid: bool
    error: str | None = None
    token: UserTokenRecord | None = None
    state: UserTokenStateRecord | None = None


class UserAPITokenService:
    """Create/validate/revoke personal API tokens."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TapdbUserAPITokenRepository(db)
        self.groups = GroupService(db)

    @staticmethod
    def generate_plaintext_token() -> str:
        return TOKEN_PREFIX + secrets.token_hex(32)

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def display_prefix(token: str) -> str:
        return f"{token[:12]}..."

    @staticmethod
    def allowed_scopes_for_roles(actor_roles: list[str]) -> set[str]:
        roles = normalize_roles(actor_roles, fallback=Role.READ_WRITE.value)
        if is_admin(roles):
            return {"internal_ro", "internal_rw", "admin"}
        if Role.READ_WRITE.value in roles:
            return {"internal_ro", "internal_rw"}
        if Role.READ_ONLY.value in roles:
            return {"internal_ro"}
        return set()

    def create_token(
        self,
        *,
        owner_user_id: str,
        actor_user_id: str,
        actor_roles: list[str],
        actor_groups: list[str],
        payload: TokenCreateInput,
    ) -> TokenCreateResult:
        self.groups.ensure_system_groups()
        normalized_roles = normalize_roles(actor_roles, fallback=Role.READ_WRITE.value)
        group_set = {group.upper() for group in actor_groups}
        actor_is_admin = is_admin(normalized_roles)
        if not actor_is_admin and API_ACCESS_GROUP not in group_set:
            raise PermissionError("User is not in API_ACCESS group")

        scope = str(payload.scope or "internal_ro").strip().lower()
        allowed_scopes = self.allowed_scopes_for_roles(normalized_roles)
        if scope not in allowed_scopes:
            raise PermissionError(f"Scope '{scope}' is not allowed for actor role set")

        expires_in_days = max(1, min(int(payload.expires_in_days or 2), 3650))
        plaintext = self.generate_plaintext_token()
        token_hash = self.hash_token(plaintext)
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=expires_in_days)

        token, state = self.repo.create_token(
            user_id=owner_user_id,
            token_name=payload.token_name.strip(),
            token_prefix=self.display_prefix(plaintext),
            scope=scope,
            token_hash=token_hash,
            expires_at=expires_at,
            created_by=actor_user_id,
            note=payload.note,
        )
        return TokenCreateResult(token=token, state=state, plaintext_token=plaintext)

    def list_user_tokens(
        self, *, user_id: str
    ) -> list[tuple[UserTokenRecord, UserTokenStateRecord]]:
        rows: list[tuple[UserTokenRecord, UserTokenStateRecord]] = []
        for token in self.repo.list_tokens(user_id=user_id):
            state = self.repo.get_current_state(token.id)
            if state is None:
                continue
            rows.append((token, state))
        return rows

    def list_all_tokens(self) -> list[tuple[UserTokenRecord, UserTokenStateRecord]]:
        rows: list[tuple[UserTokenRecord, UserTokenStateRecord]] = []
        for token in self.repo.list_tokens(user_id=None):
            state = self.repo.get_current_state(token.id)
            if state is None:
                continue
            rows.append((token, state))
        return rows

    def get_token(
        self, *, token_id: str
    ) -> tuple[UserTokenRecord, UserTokenStateRecord] | None:
        return self.repo.get_token(token_id)

    def revoke_token(
        self,
        *,
        token_id: str,
        actor_user_id: str,
        actor_roles: list[str],
    ) -> tuple[UserTokenRecord, UserTokenStateRecord] | None:
        current = self.repo.get_token(token_id)
        if current is None:
            return None
        token, state = current
        roles = normalize_roles(actor_roles, fallback=Role.READ_WRITE.value)
        if token.user_id != actor_user_id and not is_admin(roles):
            raise PermissionError("Cannot revoke another user's token")

        if state.status == TOKEN_STATUS_REVOKED:
            return token, state

        new_state = self.repo.update_token_state(
            token_id=token.id,
            status=TOKEN_STATUS_REVOKED,
            revoked_at=datetime.now(UTC),
            revoked_by=actor_user_id,
            revocation_reason="revoked_by_user",
            updated_by=actor_user_id,
            note="Token revoked",
        )
        return token, new_state

    def validate_token(self, plaintext_token: str) -> TokenValidationResult:
        token_value = str(plaintext_token or "").strip()
        if not token_value.startswith(TOKEN_PREFIX):
            return TokenValidationResult(is_valid=False, error="Invalid token prefix")

        token_hash = self.hash_token(token_value)
        state = self.repo.find_current_state_by_hash(token_hash)
        if state is None:
            return TokenValidationResult(is_valid=False, error="Token not found")

        if not hmac.compare_digest(state.token_hash, token_hash):
            return TokenValidationResult(is_valid=False, error="Token mismatch")

        if state.status == TOKEN_STATUS_REVOKED:
            return TokenValidationResult(is_valid=False, error="Token is revoked")

        now = datetime.now(UTC)
        if state.expires_at < now:
            return TokenValidationResult(is_valid=False, error="Token is expired")

        token_result = self.repo.get_token(state.token_id)
        if token_result is None:
            return TokenValidationResult(is_valid=False, error="Token owner not found")
        token, current_state = token_result
        if current_state.status == TOKEN_STATUS_REVOKED:
            return TokenValidationResult(is_valid=False, error="Token is revoked")
        if current_state.expires_at < now:
            return TokenValidationResult(is_valid=False, error="Token is expired")

        return TokenValidationResult(
            is_valid=True,
            token=token,
            state=current_state,
        )

    def mark_token_used(self, *, token_id: str) -> None:
        token_result = self.repo.get_token(token_id)
        if token_result is None:
            return
        token, _state = token_result
        self.repo.update_token_state(
            token_id=token.id,
            last_used_at=datetime.now(UTC),
            updated_by=None,
            note="Last used timestamp updated",
        )

    def log_usage(
        self,
        *,
        token_id: str,
        user_id: str,
        endpoint: str,
        http_method: str,
        response_status: int,
        ip_address: str | None,
        user_agent: str | None,
        request_metadata: dict[str, Any] | None,
    ) -> None:
        self.repo.log_usage(
            token_id=token_id,
            user_id=user_id,
            endpoint=endpoint,
            http_method=http_method,
            response_status=response_status,
            ip_address=ip_address,
            user_agent=user_agent,
            request_metadata=request_metadata,
        )

    def usage_for_token(
        self,
        *,
        token_id: str,
        actor_user_id: str,
        actor_roles: list[str],
        limit: int = 100,
    ) -> list[UserTokenUsageRecord]:
        token_result = self.repo.get_token(token_id)
        if token_result is None:
            return []
        token, _ = token_result
        roles = normalize_roles(actor_roles, fallback=Role.READ_WRITE.value)
        if token.user_id != actor_user_id and not is_admin(roles):
            raise PermissionError("Cannot view usage for another user's token")
        return self.repo.get_usage_logs(
            token_id=token_id, limit=max(1, min(limit, 1000))
        )

    def constrained_roles_for_token_owner(
        self,
        *,
        token: UserTokenRecord,
    ) -> tuple[list[str], list[str]]:
        owner_record = resolve_user_record(
            self.db, token.user_id, include_inactive=True
        )
        fallback_role = (
            owner_record.role
            if owner_record and owner_record.role
            else Role.READ_ONLY.value
        )
        owner = self.groups.resolve_user_roles_and_groups(
            user_id=token.user_id,
            fallback_role=fallback_role,
        )
        return constrain_roles_by_scope(owner.roles, token.scope), owner.groups
