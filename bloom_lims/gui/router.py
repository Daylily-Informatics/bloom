from __future__ import annotations

from fastapi import APIRouter

from bloom_lims.gui.routes import auth, base, files, graph, modern, operations, workflows


router = APIRouter()

router.include_router(base.router)
router.include_router(auth.router)
router.include_router(modern.router)
router.include_router(operations.router)
router.include_router(workflows.router)
router.include_router(graph.router)
router.include_router(files.router)
