"""
BLOOM LIMS API v1

This module provides the version 1 API endpoints for BLOOM LIMS.
All endpoints are prefixed with /api/v1.

Usage:
    from bloom_lims.api.v1 import router
    app.include_router(router)
"""

from fastapi import APIRouter

from .objects import router as objects_router
from .workflows import router as workflows_router
from .auth import router as auth_router
from .containers import router as containers_router
from .content import router as content_router
from .files import router as files_router
from .equipment import router as equipment_router
from .batch import router as batch_router
from .async_tasks import router as async_tasks_router


# Main v1 router
router = APIRouter(prefix="/api/v1", tags=["API v1"])

# Include sub-routers
router.include_router(objects_router)
router.include_router(workflows_router)
router.include_router(auth_router)
router.include_router(containers_router)
router.include_router(content_router)
router.include_router(files_router)
router.include_router(equipment_router)
router.include_router(batch_router)
router.include_router(async_tasks_router)


@router.get("/")
async def api_v1_info():
    """Get API v1 information."""
    return {
        "version": "1.0.0",
        "status": "stable",
        "documentation": "/docs",
        "endpoints": {
            "objects": "/api/v1/objects",
            "workflows": "/api/v1/workflows",
            "auth": "/api/v1/auth",
            "containers": "/api/v1/containers",
            "content": "/api/v1/content",
            "files": "/api/v1/files",
            "equipment": "/api/v1/equipment",
            "batch": "/api/v1/batch",
            "tasks": "/api/v1/tasks",
        },
    }

