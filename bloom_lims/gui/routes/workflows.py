"""Retired workflow GUI routes for queue-only Bloom beta."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from bloom_lims.gui.deps import require_auth


router = APIRouter()


def _retired() -> None:
    raise HTTPException(
        status_code=410,
        detail="Workflow GUI routes are retired in queue-centric Bloom beta.",
    )


@router.get("/workflow_summary")
async def workflow_summary(request: Request, _auth=Depends(require_auth)):
    _ = (request, _auth)
    _retired()


@router.get("/workflow_details")
async def workflow_details(request: Request, _auth=Depends(require_auth)):
    _ = (request, _auth)
    _retired()


@router.post("/update_accordion_state")
async def update_accordion_state(request: Request, _auth=Depends(require_auth)):
    _ = (request, _auth)
    _retired()


@router.post("/update_obj_json_addl_properties")
async def update_obj_json_addl_properties(request: Request, _auth=Depends(require_auth)):
    _ = (request, _auth)
    _retired()
