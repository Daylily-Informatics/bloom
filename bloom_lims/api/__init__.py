"""
BLOOM LIMS API Module

This module provides the versioned API infrastructure for BLOOM LIMS.

API Versioning Strategy:
    - All endpoints are prefixed with /api/v{version}
    - Version 1 is the current stable version
    - Backward compatibility maintained for deprecated endpoints
    - Version negotiation via Accept header (optional)

Usage:
    from bloom_lims.api import create_api_app, api_v1_router
    
    app = FastAPI()
    app.include_router(api_v1_router)
"""

from .versioning import (
    APIVersion,
    get_api_version,
    create_versioned_router,
    version_header_dependency,
)
from .v1 import router as api_v1_router

__all__ = [
    "APIVersion",
    "get_api_version",
    "create_versioned_router",
    "version_header_dependency",
    "api_v1_router",
]

