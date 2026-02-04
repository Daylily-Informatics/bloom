"""
BLOOM LIMS API v1 - Worksets Endpoints

Endpoints for workset subject management. Worksets group workflow steps
and objects created during a single transaction/batch operation.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/worksets", tags=["Worksets"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


def get_bob(bdb):
    """Get BloomObj instance."""
    from bloom_lims.bobjs import BloomObj
    return BloomObj(bdb)


class WorksetCreateSchema(BaseModel):
    """Schema for creating a workset."""
    anchor_euid: str = Field(..., description="EUID of the anchor object (first workflow step)")
    workset_type: str = Field("accession", description="Type: accession, extraction, sequencing")
    workflow_euid: Optional[str] = Field(None, description="Parent workflow EUID")
    executed_by: Optional[str] = Field(None, description="Username of executor")
    name: Optional[str] = Field(None, description="Custom workset name")


class WorksetMembersSchema(BaseModel):
    """Schema for adding members to a workset."""
    member_euids: List[str] = Field(..., description="List of member EUIDs to add")


class WorksetCompleteSchema(BaseModel):
    """Schema for completing a workset."""
    status: str = Field("complete", description="Final status: complete, failed, abandoned")


@router.get("/", response_model=Dict[str, Any])
async def list_worksets(
    status: Optional[str] = Query(None, description="Filter by status"),
    workflow_euid: Optional[str] = Query(None, description="Filter by workflow"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List worksets with optional filters."""
    try:
        from bloom_lims import subjecting

        bdb = get_bdb(user.email)
        bob = get_bob(bdb)

        worksets = subjecting.list_worksets(
            bob,
            status=status,
            workflow_euid=workflow_euid,
            limit=page_size * page,
        )

        # Paginate
        start = (page - 1) * page_size
        end = start + page_size
        paginated = worksets[start:end]

        return {
            "items": paginated,
            "total": len(worksets),
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing worksets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}", response_model=Dict[str, Any])
async def get_workset(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get a workset by EUID."""
    try:
        from bloom_lims import subjecting

        bdb = get_bdb(user.email)
        bob = get_bob(bdb)

        workset = bob.get_by_euid(euid)
        if not workset:
            raise HTTPException(status_code=404, detail=f"Workset not found: {euid}")

        if workset.category != "subject" or workset.type != "workset":
            raise HTTPException(status_code=404, detail=f"Not a workset: {euid}")

        props = workset.json_addl.get("properties", {})
        members = subjecting.list_members_for_subject(bob, euid)

        return {
            "euid": workset.euid,
            "uuid": str(workset.uuid),
            "name": props.get("name", workset.name),
            "subtype": workset.subtype,
            "subject_key": props.get("subject_key", ""),
            "anchor_euid": props.get("anchor_euid", ""),
            "workflow_euid": props.get("workflow_euid", ""),
            "status": props.get("status", "unknown"),
            "started_at": props.get("started_at", ""),
            "completed_at": props.get("completed_at", ""),
            "executed_by": props.get("executed_by", ""),
            "anchor": members.get("anchor", []),
            "members": members.get("members", []),
            "member_count": len(members.get("members", [])),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workset {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Dict[str, Any])
async def create_workset(
    data: WorksetCreateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Create a new workset."""
    try:
        from bloom_lims import subjecting

        bdb = get_bdb(user.email)
        bob = get_bob(bdb)

        workset_euid = subjecting.create_workset(
            bob,
            anchor_euid=data.anchor_euid,
            workset_type=data.workset_type,
            workflow_euid=data.workflow_euid,
            executed_by=data.executed_by or user.email,
            name=data.name,
        )

        if not workset_euid:
            raise HTTPException(status_code=400, detail="Failed to create workset")

        return {
            "success": True,
            "euid": workset_euid,
            "message": "Workset created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating workset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{euid}/members", response_model=Dict[str, Any])
async def add_workset_members(
    euid: str,
    data: WorksetMembersSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Add members to a workset."""
    try:
        from bloom_lims import subjecting

        bdb = get_bdb(user.email)
        bob = get_bob(bdb)

        # Verify workset exists
        workset = bob.get_by_euid(euid)
        if not workset:
            raise HTTPException(status_code=404, detail=f"Workset not found: {euid}")

        if workset.category != "subject" or workset.type != "workset":
            raise HTTPException(status_code=404, detail=f"Not a workset: {euid}")

        results = subjecting.add_subject_members(bob, euid, data.member_euids)

        success_count = sum(1 for v in results.values() if v)
        failed = [k for k, v in results.items() if not v]

        return {
            "success": len(failed) == 0,
            "workset_euid": euid,
            "added_count": success_count,
            "failed": failed,
            "message": f"Added {success_count} members to workset",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding members to workset {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}/members", response_model=Dict[str, Any])
async def get_workset_members(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get all members of a workset."""
    try:
        from bloom_lims import subjecting

        bdb = get_bdb(user.email)
        bob = get_bob(bdb)

        # Verify workset exists
        workset = bob.get_by_euid(euid)
        if not workset:
            raise HTTPException(status_code=404, detail=f"Workset not found: {euid}")

        if workset.category != "subject" or workset.type != "workset":
            raise HTTPException(status_code=404, detail=f"Not a workset: {euid}")

        members = subjecting.list_members_for_subject(bob, euid)

        return {
            "workset_euid": euid,
            "anchor": members.get("anchor", []),
            "members": members.get("members", []),
            "anchor_count": len(members.get("anchor", [])),
            "member_count": len(members.get("members", [])),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workset members {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{euid}/complete", response_model=Dict[str, Any])
async def complete_workset(
    euid: str,
    data: WorksetCompleteSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Mark a workset as complete (or failed/abandoned)."""
    try:
        from bloom_lims import subjecting

        bdb = get_bdb(user.email)
        bob = get_bob(bdb)

        # Verify workset exists
        workset = bob.get_by_euid(euid)
        if not workset:
            raise HTTPException(status_code=404, detail=f"Workset not found: {euid}")

        if workset.category != "subject" or workset.type != "workset":
            raise HTTPException(status_code=404, detail=f"Not a workset: {euid}")

        success = subjecting.complete_workset(bob, euid, status=data.status)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to complete workset")

        return {
            "success": True,
            "euid": euid,
            "status": data.status,
            "message": f"Workset marked as {data.status}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing workset {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-anchor/{anchor_euid}", response_model=Dict[str, Any])
async def get_workset_by_anchor(
    anchor_euid: str,
    user: APIUser = Depends(require_api_auth),
):
    """Find a workset by its anchor EUID."""
    try:
        from bloom_lims import subjecting

        bdb = get_bdb(user.email)
        bob = get_bob(bdb)

        workset_info = subjecting.get_workset_by_anchor(bob, anchor_euid)

        if not workset_info:
            raise HTTPException(
                status_code=404,
                detail=f"No workset found with anchor: {anchor_euid}"
            )

        return workset_info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error finding workset by anchor {anchor_euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

