"""
BLOOM LIMS API v1 - Containers Endpoints

CRUD endpoints for container management (plates, racks, boxes, etc.).
"""

import csv
import io
import json as json_lib
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

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
from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/containers", tags=["Containers"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


@router.get("/", response_model=Dict[str, Any])
async def list_containers(
    container_type: Optional[str] = Query(None, description="Filter by type (plate, rack, box)"),
    subtype: Optional[str] = Query(None, description="Filter by subtype"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List containers with optional filters."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContainer

        bc = BloomContainer(bdb)
        query = bdb.session.query(bdb.Base.classes.generic_instance)
        query = query.filter(bdb.Base.classes.generic_instance.category == "container")

        if container_type:
            query = query.filter(bdb.Base.classes.generic_instance.type == container_type.lower())
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
                    "container_type": obj.type,
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
        logger.error(f"Error listing containers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_container(
    euid: str,
    include_contents: bool = Query(False),
    user: APIUser = Depends(require_api_auth),
):
    """Get a container by EUID, optionally including contents."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContainer
        
        bc = BloomContainer(bdb)
        container = bc.get_by_euid(euid)
        
        if not container:
            raise HTTPException(status_code=404, detail=f"Container not found: {euid}")
        
        result = {
            "euid": container.euid,
            "uuid": str(container.uuid),
            "name": container.name,
            "container_type": container.type,
            "subtype": container.subtype,
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
                    "type": child.type,
                    "position": child.json_addl.get("cont_address") if child.json_addl else None,
                })
            result["contents"] = contents
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error getting container {euid}: {error_msg}")
        # Check for "not found" type errors and return 404
        if "not found" in error_msg.lower() or "no template found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=f"Container not found: {euid}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/", response_model=Dict[str, Any])
async def create_container(
    data: ContainerCreateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Create a new container from a template."""
    try:
        bdb = get_bdb(user.email)
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


@router.put("/{euid}", response_model=Dict[str, Any])
async def update_container(
    euid: str,
    data: ContainerUpdateSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Update a container."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContainer
        from sqlalchemy.orm.attributes import flag_modified

        bc = BloomContainer(bdb)
        container = bc.get_by_euid(euid)

        if not container:
            raise HTTPException(status_code=404, detail=f"Container not found: {euid}")

        if data.name is not None:
            container.name = data.name
        if data.status is not None:
            container.bstatus = data.status
        if data.json_addl is not None:
            existing = container.json_addl or {}
            existing.update(data.json_addl)
            container.json_addl = existing
            flag_modified(container, "json_addl")

        bdb.session.commit()

        return {
            "success": True,
            "euid": container.euid,
            "message": "Container updated successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating container {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{euid}", response_model=Dict[str, Any])
async def delete_container(
    euid: str,
    hard_delete: bool = Query(False, description="Permanently delete"),
    user: APIUser = Depends(require_api_auth),
):
    """Delete a container (soft delete by default)."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContainer

        bc = BloomContainer(bdb)
        container = bc.get_by_euid(euid)

        if not container:
            raise HTTPException(status_code=404, detail=f"Container not found: {euid}")

        if hard_delete:
            bc.delete_obj(container)
        else:
            container.is_deleted = True
            bdb.session.commit()

        return {
            "success": True,
            "euid": euid,
            "message": f"Container {'permanently deleted' if hard_delete else 'soft deleted'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting container {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{container_euid}/contents")
async def add_content_to_container(
    container_euid: str,
    data: PlaceInContainerSchema,
    user: APIUser = Depends(require_api_auth),
):
    """Add content to a container."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContainer

        bc = BloomContainer(bdb)
        bc.link_content(container_euid, data.content_euid)

        return {"success": True, "message": "Content added to container"}
    except Exception as e:
        logger.error(f"Error adding content to container: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{container_euid}/contents/{content_euid}", response_model=Dict[str, Any])
async def remove_content_from_container(
    container_euid: str,
    content_euid: str,
    user: APIUser = Depends(require_api_auth),
):
    """Remove content from a container."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContainer

        bc = BloomContainer(bdb)
        container = bc.get_by_euid(container_euid)

        if not container:
            raise HTTPException(status_code=404, detail=f"Container not found: {container_euid}")

        # Find and remove the lineage
        for lineage in container.parent_of_lineages:
            if lineage.child_instance.euid == content_euid and not lineage.is_deleted:
                lineage.is_deleted = True
                bdb.session.commit()
                return {"success": True, "message": "Content removed from container"}

        raise HTTPException(status_code=404, detail=f"Content {content_euid} not found in container")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing content from container: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}/layout", response_model=Dict[str, Any])
async def get_container_layout(
    euid: str,
    user: APIUser = Depends(require_api_auth),
):
    """Get the layout/wells of a container (for plates)."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContainer

        bc = BloomContainer(bdb)
        container = bc.get_by_euid(euid)

        if not container:
            raise HTTPException(status_code=404, detail=f"Container not found: {euid}")

        layout = {}
        for lineage in container.parent_of_lineages:
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child.type == "well":
                addr = child.json_addl.get("cont_address", {}) if child.json_addl else {}
                position = addr.get("name", child.name)
                layout[position] = {
                    "euid": child.euid,
                    "name": child.name,
                    "status": child.bstatus,
                    "contents": [],
                }
                # Get well contents
                for well_lineage in child.parent_of_lineages:
                    if well_lineage.is_deleted:
                        continue
                    content = well_lineage.child_instance
                    if content.category == "content":
                        layout[position]["contents"].append({
                            "euid": content.euid,
                            "name": content.name,
                            "type": content.type,
                        })

        return {
            "container_euid": euid,
            "container_type": container.type,
            "layout": layout,
            "well_count": len(layout),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting container layout {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk-create", response_model=Dict[str, Any])
async def bulk_create_containers(
    file: UploadFile = File(..., description="TSV file with container/content data"),
    user: APIUser = Depends(require_api_auth),
):
    """
    Bulk create containers with content from a TSV file.

    TSV columns:
    - container_template_euid OR container_type (e.g., "tube:tube-generic-10ml:1.0")
    - container_name (optional)
    - content_template_euid OR content_type (e.g., "sample:sample-blood:1.0")
    - content_name (optional)
    - content_properties (optional, JSON string for json_addl overrides)
    """
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomObj

        bobj = BloomObj(bdb)

        # Read and parse TSV
        contents = await file.read()
        text = contents.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")

        results = {"created": [], "errors": [], "total_rows": 0}

        for row_num, row in enumerate(reader, start=2):
            results["total_rows"] += 1
            try:
                # Get container template
                cx_euid = row.get("container_template_euid", "").strip()
                cx_type = row.get("container_type", "").strip()

                if cx_euid:
                    cx_template = bobj.get_by_euid(cx_euid)
                    if not cx_template:
                        raise ValueError(f"Container template not found: {cx_euid}")
                elif cx_type:
                    # Parse type string: "type:subtype:version" or "type:subtype"
                    parts = cx_type.split(":")
                    if len(parts) < 2:
                        raise ValueError(f"Invalid container_type format: {cx_type}")
                    type_val, subtype_val = parts[0], parts[1]
                    version = parts[2] if len(parts) > 2 else "1.0"
                    templates = bobj.query_template_by_component_v2(
                        "container", type_val, subtype_val, version
                    )
                    if not templates:
                        raise ValueError(f"No container template found: {cx_type}")
                    cx_template = templates[0]
                else:
                    raise ValueError("container_template_euid or container_type required")

                # Get content template
                mx_euid = row.get("content_template_euid", "").strip()
                mx_type = row.get("content_type", "").strip()

                mx_template = None
                if mx_euid:
                    mx_template = bobj.get_by_euid(mx_euid)
                    if not mx_template:
                        raise ValueError(f"Content template not found: {mx_euid}")
                elif mx_type:
                    parts = mx_type.split(":")
                    if len(parts) < 2:
                        raise ValueError(f"Invalid content_type format: {mx_type}")
                    type_val, subtype_val = parts[0], parts[1]
                    version = parts[2] if len(parts) > 2 else "1.0"
                    templates = bobj.query_template_by_component_v2(
                        "content", type_val, subtype_val, version
                    )
                    if not templates:
                        raise ValueError(f"No content template found: {mx_type}")
                    mx_template = templates[0]

                # Create container
                container_result = bobj.create_instances(cx_template.euid)
                container = container_result[0][0] if isinstance(container_result, list) else container_result

                # Set container name if provided
                cx_name = row.get("container_name", "").strip()
                if cx_name:
                    container.name = cx_name
                    from sqlalchemy.orm.attributes import flag_modified
                    if container.json_addl and "properties" in container.json_addl:
                        container.json_addl["properties"]["name"] = cx_name
                        flag_modified(container, "json_addl")

                content = None
                if mx_template:
                    # Parse content properties
                    props_str = row.get("content_properties", "").strip()
                    json_overrides = {}
                    if props_str:
                        try:
                            json_overrides = json_lib.loads(props_str)
                        except json_lib.JSONDecodeError:
                            raise ValueError(f"Invalid JSON in content_properties: {props_str}")

                    # Create content
                    content = bobj.create_instance(mx_template.euid, json_overrides)

                    # Set content name if provided
                    mx_name = row.get("content_name", "").strip()
                    if mx_name:
                        content.name = mx_name
                        if content.json_addl and "properties" in content.json_addl:
                            content.json_addl["properties"]["name"] = mx_name
                            flag_modified(content, "json_addl")

                    # Link content to container
                    from bloom_lims.bobjs import BloomContainer
                    bc = BloomContainer(bdb)
                    bc.link_content(container.euid, content.euid)

                bdb.session.commit()

                results["created"].append({
                    "row": row_num,
                    "container_euid": container.euid,
                    "content_euid": content.euid if content else None,
                })

            except Exception as e:
                results["errors"].append({
                    "row": row_num,
                    "error": str(e),
                })

        return {
            "success": True,
            "total_rows": results["total_rows"],
            "created_count": len(results["created"]),
            "error_count": len(results["errors"]),
            "created": results["created"],
            "errors": results["errors"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk container creation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

