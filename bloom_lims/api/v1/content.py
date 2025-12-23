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


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["Content"])


def get_bdb():
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3()


@router.get("/", response_model=Dict[str, Any])
async def list_content(
    content_type: Optional[str] = Query(None, description="Filter by type (sample, specimen, reagent)"),
    b_sub_type: Optional[str] = Query(None, description="Filter by subtype"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    """List content objects with optional filters."""
    try:
        bdb = get_bdb()
        
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
async def get_content(euid: str):
    """Get content by EUID."""
    try:
        bdb = get_bdb()
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
        logger.error(f"Error getting content {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/samples", response_model=Dict[str, Any])
async def create_sample(data: SampleCreateSchema):
    """Create a new sample."""
    try:
        bdb = get_bdb()
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
async def create_specimen(data: SpecimenCreateSchema):
    """Create a new specimen."""
    try:
        bdb = get_bdb()
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

