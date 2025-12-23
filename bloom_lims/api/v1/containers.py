"""
BLOOM LIMS API v1 - Containers Endpoints

CRUD endpoints for container management (plates, racks, boxes, etc.).
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from bloom_lims.schemas import (
    ContainerCreateSchema,
    ContainerUpdateSchema,
    ContainerResponseSchema,
    PlaceInContainerSchema,
    BulkPlaceInContainerSchema,
    PaginatedResponse,
    SuccessResponse,
)
from bloom_lims.exceptions import NotFoundError, ValidationError


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/containers", tags=["Containers"])


def get_bdb():
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3()


@router.get("/", response_model=Dict[str, Any])
async def list_containers(
    container_type: Optional[str] = Query(None, description="Filter by type (plate, rack, box)"),
    b_sub_type: Optional[str] = Query(None, description="Filter by subtype"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    """List containers with optional filters."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomContainer
        
        bc = BloomContainer(bdb)
        query = bdb.session.query(bdb.Base.classes.generic_instance)
        query = query.filter(bdb.Base.classes.generic_instance.super_type == "container")
        
        if container_type:
            query = query.filter(bdb.Base.classes.generic_instance.btype == container_type.lower())
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
                    "container_type": obj.btype,
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
        logger.error(f"Error listing containers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_container(euid: str, include_contents: bool = Query(False)):
    """Get a container by EUID, optionally including contents."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomContainer
        
        bc = BloomContainer(bdb)
        container = bc.get_by_euid(euid)
        
        if not container:
            raise HTTPException(status_code=404, detail=f"Container not found: {euid}")
        
        result = {
            "euid": container.euid,
            "uuid": str(container.uuid),
            "name": container.name,
            "container_type": container.btype,
            "b_sub_type": container.b_sub_type,
            "status": container.bstatus,
            "json_addl": container.json_addl,
        }
        
        if include_contents:
            contents = []
            for lineage in container.parent_of_lineages:
                child = lineage.child_instance
                contents.append({
                    "euid": child.euid,
                    "name": child.name,
                    "type": child.btype,
                    "position": child.json_addl.get("cont_address") if child.json_addl else None,
                })
            result["contents"] = contents
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting container {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Dict[str, Any])
async def create_container(data: ContainerCreateSchema):
    """Create a new container from a template."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomContainer
        
        bc = BloomContainer(bdb)
        
        if data.template_euid:
            result = bc.create_empty_container(data.template_euid)
            container = result[0][0] if isinstance(result, list) else result
        else:
            raise HTTPException(status_code=400, detail="template_euid is required")
        
        return {
            "success": True,
            "euid": container.euid,
            "uuid": str(container.uuid),
            "message": "Container created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating container: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{container_euid}/contents")
async def add_content_to_container(container_euid: str, data: PlaceInContainerSchema):
    """Add content to a container."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomContainer
        
        bc = BloomContainer(bdb)
        bc.link_content(container_euid, data.content_euid)
        
        return {"success": True, "message": "Content added to container"}
    except Exception as e:
        logger.error(f"Error adding content to container: {e}")
        raise HTTPException(status_code=500, detail=str(e))

