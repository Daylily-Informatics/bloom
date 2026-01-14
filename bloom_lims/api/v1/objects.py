"""
BLOOM LIMS API v1 - Objects Endpoints

CRUD endpoints for BloomObj (generic instances).
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from bloom_lims.schemas import (
    ObjectCreateSchema,
    ObjectUpdateSchema,
    ObjectResponseSchema,
    ObjectQueryParams,
    PaginationParams,
    PaginatedResponse,
    SuccessResponse,
)
from bloom_lims.exceptions import (
    NotFoundError,
    ValidationError,
    DatabaseError,
    create_error_response,
)
from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/objects", tags=["Objects"])


@router.get("/", response_model=Dict[str, Any])
async def list_objects(
    btype: Optional[str] = Query(None, description="Filter by type"),
    b_sub_type: Optional[str] = Query(None, description="Filter by subtype"),
    status: Optional[str] = Query(None, description="Filter by status"),
    name_contains: Optional[str] = Query(None, description="Filter by name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=1000, description="Items per page"),
    user: APIUser = Depends(require_api_auth),
):
    """
    List objects with optional filters.
    
    Returns paginated list of BloomObj instances.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomObj
        
        bdb = BLOOMdb3()
        bo = BloomObj(bdb)
        
        # Build query
        query = bdb.session.query(bdb.Base.classes.generic_instance)
        
        if btype:
            query = query.filter(bdb.Base.classes.generic_instance.btype == btype.lower())
        if b_sub_type:
            query = query.filter(bdb.Base.classes.generic_instance.b_sub_type == b_sub_type.lower())
        if status:
            query = query.filter(bdb.Base.classes.generic_instance.bstatus == status)
        if name_contains:
            query = query.filter(bdb.Base.classes.generic_instance.name.ilike(f"%{name_contains}%"))
        
        # Filter out deleted
        query = query.filter(bdb.Base.classes.generic_instance.is_deleted == False)
        
        # Get total count
        total = query.count()
        
        # Paginate
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()
        
        return {
            "items": [
                {
                    "euid": obj.euid,
                    "uuid": str(obj.uuid),
                    "name": obj.name,
                    "btype": obj.btype,
                    "b_sub_type": obj.b_sub_type,
                    "status": obj.bstatus,
                }
                for obj in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }
        
    except Exception as e:
        logger.error(f"Error listing objects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_object(euid: str, user: APIUser = Depends(require_api_auth)):
    """
    Get a single object by EUID.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomObj
        
        bdb = BLOOMdb3()
        bo = BloomObj(bdb)
        
        obj = bo.get_by_euid(euid)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {euid}")
        
        return {
            "euid": obj.euid,
            "uuid": str(obj.uuid),
            "name": obj.name,
            "btype": obj.btype,
            "b_sub_type": obj.b_sub_type,
            "status": obj.bstatus,
            "json_addl": obj.json_addl,
            "created_at": obj.created_dt.isoformat() if obj.created_dt else None,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error getting object {euid}: {error_msg}")
        # Check for "not found" type errors and return 404
        if "not found" in error_msg.lower() or "no template found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=f"Object not found: {euid}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/", response_model=Dict[str, Any])
async def create_object(data: ObjectCreateSchema, user: APIUser = Depends(require_api_auth)):
    """
    Create a new object.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomObj

        bdb = BLOOMdb3(app_username=user.email)
        bo = BloomObj(bdb)

        # For now, create via template if available
        # This is a simplified implementation
        obj_class = getattr(bdb.Base.classes, 'content_instance')
        obj = obj_class(
            name=data.name,
            btype=data.btype,
            b_sub_type=data.b_sub_type,
            json_addl=data.json_addl or {},
        )

        bdb.session.add(obj)
        bdb.session.commit()

        return {
            "success": True,
            "euid": obj.euid,
            "uuid": str(obj.uuid),
            "message": "Object created successfully",
        }

    except Exception as e:
        logger.error(f"Error creating object: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{euid}", response_model=Dict[str, Any])
async def update_object(
    euid: str,
    data: ObjectUpdateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """
    Update an existing object.

    Supports partial updates - only provided fields are updated.
    json_addl fields are merged, not replaced.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomObj
        from sqlalchemy.orm.attributes import flag_modified

        bdb = BLOOMdb3(app_username=user.email)
        bo = BloomObj(bdb)

        obj = bo.get_by_euid(euid)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {euid}")

        # Update name if provided
        if data.name is not None:
            obj.name = data.name

        # Update status if provided
        if data.status is not None:
            obj.bstatus = data.status

        # Merge json_addl if provided
        if data.json_addl is not None:
            existing = obj.json_addl or {}
            # Deep merge for 'properties' key
            if "properties" in data.json_addl and "properties" in existing:
                existing["properties"].update(data.json_addl["properties"])
                data.json_addl["properties"] = existing["properties"]
            existing.update(data.json_addl)
            obj.json_addl = existing
            flag_modified(obj, "json_addl")

        # Handle soft delete
        if data.is_deleted is not None:
            obj.is_deleted = data.is_deleted

        bdb.session.commit()

        return {
            "success": True,
            "euid": obj.euid,
            "message": "Object updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating object {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{euid}", response_model=Dict[str, Any])
async def delete_object(
    euid: str,
    hard_delete: bool = Query(False, description="Permanently delete (vs soft delete)"),
    user: APIUser = Depends(require_api_auth),
):
    """
    Delete an object.

    By default performs a soft delete (sets is_deleted=True).
    Use hard_delete=True for permanent deletion (use with caution).
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomObj

        bdb = BLOOMdb3(app_username=user.email)
        bo = BloomObj(bdb)

        obj = bo.get_by_euid(euid)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {euid}")

        if hard_delete:
            # Permanent deletion - use with caution
            bo.delete_obj(obj)
        else:
            # Soft delete
            obj.is_deleted = True
            bdb.session.commit()

        return {
            "success": True,
            "euid": euid,
            "message": f"Object {'permanently deleted' if hard_delete else 'soft deleted'} successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting object {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

