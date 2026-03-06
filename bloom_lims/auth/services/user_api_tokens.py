"""User API token service for Bloom external integrations."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
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
    UserTokenRevisionRecord,
    UserTokenUsageRecord,
)
from bloom_lims.auth.services.groups import GroupService
from bloom_lims.security.transport import require_https_url


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
    atlas_callback_uri: str | None = None
    atlas_tenant_uuid: str | None = None


@dataclass(frozen=True)
class TokenCreateResult:
    token: UserTokenRecord
    revision: UserTokenRevisionRecord
    plaintext_token: str


@dataclass(frozen=True)
class TokenValidationResult:
    is_valid: bool
    error: str | None = None
    token: UserTokenRecord | None = None
    revision: UserTokenRevisionRecord | None = None


class UserAPITokenService:
    """Create/validate/revoke personal API tokens."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TapdbUserAPITokenRepository(db)
        self.groups = GroupService(db)

    @staticmethod
    def _normalize_atlas_tenant_uuid(value: str | None) -> str | None:
        candidate = str(value or "").strip()
        if not candidate:
            return None
        try:
            return str(uuid.UUID(candidate))
        except ValueError as exc:
            raise ValueError("atlas_tenant_uuid must be a valid UUID") from exc

    @staticmethod
    def _normalize_atlas_callback_uri(value: str | None) -> str | None:
        candidate = str(value or "").strip()
        if not candidate:
            return None
        return require_https_url(candidate, context_label="atlas_callback_uri")

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
        roles = normalize_roles(actor_roles, fallback=Role.INTERNAL_READ_WRITE.value)
        if is_admin(roles):
            return {"internal_ro", "internal_rw", "admin"}
        if Role.INTERNAL_READ_WRITE.value in roles:
            return {"internal_ro", "internal_rw"}
        if Role.INTERNAL_READ_ONLY.value in roles:
            return {"internal_ro"}
        return set()

    def create_token(
        self,
        *,
        owner_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_roles: list[str],
        actor_groups: list[str],
        payload: TokenCreateInput,
    ) -> TokenCreateResult:
        self.groups.ensure_system_groups()
        normalized_roles = normalize_roles(actor_roles, fallback=Role.INTERNAL_READ_WRITE.value)
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
        atlas_callback_uri = self._normalize_atlas_callback_uri(payload.atlas_callback_uri)
        atlas_tenant_uuid = self._normalize_atlas_tenant_uuid(payload.atlas_tenant_uuid)

        token, revision = self.repo.create_token(
            user_id=owner_user_id,
            token_name=payload.token_name.strip(),
            token_prefix=self.display_prefix(plaintext),
            scope=scope,
            atlas_callback_uri=atlas_callback_uri,
            atlas_tenant_uuid=atlas_tenant_uuid,
            token_hash=token_hash,
            expires_at=expires_at,
            created_by=actor_user_id,
            note=payload.note,
        )
        return TokenCreateResult(token=token, revision=revision, plaintext_token=plaintext)

    def list_user_tokens(self, *, user_id: uuid.UUID) -> list[tuple[UserTokenRecord, UserTokenRevisionRecord]]:
        rows: list[tuple[UserTokenRecord, UserTokenRevisionRecord]] = []
        for token in self.repo.list_tokens(user_id=user_id):
            revision = self.repo.get_latest_revision(token.id)
            if revision is None:
                continue
            rows.append((token, revision))
        return rows

    def list_all_tokens(self) -> list[tuple[UserTokenRecord, UserTokenRevisionRecord]]:
        rows: list[tuple[UserTokenRecord, UserTokenRevisionRecord]] = []
        for token in self.repo.list_tokens(user_id=None):
            revision = self.repo.get_latest_revision(token.id)
            if revision is None:
                continue
            rows.append((token, revision))
        return rows

    def get_token(self, *, token_id: uuid.UUID) -> tuple[UserTokenRecord, UserTokenRevisionRecord] | None:
        return self.repo.get_token(token_id)

    def revoke_token(
        self,
        *,
        token_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_roles: list[str],
    ) -> tuple[UserTokenRecord, UserTokenRevisionRecord] | None:
        current = self.repo.get_token(token_id)
        if current is None:
            return None
        token, revision = current
        roles = normalize_roles(actor_roles, fallback=Role.INTERNAL_READ_WRITE.value)
        if token.user_id != actor_user_id and not is_admin(roles):
            raise PermissionError("Cannot revoke another user's token")

        if revision.status == TOKEN_STATUS_REVOKED:
            return token, revision

        new_revision = self.repo.create_revision(
            token_id=token.id,
            revision_no=revision.revision_no + 1,
            token_hash=revision.token_hash,
            status=TOKEN_STATUS_REVOKED,
            expires_at=revision.expires_at,
            last_used_at=revision.last_used_at,
            revoked_at=datetime.now(UTC),
            revoked_by=actor_user_id,
            revocation_reason="revoked_by_user",
            created_by=actor_user_id,
            note="Token revoked",
        )
        return token, new_revision

    def validate_token(self, plaintext_token: str) -> TokenValidationResult:
        token_value = str(plaintext_token or "").strip()
        if not token_value.startswith(TOKEN_PREFIX):
            return TokenValidationResult(is_valid=False, error="Invalid token prefix")

        token_hash = self.hash_token(token_value)
        revision = self.repo.find_latest_revision_by_hash(token_hash)
        if revision is None:
            return TokenValidationResult(is_valid=False, error="Token not found")

        if not hmac.compare_digest(revision.token_hash, token_hash):
            return TokenValidationResult(is_valid=False, error="Token mismatch")

        if revision.status == TOKEN_STATUS_REVOKED:
            return TokenValidationResult(is_valid=False, error="Token is revoked")

        now = datetime.now(UTC)
        if revision.expires_at < now:
            return TokenValidationResult(is_valid=False, error="Token is expired")

        token_result = self.repo.get_token(revision.token_id)
        if token_result is None:
            return TokenValidationResult(is_valid=False, error="Token owner not found")
        token, latest_revision = token_result
        if latest_revision.status == TOKEN_STATUS_REVOKED:
            return TokenValidationResult(is_valid=False, error="Token is revoked")
        if latest_revision.expires_at < now:
            return TokenValidationResult(is_valid=False, error="Token is expired")

        return TokenValidationResult(
            is_valid=True,
            token=token,
            revision=latest_revision,
        )

    def mark_token_used(self, *, token_id: uuid.UUID) -> None:
        token_result = self.repo.get_token(token_id)
        if token_result is None:
            return
        token, revision = token_result
        self.repo.create_revision(
            token_id=token.id,
            revision_no=revision.revision_no + 1,
            token_hash=revision.token_hash,
            status=revision.status,
            expires_at=revision.expires_at,
            last_used_at=datetime.now(UTC),
            revoked_at=revision.revoked_at,
            revoked_by=revision.revoked_by,
            revocation_reason=revision.revocation_reason,
            created_by=None,
            note="Last used timestamp updated",
        )

    def log_usage(
        self,
        *,
        token_id: uuid.UUID,
        user_id: uuid.UUID,
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
        token_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_roles: list[str],
        limit: int = 100,
    ) -> list[UserTokenUsageRecord]:
        token_result = self.repo.get_token(token_id)
        if token_result is None:
            return []
        token, _ = token_result
        roles = normalize_roles(actor_roles, fallback=Role.INTERNAL_READ_WRITE.value)
        if token.user_id != actor_user_id and not is_admin(roles):
            raise PermissionError("Cannot view usage for another user's token")
        return self.repo.get_usage_logs(token_id=token_id, limit=max(1, min(limit, 1000)))

    def constrained_roles_for_token_owner(
        self,
        *,
        token: UserTokenRecord,
    ) -> tuple[list[str], list[str]]:
        owner = self.groups.resolve_user_roles_and_groups(
            user_id=token.user_id,
            fallback_role=Role.INTERNAL_READ_ONLY.value,
        )
        return constrain_roles_by_scope(owner.roles, token.scope), owner.groups
