"""
BLOOM LIMS API Versioning

This module provides API versioning utilities and infrastructure.

Versioning is handled via:
1. URL prefix: /api/v1, /api/v2, etc.
2. Optional Accept header: application/vnd.bloom.v1+json
"""

import logging
import re
from enum import Enum
from typing import Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.routing import APIRoute


logger = logging.getLogger(__name__)


class APIVersion(str, Enum):
    """Supported API versions."""
    V1 = "v1"
    # V2 = "v2"  # Future version
    
    @classmethod
    def latest(cls) -> "APIVersion":
        """Get the latest API version."""
        return cls.V1
    
    @classmethod
    def from_string(cls, version_str: str) -> Optional["APIVersion"]:
        """Parse version string to APIVersion enum."""
        version_str = version_str.lower().strip()
        if not version_str.startswith("v"):
            version_str = f"v{version_str}"
        
        for v in cls:
            if v.value == version_str:
                return v
        return None


# Version negotiation via Accept header
ACCEPT_HEADER_PATTERN = re.compile(
    r"application/vnd\.bloom\.v(\d+)\+json",
    re.IGNORECASE
)


def parse_accept_header(accept: str) -> Optional[APIVersion]:
    """
    Parse API version from Accept header.
    
    Supports format: application/vnd.bloom.v1+json
    
    Args:
        accept: Accept header value
        
    Returns:
        APIVersion if found, None otherwise
    """
    if not accept:
        return None
    
    match = ACCEPT_HEADER_PATTERN.search(accept)
    if match:
        version_num = match.group(1)
        return APIVersion.from_string(f"v{version_num}")
    
    return None


async def version_header_dependency(
    accept: Optional[str] = Header(None),
) -> Optional[APIVersion]:
    """
    FastAPI dependency for extracting API version from Accept header.
    
    Usage:
        @router.get("/resource")
        async def get_resource(version: APIVersion = Depends(version_header_dependency)):
            ...
    """
    if accept:
        version = parse_accept_header(accept)
        if version:
            return version
    return None


def get_api_version(request: Request) -> APIVersion:
    """
    Get API version from request path or headers.
    
    Priority:
    1. URL path prefix (/api/v1/...)
    2. Accept header
    3. Default to latest version
    """
    # Check URL path
    path = request.url.path
    if "/api/v1/" in path or path.startswith("/api/v1"):
        return APIVersion.V1
    # Add more versions as needed
    
    # Check Accept header
    accept = request.headers.get("accept", "")
    header_version = parse_accept_header(accept)
    if header_version:
        return header_version
    
    # Default to latest
    return APIVersion.latest()


def create_versioned_router(
    version: APIVersion,
    prefix: str = "",
    **kwargs,
) -> APIRouter:
    """
    Create an API router with version prefix.
    
    Args:
        version: API version
        prefix: Additional prefix after version
        **kwargs: Additional router arguments
        
    Returns:
        Configured APIRouter
    """
    full_prefix = f"/api/{version.value}"
    if prefix:
        full_prefix = f"{full_prefix}/{prefix.strip('/')}"
    
    return APIRouter(prefix=full_prefix, **kwargs)


class VersionedAPIRoute(APIRoute):
    """
    Custom route class that logs API version usage.
    
    Can be used to track version adoption and deprecation.
    """
    
    def get_route_handler(self):
        original_handler = super().get_route_handler()
        
        async def versioned_handler(request: Request):
            version = get_api_version(request)
            logger.debug(f"API {version.value} request: {request.method} {request.url.path}")
            return await original_handler(request)
        
        return versioned_handler

