"""
BLOOM LIMS API v1 - Dependencies

Common dependencies for API endpoints including authentication.

Authentication is provided by daylily-cognito's ``create_auth_dependency()``.
A LOCAL DEV ONLY bypass is available via ``BLOOM_DEV_AUTH_BYPASS=true``.
The bypass is blocked when ``APP_ENV=production``.
"""

import logging
import os
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# APIUser — kept for backward compatibility with all endpoint signatures
# ---------------------------------------------------------------------------


class APIUser:
    """Represents an authenticated API user."""

    def __init__(
        self,
        email: str,
        user_id: Optional[str] = None,
        role: str = "user",
        is_service_account: bool = False,
    ):
        self.email = email
        self.user_id = user_id or email
        self.role = role
        self.is_service_account = is_service_account

    def dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "user_id": self.user_id,
            "role": self.role,
            "is_service_account": self.is_service_account,
        }


# ---------------------------------------------------------------------------
# Dev bypass guard
# ---------------------------------------------------------------------------

def _is_dev_bypass_active() -> bool:
    """Return True only when the dev auth bypass is enabled AND safe.

    Conditions (ALL must be true):
      1. ``BLOOM_DEV_AUTH_BYPASS`` is set to a truthy value (``true``, ``1``, ``yes``).
      2. ``APP_ENV`` is **not** ``production``.
    """
    bypass = os.environ.get("BLOOM_DEV_AUTH_BYPASS", "").lower()
    if bypass not in ("true", "1", "yes"):
        return False
    env = os.environ.get("APP_ENV", "development").lower()
    if env == "production":
        logger.warning(
            "BLOOM_DEV_AUTH_BYPASS is set but APP_ENV=production — bypass DENIED."
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Cognito-backed auth dependency
# ---------------------------------------------------------------------------

def _build_cognito_dependency():
    """Create the real Cognito auth dependency via daylily-cognito.

    Returns the FastAPI dependency callable, or None if daylily-cognito
    is not configured (e.g. missing env vars / config).
    """
    try:
        from daylily_cognito.fastapi import create_auth_dependency
        from auth.cognito.client import get_cognito_auth

        cognito = get_cognito_auth()
        return create_auth_dependency(cognito.auth)
    except Exception as exc:
        logger.debug("daylily-cognito auth not available: %s", exc)
        return None


_cognito_get_user = None


def _get_cognito_dependency():
    """Lazily initialize the Cognito dependency.

    This allows Bloom to start before daycog env files are available, and
    initialize auth on first bearer-token request after configuration exists.
    """
    global _cognito_get_user
    if _cognito_get_user is None:
        _cognito_get_user = _build_cognito_dependency()
    return _cognito_get_user


# ---------------------------------------------------------------------------
# Core auth dependency — used by every protected endpoint
# ---------------------------------------------------------------------------

async def get_api_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> APIUser:
    """Authenticate API requests.

    Auth chain (first match wins):
      1. Dev bypass (``BLOOM_DEV_AUTH_BYPASS=true``, non-production only)
      2. Session cookie (UI integration)
      3. ``X-API-Key`` header
      4. Bearer token verified by daylily-cognito
    """
    # 1. LOCAL DEV ONLY bypass ------------------------------------------------
    if _is_dev_bypass_active():
        return APIUser(
            email="api-dev@daylilyinformatics.com",
            role="admin",
        )

    # 2. Session-based auth (UI) ----------------------------------------------
    if hasattr(request, "session") and "user_data" in request.session:
        user_data = request.session["user_data"]
        return APIUser(
            email=user_data.get("email", "session-user"),
            user_id=user_data.get("sub"),
            role=user_data.get("role", "user"),
        )

    # 3. API key auth ---------------------------------------------------------
    if x_api_key:
        api_user = await verify_api_key(x_api_key)
        if api_user:
            return api_user

    # 4. Bearer token via daylily-cognito -------------------------------------
    cognito_dep = _get_cognito_dependency()
    if credentials and cognito_dep is not None:
        try:
            claims = cognito_dep(credentials)
            return APIUser(
                email=claims.get("email", "token-user"),
                user_id=claims.get("sub"),
                role=claims.get("custom:role", "user"),
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Cognito token verification failed: %s", exc)

    # Nothing worked ----------------------------------------------------------
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide session cookie, Bearer token, or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# API key verification (unchanged)
# ---------------------------------------------------------------------------

async def verify_api_key(api_key: str) -> Optional[APIUser]:
    """Verify an API key and return the associated user."""
    valid_key = os.environ.get("BLOOM_API_KEY")
    if valid_key and api_key == valid_key:
        return APIUser(
            email="api-service@daylilyinformatics.com",
            role="service",
            is_service_account=True,
        )
    return None


# ---------------------------------------------------------------------------
# Convenience wrappers (public API unchanged)
# ---------------------------------------------------------------------------

async def require_api_auth(user: APIUser = Depends(get_api_user)) -> APIUser:
    """Dependency that requires authentication."""
    return user


async def require_admin(user: APIUser = Depends(get_api_user)) -> APIUser:
    """Dependency that requires admin role.

    Raises:
        HTTPException 403 if user is not admin
    """
    if user.role not in ("admin", "service"):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required for this operation.",
        )
    return user


async def optional_api_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[APIUser]:
    """Optional authentication — returns None if not authenticated."""
    try:
        return await get_api_user(request, credentials, x_api_key)
    except HTTPException:
        return None
