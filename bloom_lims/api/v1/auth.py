"""
BLOOM LIMS API v1 - Auth Endpoints

Authentication and authorization endpoints.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Header


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/me")
async def get_current_user(
    authorization: Optional[str] = Header(None),
):
    """
    Get current authenticated user information.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        from bloom_lims.auth import verify_token
        
        # Extract token from Bearer header
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization
        
        user = verify_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "id": user.get("id"),
            "email": user.get("email"),
            "role": user.get("role", "user"),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/logout")
async def logout():
    """
    Logout current user.
    
    Note: For JWT-based auth, this is typically handled client-side.
    This endpoint can be used to invalidate refresh tokens if implemented.
    """
    return {
        "success": True,
        "message": "Logged out successfully",
    }

