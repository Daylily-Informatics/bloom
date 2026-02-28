"""
BLOOM LIMS API v1 - Biospecimen Endpoints

CRUD endpoints for biospecimen management.
Biospecimens are content objects created from specimen.json templates
via the generic BloomContent domain class.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.schemas import (
    BioSpecimenCreate,
    BioSpecimenStatusUpdate,
    BioSpecimenResponse,
)
from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/biospecimen", tags=["Biospecimen"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


@router.post("/", response_model=Dict[str, Any], status_code=201)
async def create_biospecimen(
    data: BioSpecimenCreate,
    user: APIUser = Depends(require_api_auth),
):
    """Create a new biospecimen from a specimen template.

    Resolves the template by specimen_subtype (e.g. 'blood-whole'),
    creates an instance via BloomContent, then applies property overrides.
    """
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)

        # Resolve template: content / specimen / {subtype} / 1.0
        templates = bc.query_template_by_component_v2(
            "content", "specimen", data.specimen_subtype, "1.0"
        )
        if not templates:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown specimen subtype: {data.specimen_subtype}. "
                "Ensure the database is seeded with specimen templates.",
            )

        result = bc.create_empty_content(templates[0].euid)
        instance = result[0][0] if isinstance(result, list) else result

        # Apply property overrides from the request
        props = instance.json_addl.get("properties", {})
        override_fields = [
            "specimen_barcode", "collection_date", "condition",
            "volume", "volume_units", "atlas_patient_euid",
            "atlas_order_euid", "comments", "lab_code",
        ]
        for field in override_fields:
            val = getattr(data, field, None)
            if val is not None:
                props[field] = val.isoformat() if isinstance(val, datetime) else val

        # Initialise status history
        now = datetime.now(timezone.utc).isoformat()
        props.setdefault("status", "REGISTERED")
        props["status_history"] = [
            {"status": "REGISTERED", "changed_at": now, "changed_by": user.email}
        ]
        instance.json_addl["properties"] = props
        flag_modified(instance, "json_addl")
        bdb.session.commit()

        return {
            "success": True,
            "euid": instance.euid,
            "uuid": str(instance.uuid),
            "specimen_type": instance.subtype,
            "status": "REGISTERED",
            "registered_at": str(instance.created_dt),
            "message": "Biospecimen created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating biospecimen: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=Dict[str, Any])
async def list_biospecimens(
    status: Optional[str] = Query(None, description="Filter by lifecycle status"),
    specimen_type: Optional[str] = Query(None, description="Filter by specimen subtype"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    """List biospecimen instances with optional filters."""
    try:
        bdb = get_bdb(user.email)
        gi = bdb.Base.classes.generic_instance

        query = bdb.session.query(gi).filter(
            gi.category == "content",
            gi.type == "specimen",
            gi.is_deleted == False,
        )
        if specimen_type:
            query = query.filter(gi.subtype == specimen_type.lower())

        # Fetch all matching, then filter by json_addl status in Python
        # (JSONB filtering varies by driver; keep it simple like other endpoints)
        all_items = query.order_by(gi.created_dt.desc()).all()

        if status:
            all_items = [
                obj for obj in all_items
                if (obj.json_addl or {}).get("properties", {}).get("status") == status.upper()
            ]

        total = len(all_items)
        offset = (page - 1) * page_size
        items = all_items[offset : offset + page_size]

        return {
            "items": [
                BioSpecimenResponse.from_instance(obj).model_dump(mode="json")
                for obj in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing biospecimens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}", response_model=Dict[str, Any])
async def get_biospecimen(euid: str, user: APIUser = Depends(require_api_auth)):
    """Get a biospecimen by EUID."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)
        instance = bc.get_by_euid(euid)

        if not instance:
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")

        # Verify it is actually a specimen
        if getattr(instance, "type", None) != "specimen":
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")

        return BioSpecimenResponse.from_instance(instance).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error getting biospecimen {euid}: {error_msg}")
        if "not found" in error_msg.lower() or "no template found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/barcode/{barcode}", response_model=Dict[str, Any])
async def get_biospecimen_by_barcode(
    barcode: str,
    user: APIUser = Depends(require_api_auth),
):
    """Look up a biospecimen by its specimen_barcode in json_addl."""
    try:
        bdb = get_bdb(user.email)
        gi = bdb.Base.classes.generic_instance

        # Query all specimen instances and filter by barcode in json_addl
        specimens = (
            bdb.session.query(gi)
            .filter(
                gi.category == "content",
                gi.type == "specimen",
                gi.is_deleted == False,
            )
            .all()
        )

        for obj in specimens:
            props = (obj.json_addl or {}).get("properties", {})
            if props.get("specimen_barcode") == barcode:
                resp = BioSpecimenResponse.from_instance(obj).model_dump(mode="json")
                resp["barcode"] = barcode
                return resp

        raise HTTPException(
            status_code=404,
            detail=f"No biospecimen found for barcode: {barcode}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error looking up barcode {barcode}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{euid}/status", response_model=Dict[str, Any])
async def update_biospecimen_status(
    euid: str,
    data: BioSpecimenStatusUpdate,
    user: APIUser = Depends(require_api_auth),
):
    """Update the lifecycle status of a biospecimen.

    Appends to the status_history array in json_addl.
    """
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)
        instance = bc.get_by_euid(euid)

        if not instance:
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")
        if getattr(instance, "type", None) != "specimen":
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")

        props = instance.json_addl.get("properties", {})
        old_status = props.get("status", "REGISTERED")
        new_status = data.status.value

        # Update status
        props["status"] = new_status

        # Append to history
        now = datetime.now(timezone.utc).isoformat()
        history = props.get("status_history", [])
        history.append({
            "status": new_status,
            "changed_at": now,
            "changed_by": user.email,
        })
        props["status_history"] = history

        instance.json_addl["properties"] = props
        flag_modified(instance, "json_addl")
        bdb.session.commit()

        return {
            "success": True,
            "euid": euid,
            "old_status": old_status,
            "new_status": new_status,
            "message": f"Status updated from {old_status} to {new_status}",
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error updating biospecimen status {euid}: {error_msg}")
        if "not found" in error_msg.lower() or "no template found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/{euid}/history", response_model=Dict[str, Any])
async def get_biospecimen_history(
    euid: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: APIUser = Depends(require_api_auth),
):
    """Get the status history for a biospecimen (newest first)."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent

        bc = BloomContent(bdb)
        instance = bc.get_by_euid(euid)

        if not instance:
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")
        if getattr(instance, "type", None) != "specimen":
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")

        props = (instance.json_addl or {}).get("properties", {})
        history = props.get("status_history", [])

        # Newest first
        history_sorted = list(reversed(history))
        total = len(history_sorted)
        page = history_sorted[offset : offset + limit]

        return {
            "euid": euid,
            "history": page,
            "total": total,
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error getting biospecimen history {euid}: {error_msg}")
        if "not found" in error_msg.lower() or "no template found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=f"Biospecimen not found: {euid}")
        raise HTTPException(status_code=500, detail=error_msg)

