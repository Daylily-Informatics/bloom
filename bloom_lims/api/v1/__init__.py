"""
BLOOM LIMS API v1

This module provides the version 1 API endpoints for BLOOM LIMS.
All endpoints are prefixed with /api/v1.

Usage:
    from bloom_lims.api.v1 import router
    app.include_router(router)
"""

from fastapi import APIRouter

from .admin_auth import router as admin_auth_router
from .async_tasks import router as async_tasks_router
from .atlas_bridge import router as atlas_bridge_router
from .auth import router as auth_router
from .batch import router as batch_router
from .beta_lab import router as beta_lab_router
from .containers import router as containers_router
from .content import router as content_router
from .equipment import router as equipment_router
from .execution_queue import router as execution_queue_router
from .external_specimens import router as external_specimens_router
from .graph import router as graph_router
from .lineages import router as lineages_router
from .object_creation import router as object_creation_router
from .objects import router as objects_router
from .search import router as search_router
from .search_v2 import router as search_v2_router
from .stats import router as stats_router
from .subjects import router as subjects_router
from .templates import router as templates_router
from .tracking import router as tracking_router
from .user_api_tokens import router as user_api_tokens_router

# Main v1 router
router = APIRouter(prefix="/api/v1", tags=["API v1"])

# Include sub-routers
router.include_router(objects_router)
router.include_router(auth_router)
router.include_router(containers_router)
router.include_router(content_router)
router.include_router(equipment_router)
router.include_router(execution_queue_router)
router.include_router(batch_router)
router.include_router(async_tasks_router)
router.include_router(templates_router)
router.include_router(subjects_router)
router.include_router(lineages_router)
router.include_router(stats_router)
router.include_router(search_router)
router.include_router(search_v2_router)
router.include_router(object_creation_router)
router.include_router(tracking_router)
router.include_router(user_api_tokens_router)
router.include_router(admin_auth_router)
router.include_router(external_specimens_router)
router.include_router(atlas_bridge_router)
router.include_router(beta_lab_router)
router.include_router(graph_router)


@router.get("/")
async def api_v1_info():
    """Get API v1 information."""
    return {
        "version": "1.0.0",
        "status": "stable",
        "documentation": "/docs",
        "endpoints": {
            "objects": "/api/v1/objects",
            "auth": "/api/v1/auth",
            "containers": "/api/v1/containers",
            "content": "/api/v1/content",
            "equipment": "/api/v1/equipment",
            "execution": "/api/v1/execution",
            "batch": "/api/v1/batch",
            "tasks": "/api/v1/tasks",
            "templates": "/api/v1/templates",
            "subjects": "/api/v1/subjects",
            "lineages": "/api/v1/lineages",
            "stats": "/api/v1/stats",
            "search": "/api/v1/search",
            "search_v2": "/api/v1/search/v2",
            "object_creation": "/api/v1/object-creation",
            "user_tokens": "/api/v1/user-tokens",
            "admin_auth": "/api/v1/admin/groups",
            "external_specimens": "/api/v1/external/specimens",
            "external_atlas": "/api/v1/external/atlas",
            "external_atlas_beta": "/api/v1/external/atlas/beta",
            "graph": "/api/v1/graph",
        },
    }
