"""Retired workflow API surface for queue-only Bloom beta."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/workflows", tags=["Workflows"])


def _retired() -> None:
    raise HTTPException(
        status_code=410,
        detail="Workflow APIs are retired in queue-centric Bloom beta.",
    )


@router.get("/")
async def list_workflows():
    _retired()


@router.get("/{euid}")
async def get_workflow(euid: str):
    _ = euid
    _retired()


@router.post("/{euid}/advance")
async def advance_workflow(euid: str):
    _ = euid
    _retired()


@router.post("/")
async def create_workflow():
    _retired()


@router.put("/{euid}")
async def update_workflow(euid: str):
    _ = euid
    _retired()


@router.get("/{euid}/steps")
async def get_workflow_steps(euid: str):
    _ = euid
    _retired()
