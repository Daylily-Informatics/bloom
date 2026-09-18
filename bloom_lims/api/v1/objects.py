"""
BLOOM LIMS API v1 - Objects Endpoints

CRUD endpoints for BloomObj (generic instances).
"""

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from bloom_lims.api.v1.owner_contracts import (
    PropertyNamespaceWrite,
    canonical_sha256,
    exact_euid,
)

from bloom_lims.schemas import (
    ObjectCreateSchema,
    ObjectUpdateSchema,
)
from bloom_lims.template_identity import template_payload

from .dependencies import APIUser, require_read, require_write

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/objects", tags=["Objects"])


@router.patch("/{euid}/properties/{namespace}")
def add_property_namespace(
    data: PropertyNamespaceWrite,
    euid: str = Path(min_length=1, max_length=128),
    namespace: str = Path(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
    user: APIUser = Depends(require_write),
):
    """Add one immutable metadata namespace with a locked whole-JSON precondition."""
    try:
        exact_euid(euid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        from bloom_lims.tapdb_adapter import BLOOMdb3

        with BLOOMdb3(app_username=user.email) as bdb:
            with bdb.session.begin():
                model = bdb.Base.classes.generic_instance
                obj = bdb.session.query(model).filter(
                    model.euid == euid, model.is_deleted.is_(False)
                ).with_for_update().one_or_none()
                if obj is None:
                    raise HTTPException(status_code=404, detail="Live owner object not found")
                before = copy.deepcopy(obj.json_addl)
                if not isinstance(before, dict):
                    raise HTTPException(status_code=409, detail="Owner json_addl must be an object")
                properties = before.get("properties", {})
                if not isinstance(properties, dict):
                    raise HTTPException(status_code=409, detail="Owner properties must be an object")
                before_sha = canonical_sha256(before)
                value_sha = canonical_sha256(data.value)
                if namespace in properties:
                    if canonical_sha256(properties[namespace]) != value_sha:
                        raise HTTPException(status_code=409, detail="Property namespace already has different content")
                    outcome = "already_present"
                    after_sha = before_sha
                else:
                    if before_sha != data.expected_json_addl_sha256:
                        raise HTTPException(status_code=409, detail="Owner json_addl changed since the supplied precondition")
                    after = copy.deepcopy(before)
                    after.setdefault("properties", {})[namespace] = copy.deepcopy(data.value)
                    obj.json_addl = after
                    bdb.session.flush()
                    after_sha = canonical_sha256(obj.json_addl)
                    outcome = "created"
                payload = {
                    "schema": "bloom.property_namespace_write/1",
                    "euid": obj.euid,
                    "namespace": namespace,
                    "outcome": outcome,
                    "changed": outcome == "created",
                    "expected_json_addl_sha256": data.expected_json_addl_sha256,
                    "before_json_addl_sha256": before_sha,
                    "after_json_addl_sha256": after_sha,
                    "value_sha256": value_sha,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
            # The transaction has committed before any success is returned.
            payload["receipt_sha256"] = canonical_sha256(payload)
            return payload
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Conditional owner namespace write failed")
        raise HTTPException(status_code=500, detail="Conditional owner namespace write failed") from exc


def _is_singleton_template(template_row) -> bool:
    payload = template_payload(template_row)
    singleton_value = payload.get("singleton")
    return bool(getattr(template_row, "is_singleton", False)) or str(
        singleton_value
    ).strip().lower() in {"1", "true", "yes", "on"}


def _has_recursive_layout(template_row) -> bool:
    layouts = template_payload(template_row).get("instantiation_layouts")
    return bool(layouts)


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
        from bloom_lims.domain import BloomObj
        from bloom_lims.tapdb_adapter import BLOOMdb3

        bdb = BLOOMdb3()
        BloomObj(bdb)

        # Build query
        query = bdb.session.query(bdb.Base.classes.generic_instance)

        if type:
            query = query.filter(bdb.Base.classes.generic_instance.type == type.lower())
        if subtype:
            query = query.filter(
                bdb.Base.classes.generic_instance.subtype == subtype.lower()
            )
        if status:
            query = query.filter(bdb.Base.classes.generic_instance.bstatus == status)
        if name_contains:
            query = query.filter(
                bdb.Base.classes.generic_instance.name.ilike(f"%{name_contains}%")
            )

        # Filter out deleted
        query = query.filter(bdb.Base.classes.generic_instance.is_deleted.is_(False))

        # Get total count
        total = query.count()

        # Paginate
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()

        return {
            "items": [
                {
                    "euid": obj.euid,
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
        from bloom_lims.domain import BloomObj
        from bloom_lims.tapdb_adapter import BLOOMdb3

        bdb = BLOOMdb3()
        bo = BloomObj(bdb)

        obj = bo.get_by_euid(euid)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {euid}")

        return {
            "euid": obj.euid,
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
async def create_object(
    data: ObjectCreateSchema, user: APIUser = Depends(require_write)
):
    """
    Create a new object.
    """
    try:
        from bloom_lims.domain import BloomObj
        from bloom_lims.tapdb_adapter import BLOOMdb3

        bdb = BLOOMdb3(app_username=user.email)
        bo = BloomObj(bdb)
        bo.set_actor_context(user_id=user.user_id, email=user.email)

        # TapDB requires instances be created from templates (template_uid is required).
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
        if not templates:
            raise HTTPException(
                status_code=400,
                detail=f"No template found for {category}/{data.type}/{data.subtype or '*'}@{version}",
            )
        template = templates[0]
        if data.count > 1 and _is_singleton_template(template):
            raise HTTPException(
                status_code=400,
                detail="count > 1 is not allowed for singleton templates",
            )
        if data.count > 1 and _has_recursive_layout(template):
            raise HTTPException(
                status_code=400,
                detail=(
                    "count > 1 is not allowed for recursive templates; "
                    "create recursive containers one at a time"
                ),
            )

        created_objects = []
        for index in range(data.count):
            json_overrides = copy.deepcopy(data.json_addl or {})
            props = json_overrides.get("properties")
            if not isinstance(props, dict):
                props = {}
            props.setdefault(
                "name", f"{data.name} {index + 1}" if data.count > 1 else data.name
            )
            json_overrides["properties"] = props

            created = bo.create_instances(
                template.euid, json_addl_overrides=json_overrides
            )
            obj = created[0][0] if created and created[0] else None
            if obj is None:
                raise HTTPException(status_code=500, detail="Failed to create object")
            obj.name = props["name"]
            bdb.session.flush()
            bo.track_user_interaction(
                obj.euid,
                relationship_type="user_created",
                user_id=user.user_id,
                email=user.email,
            )
            created_objects.append(obj)

        bdb.session.commit()
        obj = created_objects[0]

        return {
            "success": True,
            "euid": obj.euid,
            "created_euids": [created.euid for created in created_objects],
            "message": "Object created successfully"
            if data.count == 1
            else f"{len(created_objects)} objects created successfully",
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
        from sqlalchemy.orm.attributes import flag_modified

        from bloom_lims.domain import BloomObj
        from bloom_lims.tapdb_adapter import BLOOMdb3

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
            raise HTTPException(
                status_code=403, detail="Admin privileges required for hard delete"
            )

        from bloom_lims.domain import BloomObj
        from bloom_lims.tapdb_adapter import BLOOMdb3

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
