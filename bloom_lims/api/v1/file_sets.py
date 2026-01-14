"""
BLOOM LIMS API v1 - File Sets Endpoints

Endpoints for file set management.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/file-sets", tags=["File Sets"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


class FileSetCreateSchema(BaseModel):
    """Schema for creating a file set."""
    name: str = Field(..., description="File set name")
    parent_euid: Optional[str] = Field(None, description="Parent object EUID to associate with")
    file_type: Optional[str] = Field(None, description="Type of files in set")
    json_addl: Optional[Dict[str, Any]] = Field(None, description="Additional properties")


class FileSetUpdateSchema(BaseModel):
    """Schema for updating a file set."""
    name: Optional[str] = Field(None, description="File set name")
    status: Optional[str] = Field(None, description="File set status")
    json_addl: Optional[Dict[str, Any]] = Field(None, description="Additional properties")


@router.get("/", response_model=Dict[str, Any])
async def list_file_sets(
    parent_euid: Optional[str] = Query(None, description="Filter by parent EUID"),
    file_type: Optional[str] = Query(None, description="Filter by file type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List file sets with optional filters."""
    try:
        bdb = get_bdb(user.email)
        
        query = bdb.session.query(bdb.Base.classes.generic_instance)
        query = query.filter(bdb.Base.classes.generic_instance.btype == "file_set")
        query = query.filter(bdb.Base.classes.generic_instance.is_deleted == False)
        
        if file_type:
            query = query.filter(bdb.Base.classes.generic_instance.b_sub_type == file_type.lower())
        
        total = query.count()
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()
        
        return {
            "items": [
                {
                    "euid": fs.euid,
                    "uuid": str(fs.uuid),
                    "name": fs.name,
                    "file_type": fs.b_sub_type,
                    "status": fs.bstatus,
                }
                for fs in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing file sets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_file_set(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get a file set by EUID."""
    try:
        bdb = get_bdb(user.email)
        
        file_set = bdb.session.query(bdb.Base.classes.generic_instance).filter(
            bdb.Base.classes.generic_instance.euid == euid,
            bdb.Base.classes.generic_instance.btype == "file_set",
        ).first()
        
        if not file_set:
            raise HTTPException(status_code=404, detail=f"File set not found: {euid}")
        
        # Get files in set
        files = []
        for lineage in file_set.parent_of_lineages:
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child.btype == "file":
                files.append({
                    "euid": child.euid,
                    "name": child.name,
                    "path": child.json_addl.get("path") if child.json_addl else None,
                })
        
        return {
            "euid": file_set.euid,
            "uuid": str(file_set.uuid),
            "name": file_set.name,
            "file_type": file_set.b_sub_type,
            "status": file_set.bstatus,
            "json_addl": file_set.json_addl,
            "files": files,
            "file_count": len(files),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file set {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Dict[str, Any])
async def create_file_set(
    data: FileSetCreateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Create a new file set."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomObj
        from sqlalchemy.orm.attributes import flag_modified
        import uuid as uuid_lib
        
        # Create file set instance directly
        GenericInstance = bdb.Base.classes.generic_instance
        file_set = GenericInstance(
            uuid=uuid_lib.uuid4(),
            name=data.name,
            super_type="data",
            btype="file_set",
            b_sub_type=data.file_type or "generic",
            bstatus="created",
            json_addl=data.json_addl or {},
        )
        bdb.session.add(file_set)
        bdb.session.flush()
        
        # Link to parent if provided
        if data.parent_euid:
            bo = BloomObj(bdb)
            parent = bo.get_by_euid(data.parent_euid)
            if parent:
                bo.create_lineage(parent, file_set)
        
        bdb.session.commit()
        
        return {
            "success": True,
            "euid": file_set.euid,
            "uuid": str(file_set.uuid),
            "message": "File set created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating file set: {e}")
        raise HTTPException(status_code=500, detail=str(e))

