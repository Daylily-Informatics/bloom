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
from .dependencies import APIUser, require_read, require_write


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/objects", tags=["Objects"])


@router.get("/", response_model=Dict[str, Any])
async def list_objects(
    type: Optional[str] = Query(None, description="Filter by type"),
    subtype: Optional[str] = Query(None, description="Filter by subtype"),
    status: Optional[str] = Query(None, description="Filter by status"),
    name_contains: Optional[str] = Query(None, description="Filter by name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=1000, description="Items per page"),
    user: APIUser = Depends(require_read),
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

        if type:
            query = query.filter(bdb.Base.classes.generic_instance.type == type.lower())
        if subtype:
            query = query.filter(bdb.Base.classes.generic_instance.subtype == subtype.lower())
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
                    "type": obj.type,
                    "subtype": obj.subtype,
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
async def get_object(euid: str, user: APIUser = Depends(require_read)):
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
            "type": obj.type,
            "subtype": obj.subtype,
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
async def create_object(data: ObjectCreateSchema, user: APIUser = Depends(require_write)):
    """
    Create a new object.
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomObj

        bdb = BLOOMdb3(app_username=user.email)
        bo = BloomObj(bdb)
        bo.set_actor_context(user_id=user.user_id, email=user.email)

        # TapDB requires instances be created from templates (template_uuid NOT NULL).
        category = (data.category or "").strip().lower()
        if not category or category == "instance":
            category = "content"

        version = "1.0"
        templates = bo.query_template_by_component_v2(
            category=category,
            type=data.type,
            subtype=data.subtype,
            version=version,
        )
        if not templates and data.subtype:
            # Fallback: if subtype doesn't exist, allow creating from the first
            # matching category/type template.
            templates = bo.query_template_by_component_v2(
                category=category,
                type=data.type,
                subtype=None,
                version=version,
            )
        if not templates:
            raise HTTPException(
                status_code=400,
                detail=f"No template found for {category}/{data.type}/{data.subtype or '*'}@{version}",
            )

        json_overrides = data.json_addl or {}
        props = json_overrides.get("properties")
        if not isinstance(props, dict):
            props = {}
        props.setdefault("name", data.name)
        json_overrides["properties"] = props

        obj = bo.create_instance(templates[0].euid, json_overrides)
        obj.name = data.name
        bdb.session.commit()
        bo.track_user_interaction(
            obj.euid,
            relationship_type="user_created",
            user_id=user.user_id,
            email=user.email,
        )

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
    user: APIUser = Depends(require_write),
):
    """
    Update an existing object. Requires admin privileges.

    Supports partial updates - only provided fields are updated.
    json_addl fields are merged, not replaced.

    Editable fields:
    - name: Object name
    - status: Object status (bstatus)
    - created_dt: Creation datetime
    - is_deleted: Soft delete flag
    - json_addl: Additional JSON data (merged with existing)
    """
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.bobjs import BloomObj
        from sqlalchemy.orm.attributes import flag_modified

        bdb = BLOOMdb3(app_username=user.email)
        bo = BloomObj(bdb)
        bo.set_actor_context(user_id=user.user_id, email=user.email)

        obj = bo.get_by_euid(euid)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {euid}")

        # Update name if provided
        if data.name is not None:
            obj.name = data.name
            # Also update in json_addl.properties.name for consistency
            if obj.json_addl and "properties" in obj.json_addl:
                obj.json_addl["properties"]["name"] = data.name
                flag_modified(obj, "json_addl")

        # Update status if provided
        if data.status is not None:
            obj.bstatus = data.status

        # Update created_dt if provided
        if data.created_dt is not None:
            obj.created_dt = data.created_dt

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
        bo.track_user_interaction(
            obj.euid,
            relationship_type="user_updated",
            user_id=user.user_id,
            email=user.email,
        )

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
    user: APIUser = Depends(require_write),
):
    """
    Delete an object. Requires admin privileges.

    By default performs a soft delete (sets is_deleted=True).
    Use hard_delete=True for permanent deletion (use with caution).
    """
    try:
        if hard_delete and not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required for hard delete")

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
