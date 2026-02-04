"""
BLOOM LIMS API v1 - Subjects Endpoints

Endpoints for subject management (patients, donors, etc.).
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/subjects", tags=["Subjects"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


class SubjectCreateSchema(BaseModel):
    """Schema for creating a subject."""
    template_euid: str = Field(..., description="Template EUID to create from")
    name: Optional[str] = Field(None, description="Subject name/identifier")
    external_id: Optional[str] = Field(None, description="External identifier")
    json_addl: Optional[Dict[str, Any]] = Field(None, description="Additional properties")


class SubjectUpdateSchema(BaseModel):
    """Schema for updating a subject."""
    name: Optional[str] = Field(None, description="Subject name/identifier")
    status: Optional[str] = Field(None, description="Subject status")
    json_addl: Optional[Dict[str, Any]] = Field(None, description="Additional properties")


@router.get("/", response_model=Dict[str, Any])
async def list_subjects(
    subtype: Optional[str] = Query(None, description="Filter by subtype"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List subjects with optional filters."""
    try:
        bdb = get_bdb(user.email)

        query = bdb.session.query(bdb.Base.classes.generic_instance)
        query = query.filter(bdb.Base.classes.generic_instance.category == "subject")

        if subtype:
            query = query.filter(bdb.Base.classes.generic_instance.subtype == subtype.lower())
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
                    "type": obj.type,
                    "subtype": obj.subtype,
                    "status": obj.bstatus,
                }
                for obj in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing subjects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_subject(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get a subject by EUID."""
    try:
        bdb = get_bdb(user.email)
        
        subject = bdb.session.query(bdb.Base.classes.generic_instance).filter(
            bdb.Base.classes.generic_instance.euid == euid,
            bdb.Base.classes.generic_instance.category == "subject",
        ).first()

        if not subject:
            raise HTTPException(status_code=404, detail=f"Subject not found: {euid}")

        return {
            "euid": subject.euid,
            "uuid": str(subject.uuid),
            "name": subject.name,
            "type": subject.type,
            "subtype": subject.subtype,
            "status": subject.bstatus,
            "json_addl": subject.json_addl,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting subject {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Dict[str, Any])
async def create_subject(
    data: SubjectCreateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Create a new subject from a template."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomObj
        from sqlalchemy.orm.attributes import flag_modified
        
        bo = BloomObj(bdb)
        result = bo.create_instances(data.template_euid)
        
        if not result or not result[0]:
            raise HTTPException(status_code=400, detail="Failed to create subject from template")
        
        subject = result[0][0]
        
        if data.name:
            subject.name = data.name
        if data.external_id:
            subject.json_addl = subject.json_addl or {}
            subject.json_addl.setdefault("properties", {})["external_id"] = data.external_id
            flag_modified(subject, "json_addl")
        if data.json_addl:
            existing = subject.json_addl or {}
            existing.update(data.json_addl)
            subject.json_addl = existing
            flag_modified(subject, "json_addl")
        
        bdb.session.commit()
        
        return {
            "success": True,
            "euid": subject.euid,
            "uuid": str(subject.uuid),
            "message": "Subject created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating subject: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{euid}", response_model=Dict[str, Any])
async def update_subject(
    euid: str,
    data: SubjectUpdateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Update a subject."""
    try:
        bdb = get_bdb(user.email)
        from sqlalchemy.orm.attributes import flag_modified

        subject = bdb.session.query(bdb.Base.classes.generic_instance).filter(
            bdb.Base.classes.generic_instance.euid == euid,
            bdb.Base.classes.generic_instance.category == "subject",
        ).first()

        if not subject:
            raise HTTPException(status_code=404, detail=f"Subject not found: {euid}")

        if data.name is not None:
            subject.name = data.name
        if data.status is not None:
            subject.bstatus = data.status
        if data.json_addl is not None:
            existing = subject.json_addl or {}
            existing.update(data.json_addl)
            subject.json_addl = existing
            flag_modified(subject, "json_addl")

        bdb.session.commit()

        return {
            "success": True,
            "euid": subject.euid,
            "message": "Subject updated successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating subject {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{euid}", response_model=Dict[str, Any])
async def delete_subject(
    euid: str,
    hard_delete: bool = Query(False, description="Permanently delete"),
    user: APIUser = Depends(require_api_auth),
):
    """Delete a subject (soft delete by default)."""
    try:
        bdb = get_bdb(user.email)

        subject = bdb.session.query(bdb.Base.classes.generic_instance).filter(
            bdb.Base.classes.generic_instance.euid == euid,
            bdb.Base.classes.generic_instance.category == "subject",
        ).first()

        if not subject:
            raise HTTPException(status_code=404, detail=f"Subject not found: {euid}")

        if hard_delete:
            bdb.session.delete(subject)
        else:
            subject.is_deleted = True

        bdb.session.commit()

        return {
            "success": True,
            "euid": euid,
            "message": f"Subject {'permanently deleted' if hard_delete else 'soft deleted'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting subject {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}/specimens", response_model=Dict[str, Any])
async def get_subject_specimens(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get all specimens associated with a subject."""
    try:
        bdb = get_bdb(user.email)

        subject = bdb.session.query(bdb.Base.classes.generic_instance).filter(
            bdb.Base.classes.generic_instance.euid == euid,
            bdb.Base.classes.generic_instance.category == "subject",
        ).first()

        if not subject:
            raise HTTPException(status_code=404, detail=f"Subject not found: {euid}")

        specimens = []
        for lineage in subject.parent_of_lineages:
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child.category == "content" and child.type in ["specimen", "sample"]:
                specimens.append({
                    "euid": child.euid,
                    "name": child.name,
                    "type": child.type,
                    "subtype": child.subtype,
                    "status": child.bstatus,
                })

        return {
            "subject_euid": euid,
            "specimens": specimens,
            "count": len(specimens),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting subject specimens {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

