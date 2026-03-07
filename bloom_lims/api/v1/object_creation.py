"""
BLOOM LIMS API v1 - Object Creation Wizard Endpoints

Endpoints to support the multi-step object creation workflow.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func

from bloom_lims.integrations.atlas.events import emit_bloom_event
from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/object-creation", tags=["Object Creation"])

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
    name: str
    category: str
    type: str
    subtype: str
    message: str


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


def _template_payload(template_row) -> Dict[str, Any]:
    """Return template json_addl as a dict."""
    payload = template_row.json_addl or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


@router.get("/categories")
async def list_categories(user: APIUser = Depends(require_api_auth)):
    """
    List all available categories from active TapDB templates.

    Step 1 of the object creation wizard.
    """
    try:
        bdb = get_bdb(user.email)
        template = bdb.Base.classes.generic_template
        rows = (
            bdb.session.query(
                template.category,
                func.count(func.distinct(template.type)).label("type_count"),
            )
            .filter(template.is_deleted == False)  # noqa: E712
            .group_by(template.category)
            .order_by(template.category)
            .all()
        )
        categories = [
            {
                "name": row.category,
                "display_name": row.category.replace("_", " ").title(),
                "type_count": int(row.type_count or 0),
            }
            for row in rows
            if row.category
        ]
        return {"categories": categories}
    except Exception as e:
        logger.error(f"Error listing categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/types")
async def list_types(
    category: str = Query(..., description="Template category"),
    user: APIUser = Depends(require_api_auth),
):
    """
    List all available types for a category from active TapDB templates.

    Step 2 of the object creation wizard.
    """
    # Validate path component to prevent path traversal
    validate_path_component(category, "category")

    try:
        bdb = get_bdb(user.email)
        template = bdb.Base.classes.generic_template
        rows = (
            bdb.session.query(
                template.type,
                func.count(func.distinct(template.subtype)).label("subtype_count"),
            )
            .filter(
                template.is_deleted == False,  # noqa: E712
                template.category == category,
            )
            .group_by(template.type)
            .order_by(template.type)
            .all()
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Category not found: {category}")
        types = [
            {
                "name": row.type,
                "display_name": row.type.replace("_", " ").replace("-", " ").title(),
                "subtype_count": int(row.subtype_count or 0),
            }
            for row in rows
            if row.type
        ]

        return {"category": category, "types": types}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing types for {category}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subtypes")
async def list_subtypes(
    category: str = Query(..., description="Template category"),
    type: str = Query(..., description="Template type"),
    user: APIUser = Depends(require_api_auth),
):
    """
    List all available subtypes and versions from active TapDB templates.

    Step 3 of the object creation wizard.
    """
    # Validate path components to prevent path traversal
    validate_path_component(category, "category")
    validate_path_component(type, "type")

    try:
        bdb = get_bdb(user.email)
        template = bdb.Base.classes.generic_template
        rows = (
            bdb.session.query(
                template.subtype,
                template.version,
                template.json_addl,
            )
            .filter(
                template.is_deleted == False,  # noqa: E712
                template.category == category,
                template.type == type,
            )
            .order_by(template.subtype, template.version)
            .all()
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Type not found: {category}/{type}")

        subtype_map: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            subtype_name = row.subtype
            if not subtype_name:
                continue
            payload = _template_payload(row)
            entry = subtype_map.setdefault(
                subtype_name,
                {
                    "name": subtype_name,
                    "display_name": subtype_name.replace("-", " ").replace("_", " ").title(),
                    "versions": [],
                    "description": "",
                },
            )
            if row.version:
                entry["versions"].append(row.version)
            if not entry["description"]:
                entry["description"] = payload.get("description", "") or ""

        subtypes = []
        for subtype_name in sorted(subtype_map.keys()):
            entry = subtype_map[subtype_name]
            entry["versions"] = sorted(set(entry["versions"]))
            subtypes.append(entry)

        return {"category": category, "type": type, "subtypes": subtypes}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing subtypes for {category}/{type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/template")
async def get_template_details(
    category: str = Query(..., description="Template category"),
    type: str = Query(..., description="Template type"),
    subtype: str = Query(..., description="Template subtype"),
    version: str = Query(..., description="Template version"),
    user: APIUser = Depends(require_api_auth),
):
    """
    Get full template details including properties for form generation.

    Step 4 of the object creation wizard - provides data for the creation form.
    """
    # Validate category/type path components for defense in depth.
    validate_path_component(category, "category")
    validate_path_component(type, "type")

    try:
        bdb = get_bdb(user.email)
        template = bdb.Base.classes.generic_template
        type_rows = (
            bdb.session.query(template.euid)
            .filter(
                template.is_deleted == False,  # noqa: E712
                template.category == category,
                template.type == type,
            )
            .limit(1)
            .all()
        )
        if not type_rows:
            raise HTTPException(status_code=404, detail=f"Type not found: {category}/{type}")
        subtype_rows = (
            bdb.session.query(template.euid)
            .filter(
                template.is_deleted == False,  # noqa: E712
                template.category == category,
                template.type == type,
                template.subtype == subtype,
            )
            .limit(1)
            .all()
        )
        if not subtype_rows:
            raise HTTPException(status_code=404, detail=f"Subtype not found: {subtype}")
        row = (
            bdb.session.query(template)
            .filter(
                template.is_deleted == False,  # noqa: E712
                template.category == category,
                template.type == type,
                template.subtype == subtype,
                template.version == version,
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"Version not found: {version}")

        template_data = _template_payload(row)

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
        bloom_obj.set_actor_context(user_id=user.user_id, email=user.email)

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
        bloom_obj.track_user_interaction(
            new_instance.euid,
            relationship_type="user_created",
            user_id=user.user_id,
            email=user.email,
        )

        if new_instance.category == "container":
            emit_bloom_event(
                "container.created",
                {
                    "euid": new_instance.euid,
                    "container_euid": new_instance.euid,
                    "name": new_instance.name,
                    "category": new_instance.category,
                    "type": new_instance.type,
                    "subtype": new_instance.subtype,
                    "status": new_instance.bstatus,
                    "json_addl": new_instance.json_addl if isinstance(new_instance.json_addl, dict) else {},
                    "is_deleted": bool(getattr(new_instance, "is_deleted", False)),
                },
            )

        return CreateObjectResponse(
            euid=new_instance.euid,
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
