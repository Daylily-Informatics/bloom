"""Authentication/authorization dependencies for Bloom API v1."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import Depends, HTTPException, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bloom_lims.auth.rbac import (
    API_ACCESS_GROUP,
    Permission,
    Role,
    effective_permissions,
    has_permission,
    normalize_roles,
)
from bloom_lims.auth.services.groups import GroupService, map_legacy_role
from bloom_lims.auth.services.user_api_tokens import TOKEN_PREFIX, UserAPITokenService
from bloom_lims.config import get_settings
from bloom_lims.db import BLOOMdb3

logger = logging.getLogger(__name__)


class APIUser:
    """Represents an authenticated user context for API handlers."""

    def __init__(
        self,
        *,
        email: str,
        user_id: str | None = None,
        role: str | None = None,
        roles: list[str] | None = None,
        groups: list[str] | None = None,
        permissions: list[str] | None = None,
        auth_source: str = "unknown",
        is_service_account: bool = False,
        token_scope: str | None = None,
        token_id: str | None = None,
    ):
        fallback_role = map_legacy_role(role)
        normalized_roles = normalize_roles(roles or ([fallback_role] if fallback_role else []), fallback=fallback_role)
        if not normalized_roles:
            normalized_roles = [Role.INTERNAL_READ_WRITE.value]
        self.email = email
        self.user_id = user_id or email
        self.roles = normalized_roles
        self.groups = sorted(set(groups or []))
        self.permissions = sorted(set(permissions or effective_permissions(self.roles)))
        self.role = role or self.roles[0]
        self.auth_source = auth_source
        self.is_service_account = is_service_account
        self.token_scope = token_scope
        self.token_id = token_id

    def has_permission(self, permission: Permission | str) -> bool:
        return has_permission(self.roles, permission)

    @property
    def is_admin(self) -> bool:
        return self.has_permission(Permission.BLOOM_ADMIN)

    @property
    def can_write(self) -> bool:
        return self.has_permission(Permission.BLOOM_WRITE)

    @property
    def is_token_authenticated(self) -> bool:
        return self.auth_source == "token"

    def dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "user_id": self.user_id,
            "role": self.role,
            "roles": self.roles,
            "groups": self.groups,
            "permissions": self.permissions,
            "auth_source": self.auth_source,
            "is_service_account": self.is_service_account,
            "token_scope": self.token_scope,
            "token_id": self.token_id,
        }


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_dev_bypass_active() -> bool:
    bypass = _is_truthy(os.environ.get("BLOOM_DEV_AUTH_BYPASS"))
    if not bypass:
        return False
    settings = get_settings()
    env = (os.environ.get("APP_ENV") or settings.environment or "development").lower()
    if env == "production":
        logger.warning("BLOOM_DEV_AUTH_BYPASS denied because environment=production")
        return False
    return True


def _allow_legacy_api_key() -> bool:
    settings = get_settings()
    env = (os.environ.get("APP_ENV") or settings.environment or "development").lower()
    if env != "development":
        return False
    return _is_truthy(os.environ.get("BLOOM_ALLOW_LEGACY_API_KEY"))


def _build_cognito_dependency():
    """Create the Cognito auth dependency if available."""
    try:
        from daylily_cognito.auth import CognitoAuth
        from daylily_cognito.fastapi import create_auth_dependency
        from auth.cognito.client import get_cognito_auth

        auth_cfg = get_cognito_auth().config
        cognito = CognitoAuth(
            region=auth_cfg.region,
            user_pool_id=auth_cfg.user_pool_id,
            app_client_id=auth_cfg.client_id,
        )
        return create_auth_dependency(cognito)
    except Exception as exc:
        logger.debug("daylily-cognito auth not available: %s", exc)
        return None


_cognito_get_user = _build_cognito_dependency()


def _resolve_roles_and_groups(
    *,
    user_id: str | None,
    fallback_role: str | None,
) -> tuple[list[str], list[str], list[str]]:
    normalized_fallback = map_legacy_role(fallback_role)
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        roles = normalize_roles([normalized_fallback], fallback=normalized_fallback)
        permissions = sorted(effective_permissions(roles))
        return roles, [], permissions

    bdb = BLOOMdb3(app_username="api-auth")
    try:
        groups = GroupService(bdb.session)
        resolution = groups.resolve_user_roles_and_groups(
            user_id=normalized_user_id,
            fallback_role=normalized_fallback,
        )
        permissions = sorted(effective_permissions(resolution.roles))
        return resolution.roles, resolution.groups, permissions
    except Exception as exc:
        logger.warning("Failed loading RBAC from groups for user %s: %s", user_id, exc)
        roles = normalize_roles([normalized_fallback], fallback=normalized_fallback)
        permissions = sorted(effective_permissions(roles))
        return roles, [], permissions
    finally:
        bdb.close()


def _make_user(
    *,
    email: str,
    user_id: str | None,
    role_hint: str | None,
    auth_source: str,
    is_service_account: bool = False,
    groups_hint: list[str] | None = None,
    token_scope: str | None = None,
    token_id: str | None = None,
) -> APIUser:
    roles, resolved_groups, permissions = _resolve_roles_and_groups(
        user_id=user_id,
        fallback_role=role_hint,
    )
    all_groups = sorted(set((groups_hint or []) + resolved_groups))
    if API_ACCESS_GROUP in all_groups and Permission.TOKEN_SELF_MANAGE.value not in permissions:
        permissions = sorted(set(permissions + [Permission.TOKEN_SELF_MANAGE.value]))
    primary_role = roles[0] if roles else Role.INTERNAL_READ_WRITE.value
    return APIUser(
        email=email,
        user_id=user_id or email,
        roles=roles,
        groups=all_groups,
        permissions=permissions,
        role=primary_role,
        auth_source=auth_source,
        is_service_account=is_service_account,
        token_scope=token_scope,
        token_id=token_id,
    )


def _authenticate_bloom_token(request: Request, token_value: str) -> APIUser:
    bdb = BLOOMdb3(app_username="api-token-auth")
    try:
        token_service = UserAPITokenService(bdb.session)
        token_service.groups.ensure_system_groups()
        validation = token_service.validate_token(token_value)
        if not validation.is_valid or validation.token is None or validation.revision is None:
            raise HTTPException(
                status_code=401,
                detail=validation.error or "Invalid Bloom API token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_row = validation.token
        constrained_roles, owner_groups = token_service.constrained_roles_for_token_owner(token=token_row)
        permissions = sorted(effective_permissions(constrained_roles))
        user = APIUser(
            email=f"token-user:{token_row.user_id}",
            user_id=str(token_row.user_id),
            roles=constrained_roles,
            groups=owner_groups,
            permissions=permissions,
            role=constrained_roles[0] if constrained_roles else Role.INTERNAL_READ_ONLY.value,
            auth_source="token",
            is_service_account=True,
            token_scope=token_row.scope,
            token_id=str(token_row.id),
        )

        try:
            token_service.mark_token_used(token_id=token_row.id)
            token_service.log_usage(
                token_id=token_row.id,
                user_id=token_row.user_id,
                endpoint=request.url.path,
                http_method=request.method,
                response_status=200,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                request_metadata={
                    "query_params": dict(request.query_params),
                    "content_type": request.headers.get("content-type"),
                },
            )
        except Exception as exc:
            logger.debug("Failed to write token usage metadata: %s", exc)
        return user
    finally:
        bdb.close()


async def verify_api_key(api_key: str) -> APIUser | None:
    """Verify legacy API key and return a service account user."""
    valid_key = os.environ.get("BLOOM_API_KEY")
    if not (valid_key and api_key == valid_key):
        return None
    return _make_user(
        email="api-legacy@daylilyinformatics.com",
        user_id="legacy-api-key",
        role_hint=Role.ADMIN.value,
        auth_source="legacy_api_key",
        is_service_account=True,
        groups_hint=[API_ACCESS_GROUP, Role.ADMIN.value],
    )


async def get_api_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> APIUser:
    """Authenticate API requests and return resolved RBAC context."""
    if _is_dev_bypass_active():
        return APIUser(
            email="api-dev@daylilyinformatics.com",
            user_id="dev-bypass-admin",
            roles=[Role.ADMIN.value],
            groups=[Role.ADMIN.value, API_ACCESS_GROUP],
            permissions=sorted(permission.value for permission in Permission),
            role=Role.ADMIN.value,
            auth_source="dev_bypass",
            is_service_account=True,
        )

    if hasattr(request, "session") and "user_data" in request.session:
        user_data = request.session.get("user_data", {})
        return _make_user(
            email=user_data.get("email", "session-user"),
            user_id=user_data.get("sub"),
            role_hint=user_data.get("role") or user_data.get("custom:role"),
            auth_source="session",
            groups_hint=user_data.get("groups") if isinstance(user_data.get("groups"), list) else [],
        )

    if x_api_key:
        if _allow_legacy_api_key():
            api_user = await verify_api_key(x_api_key)
            if api_user is not None:
                return api_user
        else:
            logger.warning("Legacy X-API-Key auth attempted while disabled")

    if credentials:
        token = (credentials.credentials or "").strip()
        if token.startswith(TOKEN_PREFIX):
            return _authenticate_bloom_token(request, token)
        if _cognito_get_user is not None:
            try:
                claims = _cognito_get_user(credentials)
                return _make_user(
                    email=claims.get("email", "token-user"),
                    user_id=claims.get("sub"),
                    role_hint=claims.get("custom:role") or claims.get("role"),
                    auth_source="cognito",
                    groups_hint=claims.get("cognito:groups")
                    if isinstance(claims.get("cognito:groups"), list)
                    else [],
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Cognito token verification failed: %s", exc)

    raise HTTPException(
        status_code=401,
        detail=(
            "Authentication required. Use session auth for UI, Cognito bearer token, "
            "or Bloom API token (blm_...)."
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_api_auth(user: APIUser = Depends(get_api_user)) -> APIUser:
    return user


async def require_read(user: APIUser = Depends(get_api_user)) -> APIUser:
    if not user.has_permission(Permission.BLOOM_READ):
        raise HTTPException(status_code=403, detail="Read permission required")
    return user


async def require_write(user: APIUser = Depends(get_api_user)) -> APIUser:
    if not user.has_permission(Permission.BLOOM_WRITE):
        raise HTTPException(status_code=403, detail="Write permission required")
    return user


async def require_admin(user: APIUser = Depends(get_api_user)) -> APIUser:
    if not user.has_permission(Permission.BLOOM_ADMIN):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


async def require_external_token_auth(user: APIUser = Depends(get_api_user)) -> APIUser:
    if not user.is_token_authenticated:
        raise HTTPException(
            status_code=401,
            detail="External endpoint requires Bloom API bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_permission(permission: Permission | str):
    async def _check(user: APIUser = Depends(get_api_user)) -> APIUser:
        if not user.has_permission(permission):
            raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
        return user

    return _check


async def optional_api_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> APIUser | None:
    try:
        return await get_api_user(request, credentials, x_api_key)
    except HTTPException:
        return None
