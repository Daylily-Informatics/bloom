"""
BLOOM LIMS API v1 - Files Endpoints

Endpoints for file management and S3 operations.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form

from bloom_lims.schemas import (
    FileUploadSchema,
    FileResponseSchema,
    FileSetCreateSchema,
    FileSetResponseSchema,
    FileSearchSchema,
    PaginatedResponse,
    SuccessResponse,
)
from bloom_lims.exceptions import NotFoundError, ValidationError


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])


def get_bdb():
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3()


@router.get("/", response_model=Dict[str, Any])
async def list_files(
    file_type: Optional[str] = Query(None, description="Filter by file type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    """List files with optional filters."""
    try:
        bdb = get_bdb()
        
        query = bdb.session.query(bdb.Base.classes.generic_instance)
        query = query.filter(bdb.Base.classes.generic_instance.super_type == "file")
        
        if file_type:
            query = query.filter(bdb.Base.classes.generic_instance.btype == file_type.lower())
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
                    "file_type": obj.btype,
                    "status": obj.bstatus,
                    "s3_uri": obj.json_addl.get("properties", {}).get("s3_uri") if obj.json_addl else None,
                }
                for obj in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_file(euid: str):
    """Get file metadata by EUID."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomFile
        
        bf = BloomFile(bdb)
        file_obj = bf.get_by_euid(euid)
        
        if not file_obj:
            raise HTTPException(status_code=404, detail=f"File not found: {euid}")
        
        props = file_obj.json_addl.get("properties", {}) if file_obj.json_addl else {}
        
        return {
            "euid": file_obj.euid,
            "uuid": str(file_obj.uuid),
            "name": file_obj.name,
            "file_type": file_obj.btype,
            "status": file_obj.bstatus,
            "s3_uri": props.get("s3_uri"),
            "s3_bucket": props.get("current_s3_bucket_name"),
            "file_size": props.get("file_size"),
            "content_type": props.get("content_type"),
            "json_addl": file_obj.json_addl,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Dict[str, Any])
async def create_file(
    file_metadata: str = Form(..., description="JSON metadata for the file"),
    file: Optional[UploadFile] = File(None, description="File to upload"),
    s3_uri: Optional[str] = Form(None, description="S3 URI for existing file"),
):
    """Create a new file record, optionally uploading data."""
    try:
        import json
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomFile
        
        bf = BloomFile(bdb)
        metadata = json.loads(file_metadata)
        
        file_data = None
        file_name = None
        if file:
            file_data = await file.read()
            file_name = file.filename
        
        new_file = bf.create_file(
            file_metadata=metadata,
            file_data=file_data,
            file_name=file_name,
            s3_uri=s3_uri,
        )
        
        return {
            "success": True,
            "euid": new_file.euid,
            "uuid": str(new_file.uuid),
            "message": "File created successfully",
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in file_metadata")
    except Exception as e:
        logger.error(f"Error creating file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{file_euid}/link/{parent_euid}")
async def link_file_to_parent(file_euid: str, parent_euid: str):
    """Link a file to a parent object."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomFile
        
        bf = BloomFile(bdb)
        bf.link_file_to_parent(file_euid, parent_euid)
        
        return {"success": True, "message": "File linked to parent"}
    except Exception as e:
        logger.error(f"Error linking file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

