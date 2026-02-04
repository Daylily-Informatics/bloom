"""
BLOOM LIMS API v1 - Dependencies

Common dependencies for API endpoints including authentication.
"""

import logging
import os
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# Optional Bearer token scheme
security = HTTPBearer(auto_error=False)


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


async def get_api_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> APIUser:
    """
    Authenticate API requests.
    
    Supports multiple authentication methods:
    1. Session-based auth (for UI integration)
    2. Bearer token auth (JWT)
    3. API key auth (X-API-Key header)
    
    Returns:
        APIUser object with user information
        
    Raises:
        HTTPException 401 if authentication fails
    """
    # Skip auth in development mode
    if os.environ.get("BLOOM_API_AUTH", "yes") == "no":
        return APIUser(
            email="api-dev@daylilyinformatics.com",
            role="admin",
        )
    
    # 1. Check session-based auth (from UI)
    if hasattr(request, "session") and "user_data" in request.session:
        user_data = request.session["user_data"]
        return APIUser(
            email=user_data.get("email", "session-user"),
            user_id=user_data.get("sub"),
            role=user_data.get("role", "user"),
        )
    
    # 2. Check API key auth
    if x_api_key:
        api_user = await verify_api_key(x_api_key)
        if api_user:
            return api_user
    
    # 3. Check Bearer token auth
    if credentials:
        api_user = await verify_bearer_token(credentials.credentials)
        if api_user:
            return api_user
    
    # No valid authentication found
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide session cookie, Bearer token, or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_api_key(api_key: str) -> Optional[APIUser]:
    """
    Verify an API key and return the associated user.
    
    For now, supports a simple environment-based API key.
    Can be extended to support database-backed API keys.
    """
    valid_key = os.environ.get("BLOOM_API_KEY")
    
    if valid_key and api_key == valid_key:
        return APIUser(
            email="api-service@daylilyinformatics.com",
            role="service",
            is_service_account=True,
        )
    
    return None


async def verify_bearer_token(token: str) -> Optional[APIUser]:
    """
    Verify a Bearer token and return the associated user.
    
    Attempts to verify via Cognito if configured.
    """
    try:
        from auth.cognito.client import get_cognito_auth, CognitoConfigurationError
        
        try:
            cognito = get_cognito_auth()
            # Verify token with Cognito
            user_info = cognito.verify_token(token)
            if user_info:
                return APIUser(
                    email=user_info.get("email", "token-user"),
                    user_id=user_info.get("sub"),
                    role=user_info.get("custom:role", "user"),
                )
        except CognitoConfigurationError:
            logger.debug("Cognito not configured, skipping token verification")
        except Exception as e:
            logger.warning(f"Token verification failed: {e}")
    except ImportError:
        logger.debug("Cognito auth not available")
    
    return None


async def require_api_auth(user: APIUser = Depends(get_api_user)) -> APIUser:
    """
    Dependency that requires authentication.
    Use this in endpoints that need auth.
    """
    return user


async def require_admin(user: APIUser = Depends(get_api_user)) -> APIUser:
    """
    Dependency that requires admin role.
    Use this in endpoints that need admin privileges.

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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[APIUser]:
    """
    Optional authentication - returns None if not authenticated.
    Use this for endpoints that work with or without auth.
    """
    try:
        return await get_api_user(request, credentials, x_api_key)
    except HTTPException:
        return None

