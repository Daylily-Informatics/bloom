"""
BLOOM LIMS API v1 - Lineages Endpoints

Endpoints for lineage/relationship management between objects.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/lineages", tags=["Lineages"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


class LineageCreateSchema(BaseModel):
    """Schema for creating a lineage relationship."""
    parent_euid: str = Field(..., description="Parent object EUID")
    child_euid: str = Field(..., description="Child object EUID")
    relationship_type: Optional[str] = Field(None, description="Type of relationship")


class LineageUpdateSchema(BaseModel):
    """Schema for updating a lineage."""
    relationship_type: Optional[str] = Field(None, description="Type of relationship")
    json_addl: Optional[Dict[str, Any]] = Field(None, description="Additional properties")


@router.get("/", response_model=Dict[str, Any])
async def list_lineages(
    parent_euid: Optional[str] = Query(None, description="Filter by parent EUID"),
    child_euid: Optional[str] = Query(None, description="Filter by child EUID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List lineages with optional filters."""
    try:
        bdb = get_bdb(user.email)
        
        query = bdb.session.query(bdb.Base.classes.generic_instance_lineage)
        query = query.filter(bdb.Base.classes.generic_instance_lineage.is_deleted == False)
        
        if parent_euid:
            parent = bdb.session.query(bdb.Base.classes.generic_instance).filter(
                bdb.Base.classes.generic_instance.euid == parent_euid
            ).first()
            if parent:
                query = query.filter(
                    bdb.Base.classes.generic_instance_lineage.parent_instance_uuid == parent.uuid
                )
        
        if child_euid:
            child = bdb.session.query(bdb.Base.classes.generic_instance).filter(
                bdb.Base.classes.generic_instance.euid == child_euid
            ).first()
            if child:
                query = query.filter(
                    bdb.Base.classes.generic_instance_lineage.child_instance_uuid == child.uuid
                )
        
        total = query.count()
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()
        
        return {
            "items": [
                {
                    "uuid": str(lin.uuid),
                    "parent_euid": lin.parent_instance.euid if lin.parent_instance else None,
                    "child_euid": lin.child_instance.euid if lin.child_instance else None,
                    "relationship_type": lin.json_addl.get("relationship_type") if lin.json_addl else None,
                }
                for lin in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing lineages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Dict[str, Any])
async def create_lineage(
    data: LineageCreateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Create a new lineage relationship between objects."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomObj
        
        bo = BloomObj(bdb)
        
        parent = bo.get_by_euid(data.parent_euid)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent not found: {data.parent_euid}")
        
        child = bo.get_by_euid(data.child_euid)
        if not child:
            raise HTTPException(status_code=404, detail=f"Child not found: {data.child_euid}")
        
        # Create lineage
        lineage = bo.create_lineage(parent, child)
        
        if data.relationship_type:
            lineage.json_addl = lineage.json_addl or {}
            lineage.json_addl["relationship_type"] = data.relationship_type
            bdb.session.commit()
        
        return {
            "success": True,
            "uuid": str(lineage.uuid),
            "parent_euid": data.parent_euid,
            "child_euid": data.child_euid,
            "message": "Lineage created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating lineage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{uuid}", response_model=Dict[str, Any])
async def delete_lineage(
    uuid: str,
    hard_delete: bool = Query(False, description="Permanently delete"),
    user: APIUser = Depends(require_api_auth),
):
    """Delete a lineage (soft delete by default)."""
    try:
        bdb = get_bdb(user.email)
        import uuid as uuid_lib
        
        lineage = bdb.session.query(bdb.Base.classes.generic_instance_lineage).filter(
            bdb.Base.classes.generic_instance_lineage.uuid == uuid_lib.UUID(uuid)
        ).first()
        
        if not lineage:
            raise HTTPException(status_code=404, detail=f"Lineage not found: {uuid}")
        
        if hard_delete:
            bdb.session.delete(lineage)
        else:
            lineage.is_deleted = True
        
        bdb.session.commit()
        
        return {
            "success": True,
            "uuid": uuid,
            "message": f"Lineage {'permanently deleted' if hard_delete else 'soft deleted'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting lineage {uuid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

