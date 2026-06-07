"""
BLOOM LIMS API v1 - Auth Endpoints

Authentication and authorization endpoints.
"""

import logging
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .dependencies import APIUser, require_api_auth

logger = logging.getLogger(__name__)
THEME_NAMES = {"original", "lsmc", "dark", "light", "tacky"}

router = APIRouter(prefix="/auth", tags=["Authentication"])
preferences_router = APIRouter(tags=["Preferences"])


def _broker_preferences_contract(email: str) -> tuple[str, dict[str, str]]:
    raw_url = str(os.environ.get("LSMC_AUTH_BROKER_USER_PREFERENCES_URL") or "").strip()
    token = str(os.environ.get("LSMC_AUTH_BROKER_SERVICE_TOKEN") or "").strip()
    service_id = str(os.environ.get("LSMC_AUTH_BROKER_SERVICE_ID") or "bloom").strip()
    if not raw_url:
        raise HTTPException(status_code=503, detail="Broker user preferences URL is not configured")
    if not token:
        raise HTTPException(status_code=503, detail="Broker service token is not configured")
    if "{email}" not in raw_url:
        raise HTTPException(
            status_code=503,
            detail="Broker user preferences URL must include {email}",
        )
    return raw_url.replace("{email}", quote(email, safe="")), {
        "Authorization": f"Bearer {token}",
        "X-LSMC-Service-ID": service_id,
    }


@router.get("/me")
async def get_current_user(user: APIUser = Depends(require_api_auth)):
    """Get current authenticated user information."""
    return {
        "id": user.user_id,
        "email": user.email,
        "role": user.role,
        "roles": user.roles,
        "groups": user.groups,
        "permissions": user.permissions,
        "auth_source": user.auth_source,
        "token_scope": user.token_scope,
        "token_id": user.token_id,
    }


@preferences_router.get("/me/preferences")
async def current_user_preferences(user: APIUser = Depends(require_api_auth)):
    if not user.email:
        raise HTTPException(status_code=400, detail="Authenticated user email is required")
    url, headers = _broker_preferences_contract(user.email)
    with httpx.Client(timeout=5.0) as client:
        response = client.get(url, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@preferences_router.put("/me/preferences")
async def update_current_user_preferences(
    request: Request,
    user: APIUser = Depends(require_api_auth),
):
    if not user.email:
        raise HTTPException(status_code=400, detail="Authenticated user email is required")
    payload = await request.json()
    theme = str(payload.get("theme") or "").strip()
    if theme and theme not in THEME_NAMES:
        raise HTTPException(status_code=400, detail="Unknown theme")
    url, headers = _broker_preferences_contract(user.email)
    with httpx.Client(timeout=5.0) as client:
        response = client.put(url, headers=headers, json={"theme": theme or None})
        if response.status_code < 400:
            response = client.get(url, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@router.post("/logout")
async def logout():
    """Logout current user.

    Note: For JWT-based auth, this is typically handled client-side.
    This endpoint can be used to invalidate refresh tokens if implemented.
    """
    return {
        "success": True,
        "message": "Logged out successfully",
    }
