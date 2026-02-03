"""
BLOOM LIMS API v1 - Object Creation Wizard Endpoints

Endpoints to support the multi-step object creation workflow.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/object-creation", tags=["Object Creation"])

# Path to config directory
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


class CreateObjectRequest(BaseModel):
    """Request body for creating a new object."""
    super_type: str
    btype: str
    b_sub_type: str
    version: str
    name: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class CreateObjectResponse(BaseModel):
    """Response for object creation."""
    euid: str
    uuid: str
    name: str
    super_type: str
    btype: str
    b_sub_type: str
    message: str


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


@router.get("/super-types")
async def list_super_types(user: APIUser = Depends(require_api_auth)):
    """
    List all available super types (directories in config/).
    
    Step 1 of the object creation wizard.
    """
    try:
        super_types = []
        for path in sorted(CONFIG_DIR.iterdir()):
            if path.is_dir() and not path.name.startswith((".", "_")):
                # Count JSON files in directory
                json_files = list(path.glob("*.json"))
                # Exclude metadata.json from count
                type_count = len([f for f in json_files if f.name != "metadata.json"])
                super_types.append({
                    "name": path.name,
                    "display_name": path.name.replace("_", " ").title(),
                    "type_count": type_count,
                })
        return {"super_types": super_types}
    except Exception as e:
        logger.error(f"Error listing super types: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/types")
async def list_types(
    super_type: str = Query(..., description="Super type directory name"),
    user: APIUser = Depends(require_api_auth),
):
    """
    List all available types (JSON files) for a super type.
    
    Step 2 of the object creation wizard.
    """
    try:
        super_type_dir = CONFIG_DIR / super_type
        if not super_type_dir.exists() or not super_type_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Super type not found: {super_type}")
        
        types = []
        for json_file in sorted(super_type_dir.glob("*.json")):
            if json_file.name == "metadata.json":
                continue  # Skip metadata files
            
            type_name = json_file.stem
            # Load file to count sub-types
            try:
                with open(json_file) as f:
                    data = json.load(f)
                    sub_type_count = len(data)
            except Exception:
                sub_type_count = 0
            
            types.append({
                "name": type_name,
                "display_name": type_name.replace("_", " ").replace("-", " ").title(),
                "sub_type_count": sub_type_count,
            })
        
        return {"super_type": super_type, "types": types}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing types for {super_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sub-types")
async def list_sub_types(
    super_type: str = Query(..., description="Super type directory name"),
    btype: str = Query(..., description="Type (JSON file name without extension)"),
    user: APIUser = Depends(require_api_auth),
):
    """
    List all available sub-types and versions from a type's JSON file.
    
    Step 3 of the object creation wizard.
    """
    try:
        json_file = CONFIG_DIR / super_type / f"{btype}.json"
        if not json_file.exists():
            raise HTTPException(status_code=404, detail=f"Type not found: {super_type}/{btype}")
        
        with open(json_file) as f:
            data = json.load(f)
        
        sub_types = []
        for sub_type_name, versions in data.items():
            version_list = list(versions.keys()) if isinstance(versions, dict) else []
            # Get description from first version if available
            description = ""
            if version_list and isinstance(versions.get(version_list[0]), dict):
                description = versions[version_list[0]].get("description", "")
            
            sub_types.append({
                "name": sub_type_name,
                "display_name": sub_type_name.replace("-", " ").replace("_", " ").title(),
                "versions": version_list,
                "description": description,
            })
        
        return {"super_type": super_type, "btype": btype, "sub_types": sub_types}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing sub-types for {super_type}/{btype}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/template")
async def get_template_details(
    super_type: str = Query(..., description="Super type directory name"),
    btype: str = Query(..., description="Type (JSON file name without extension)"),
    b_sub_type: str = Query(..., description="Sub-type key in JSON"),
    version: str = Query(..., description="Version key"),
    user: APIUser = Depends(require_api_auth),
):
    """
    Get full template details including properties for form generation.

    Step 4 of the object creation wizard - provides data for the creation form.
    """
    try:
        json_file = CONFIG_DIR / super_type / f"{btype}.json"
        if not json_file.exists():
            raise HTTPException(status_code=404, detail=f"Type not found: {super_type}/{btype}")

        with open(json_file) as f:
            data = json.load(f)

        if b_sub_type not in data:
            raise HTTPException(status_code=404, detail=f"Sub-type not found: {b_sub_type}")

        versions = data[b_sub_type]
        if version not in versions:
            raise HTTPException(status_code=404, detail=f"Version not found: {version}")

        template_data = versions[version]

        return {
            "super_type": super_type,
            "btype": btype,
            "b_sub_type": b_sub_type,
            "version": version,
            "template": template_data,
            "properties": template_data.get("properties", {}),
            "description": template_data.get("description", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template {super_type}/{btype}/{b_sub_type}/{version}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create", response_model=CreateObjectResponse)
async def create_object(
    request: CreateObjectRequest,
    user: APIUser = Depends(require_api_auth),
):
    """
    Create a new object instance from template selection.

    Final step of the object creation wizard.
    """
    try:
        bdb = get_bdb(user.email)

        # Find the template in the database using the quad components
        from bloom_lims.domain.base import BloomObj

        bloom_obj = BloomObj(bdb)

        # Query for the template using components
        templates = bloom_obj.query_template_by_component_v2(
            request.super_type,
            request.btype,
            request.b_sub_type,
            request.version
        )

        if not templates:
            raise HTTPException(
                status_code=404,
                detail=f"Template not found: {request.super_type}/{request.btype}/{request.b_sub_type}/{request.version}"
            )

        template = templates[0]

        # Prepare json_addl overrides
        json_addl_overrides = {}
        if request.properties:
            json_addl_overrides["properties"] = request.properties
        if request.name:
            json_addl_overrides["properties"] = json_addl_overrides.get("properties", {})
            json_addl_overrides["properties"]["name"] = request.name

        # Create instance from template using the create_instance method
        new_instance = bloom_obj.create_instance(
            template.euid,
            json_addl_overrides=json_addl_overrides
        )

        if not new_instance:
            raise HTTPException(
                status_code=500,
                detail="Failed to create object instance"
            )

        bdb.session.commit()

        return CreateObjectResponse(
            euid=new_instance.euid,
            uuid=str(new_instance.uuid),
            name=new_instance.name or "",
            super_type=new_instance.super_type,
            btype=new_instance.btype,
            b_sub_type=new_instance.b_sub_type,
            message=f"Successfully created {new_instance.euid}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating object: {e}")
        raise HTTPException(status_code=500, detail=str(e))

