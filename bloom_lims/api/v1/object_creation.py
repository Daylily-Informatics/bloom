"""
BLOOM LIMS API v1 - Object Creation Wizard Endpoints

Endpoints to support the multi-step object creation workflow.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/object-creation", tags=["Object Creation"])

# Path to config directory
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

# Regex pattern for valid path components: lowercase letters, numbers, underscores, hyphens
VALID_PATH_COMPONENT_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def validate_path_component(value: str, param_name: str) -> None:
    """
    Validate a path component to prevent path traversal attacks.

    Args:
        value: The path component to validate
        param_name: Name of the parameter (for error messages)

    Raises:
        HTTPException: If validation fails
    """
    # Check for path separators
    if "/" in value or "\\" in value:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name}: path separators not allowed"
        )

    # Check for parent directory references
    if ".." in value:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name}: parent directory references not allowed"
        )

    # Check against whitelist pattern
    if not VALID_PATH_COMPONENT_PATTERN.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name}: must contain only lowercase letters, numbers, underscores, and hyphens"
        )


def validate_path_within_config(resolved_path: Path) -> None:
    """
    Verify that a resolved path stays within CONFIG_DIR.

    Args:
        resolved_path: The resolved (normalized) path to check

    Raises:
        HTTPException: If path is outside CONFIG_DIR
    """
    config_dir_resolved = CONFIG_DIR.resolve()
    try:
        # Python 3.9+ method
        if not resolved_path.is_relative_to(config_dir_resolved):
            raise HTTPException(
                status_code=400,
                detail="Invalid path: access denied"
            )
    except AttributeError:
        # Fallback for Python < 3.9
        try:
            resolved_path.relative_to(config_dir_resolved)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid path: access denied"
            )


class CreateObjectRequest(BaseModel):
    """Request body for creating a new object."""
    category: str
    type: str
    subtype: str
    version: str
    name: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class CreateObjectResponse(BaseModel):
    """Response for object creation."""
    euid: str
    uuid: str
    name: str
    category: str
    type: str
    subtype: str
    message: str


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


@router.get("/categories")
async def list_categories(user: APIUser = Depends(require_api_auth)):
    """
    List all available categories (directories in config/).

    Step 1 of the object creation wizard.
    """
    try:
        categories = []
        for path in sorted(CONFIG_DIR.iterdir()):
            if path.is_dir() and not path.name.startswith((".", "_")):
                # Count JSON files in directory
                json_files = list(path.glob("*.json"))
                # Exclude metadata.json from count
                type_count = len([f for f in json_files if f.name != "metadata.json"])
                categories.append({
                    "name": path.name,
                    "display_name": path.name.replace("_", " ").title(),
                    "type_count": type_count,
                })
        return {"categories": categories}
    except Exception as e:
        logger.error(f"Error listing categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/types")
async def list_types(
    category: str = Query(..., description="Category directory name"),
    user: APIUser = Depends(require_api_auth),
):
    """
    List all available types (JSON files) for a category.

    Step 2 of the object creation wizard.
    """
    # Validate path component to prevent path traversal
    validate_path_component(category, "category")

    try:
        category_dir = CONFIG_DIR / category

        # Verify resolved path stays within CONFIG_DIR
        validate_path_within_config(category_dir.resolve())

        if not category_dir.exists() or not category_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Category not found: {category}")

        types = []
        for json_file in sorted(category_dir.glob("*.json")):
            if json_file.name == "metadata.json":
                continue  # Skip metadata files

            type_name = json_file.stem
            # Load file to count subtypes
            try:
                with open(json_file) as f:
                    data = json.load(f)
                    subtype_count = len(data)
            except Exception:
                subtype_count = 0

            types.append({
                "name": type_name,
                "display_name": type_name.replace("_", " ").replace("-", " ").title(),
                "subtype_count": subtype_count,
            })

        return {"category": category, "types": types}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing types for {category}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subtypes")
async def list_subtypes(
    category: str = Query(..., description="Category directory name"),
    type: str = Query(..., description="Type (JSON file name without extension)"),
    user: APIUser = Depends(require_api_auth),
):
    """
    List all available subtypes and versions from a type's JSON file.

    Step 3 of the object creation wizard.
    """
    # Validate path components to prevent path traversal
    validate_path_component(category, "category")
    validate_path_component(type, "type")

    try:
        json_file = CONFIG_DIR / category / f"{type}.json"

        # Verify resolved path stays within CONFIG_DIR
        validate_path_within_config(json_file.resolve())

        if not json_file.exists():
            raise HTTPException(status_code=404, detail=f"Type not found: {category}/{type}")

        with open(json_file) as f:
            data = json.load(f)

        subtypes = []
        for subtype_name, versions in data.items():
            version_list = list(versions.keys()) if isinstance(versions, dict) else []
            # Get description from first version if available
            description = ""
            if version_list and isinstance(versions.get(version_list[0]), dict):
                description = versions[version_list[0]].get("description", "")

            subtypes.append({
                "name": subtype_name,
                "display_name": subtype_name.replace("-", " ").replace("_", " ").title(),
                "versions": version_list,
                "description": description,
            })

        return {"category": category, "type": type, "subtypes": subtypes}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing subtypes for {category}/{type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/template")
async def get_template_details(
    category: str = Query(..., description="Category directory name"),
    type: str = Query(..., description="Type (JSON file name without extension)"),
    subtype: str = Query(..., description="Subtype key in JSON"),
    version: str = Query(..., description="Version key"),
    user: APIUser = Depends(require_api_auth),
):
    """
    Get full template details including properties for form generation.

    Step 4 of the object creation wizard - provides data for the creation form.
    """
    # Validate path components to prevent path traversal
    # Note: subtype and version are JSON keys, not filesystem paths,
    # but we validate them anyway for defense in depth
    validate_path_component(category, "category")
    validate_path_component(type, "type")

    try:
        json_file = CONFIG_DIR / category / f"{type}.json"

        # Verify resolved path stays within CONFIG_DIR
        validate_path_within_config(json_file.resolve())

        if not json_file.exists():
            raise HTTPException(status_code=404, detail=f"Type not found: {category}/{type}")

        with open(json_file) as f:
            data = json.load(f)

        if subtype not in data:
            raise HTTPException(status_code=404, detail=f"Subtype not found: {subtype}")

        versions = data[subtype]
        if version not in versions:
            raise HTTPException(status_code=404, detail=f"Version not found: {version}")

        template_data = versions[version]

        return {
            "category": category,
            "type": type,
            "subtype": subtype,
            "version": version,
            "template": template_data,
            "properties": template_data.get("properties", {}),
            "description": template_data.get("description", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template {category}/{type}/{subtype}/{version}: {e}")
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
            request.category,
            request.type,
            request.subtype,
            request.version
        )

        if not templates:
            raise HTTPException(
                status_code=404,
                detail=f"Template not found: {request.category}/{request.type}/{request.subtype}/{request.version}"
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
            category=new_instance.category,
            type=new_instance.type,
            subtype=new_instance.subtype,
            message=f"Successfully created {new_instance.euid}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating object: {e}")
        raise HTTPException(status_code=500, detail=str(e))

