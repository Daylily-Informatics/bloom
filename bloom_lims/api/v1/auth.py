"""
BLOOM LIMS API v1 - Auth Endpoints

Authentication and authorization endpoints.
"""

import logging

from fastapi import APIRouter, Depends

from .dependencies import APIUser, require_api_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/me")
async def get_current_user(user: APIUser = Depends(require_api_auth)):
    """Get current authenticated user information."""
    return {
        "id": user.user_id,
        "email": user.email,
        "role": user.role,
    }


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

