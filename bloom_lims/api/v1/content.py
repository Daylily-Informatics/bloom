"""
BLOOM LIMS API v1 - Content Endpoints

CRUD endpoints for content management (samples, specimens, reagents, etc.).
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from bloom_lims.schemas import (
    SampleCreateSchema,
    SpecimenCreateSchema,
    ReagentCreateSchema,
    ContentUpdateSchema,
    ContentResponseSchema,
    PaginatedResponse,
    SuccessResponse,
)
from bloom_lims.exceptions import NotFoundError, ValidationError
from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["Content"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


@router.get("/", response_model=Dict[str, Any])
async def list_content(
    content_type: Optional[str] = Query(None, description="Filter by type (sample, specimen, reagent)"),
    b_sub_type: Optional[str] = Query(None, description="Filter by subtype"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List content objects with optional filters."""
    try:
        bdb = get_bdb(user.email)
        
        query = bdb.session.query(bdb.Base.classes.generic_instance)
        query = query.filter(bdb.Base.classes.generic_instance.super_type == "content")
        
        if content_type:
            query = query.filter(bdb.Base.classes.generic_instance.btype == content_type.lower())
        if b_sub_type:
            query = query.filter(bdb.Base.classes.generic_instance.b_sub_type == b_sub_type.lower())
        if status:
            query = query.filter(bdb.Base.classes.generic_instance.bstatus == status)
        
        query = query.filter(bdb.Base.classes.generic_instance.is_deleted == False)
        
        total = query.count()
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()
        
        return {
            "items": [
                {
                    "euid": obj.euid,
                    "uuid": str(obj.uuid),
                    "name": obj.name,
                    "content_type": obj.btype,
                    "b_sub_type": obj.b_sub_type,
                    "status": obj.bstatus,
                }
                for obj in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_content(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get content by EUID."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent
        
        bc = BloomContent(bdb)
        content = bc.get_by_euid(euid)
        
        if not content:
            raise HTTPException(status_code=404, detail=f"Content not found: {euid}")
        
        return {
            "euid": content.euid,
            "uuid": str(content.uuid),
            "name": content.name,
            "content_type": content.btype,
            "b_sub_type": content.b_sub_type,
            "status": content.bstatus,
            "json_addl": content.json_addl,
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error getting content {euid}: {error_msg}")
        # Check for "not found" type errors and return 404
        if "not found" in error_msg.lower() or "no template found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=f"Content not found: {euid}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/samples", response_model=Dict[str, Any])
async def create_sample(data: SampleCreateSchema, user: APIUser = Depends(require_api_auth)):
    """Create a new sample."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)

        if data.template_euid:
            result = bc.create_empty_content(data.template_euid)
            sample = result[0][0] if isinstance(result, list) else result
        else:
            raise HTTPException(status_code=400, detail="template_euid is required")

        return {
            "success": True,
            "euid": sample.euid,
            "uuid": str(sample.uuid),
            "message": "Sample created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating sample: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/specimens", response_model=Dict[str, Any])
async def create_specimen(data: SpecimenCreateSchema, user: APIUser = Depends(require_api_auth)):
    """Create a new specimen."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)

        if data.template_euid:
            result = bc.create_empty_content(data.template_euid)
            specimen = result[0][0] if isinstance(result, list) else result
        else:
            raise HTTPException(status_code=400, detail="template_euid is required")

        return {
            "success": True,
            "euid": specimen.euid,
            "uuid": str(specimen.uuid),
            "message": "Specimen created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating specimen: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reagents", response_model=Dict[str, Any])
async def create_reagent(data: ReagentCreateSchema, user: APIUser = Depends(require_api_auth)):
    """Create a new reagent."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)

        if data.template_euid:
            result = bc.create_empty_content(data.template_euid)
            reagent = result[0][0] if isinstance(result, list) else result
        else:
            raise HTTPException(status_code=400, detail="template_euid is required")

        return {
            "success": True,
            "euid": reagent.euid,
            "uuid": str(reagent.uuid),
            "message": "Reagent created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating reagent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{euid}", response_model=Dict[str, Any])
async def update_content(
    euid: str,
    data: ContentUpdateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Update content."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent
        from sqlalchemy.orm.attributes import flag_modified

        bc = BloomContent(bdb)
        content = bc.get_by_euid(euid)

        if not content:
            raise HTTPException(status_code=404, detail=f"Content not found: {euid}")

        if data.name is not None:
            content.name = data.name
        if data.status is not None:
            content.bstatus = data.status
        if data.json_addl is not None:
            existing = content.json_addl or {}
            if "properties" in data.json_addl and "properties" in existing:
                existing["properties"].update(data.json_addl["properties"])
                data.json_addl["properties"] = existing["properties"]
            existing.update(data.json_addl)
            content.json_addl = existing
            flag_modified(content, "json_addl")

        bdb.session.commit()

        return {
            "success": True,
            "euid": content.euid,
            "message": "Content updated successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating content {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{euid}", response_model=Dict[str, Any])
async def delete_content(
    euid: str,
    hard_delete: bool = Query(False, description="Permanently delete"),
    user: APIUser = Depends(require_api_auth),
):
    """Delete content (soft delete by default)."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)
        content = bc.get_by_euid(euid)

        if not content:
            raise HTTPException(status_code=404, detail=f"Content not found: {euid}")

        if hard_delete:
            bc.delete_obj(content)
        else:
            content.is_deleted = True
            bdb.session.commit()

        return {
            "success": True,
            "euid": euid,
            "message": f"Content {'permanently deleted' if hard_delete else 'soft deleted'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting content {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

