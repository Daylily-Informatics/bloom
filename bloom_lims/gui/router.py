from __future__ import annotations

from fastapi import APIRouter

from bloom_lims.gui.routes import auth, base, graph, modern, operations


router = APIRouter()

router.include_router(base.router)
router.include_router(auth.router)
router.include_router(modern.router)
router.include_router(operations.router)
router.include_router(graph.router)
