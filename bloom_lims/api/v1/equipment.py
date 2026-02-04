"""
BLOOM LIMS API v1 - Equipment Endpoints

Endpoints for equipment management, maintenance, and calibration tracking.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from bloom_lims.schemas import (
    EquipmentCreateSchema,
    EquipmentUpdateSchema,
    EquipmentResponseSchema,
    MaintenanceRecordSchema,
    CalibrationRecordSchema,
    EquipmentSearchSchema,
    PaginatedResponse,
    SuccessResponse,
)
from bloom_lims.exceptions import NotFoundError, ValidationError


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/equipment", tags=["Equipment"])


def get_bdb():
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3()


@router.get("/", response_model=Dict[str, Any])
async def list_equipment(
    equipment_type: Optional[str] = Query(None, description="Filter by type"),
    manufacturer: Optional[str] = Query(None, description="Filter by manufacturer"),
    operational_status: Optional[str] = Query(None, description="Filter by status"),
    location: Optional[str] = Query(None, description="Filter by location"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    """List equipment with optional filters."""
    try:
        bdb = get_bdb()

        query = bdb.session.query(bdb.Base.classes.generic_instance)
        query = query.filter(bdb.Base.classes.generic_instance.category == "equipment")

        if equipment_type:
            query = query.filter(bdb.Base.classes.generic_instance.type == equipment_type.lower())
        if operational_status:
            query = query.filter(bdb.Base.classes.generic_instance.bstatus == operational_status)

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
                    "equipment_type": obj.type,
                    "subtype": obj.subtype,
                    "status": obj.bstatus,
                    "location": obj.json_addl.get("properties", {}).get("location") if obj.json_addl else None,
                }
                for obj in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing equipment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{euid}")
async def get_equipment(euid: str):
    """Get equipment by EUID."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomEquipment

        be = BloomEquipment(bdb)
        equipment = be.get_by_euid(euid)

        if not equipment:
            raise HTTPException(status_code=404, detail=f"Equipment not found: {euid}")

        props = equipment.json_addl.get("properties", {}) if equipment.json_addl else {}

        return {
            "euid": equipment.euid,
            "uuid": str(equipment.uuid),
            "name": equipment.name,
            "equipment_type": equipment.type,
            "subtype": equipment.subtype,
            "status": equipment.bstatus,
            "serial_number": props.get("serial_number"),
            "model": props.get("model"),
            "manufacturer": props.get("manufacturer"),
            "location": props.get("location"),
            "last_maintenance": props.get("last_maintenance"),
            "last_calibration": props.get("last_calibration"),
            "json_addl": equipment.json_addl,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting equipment {euid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Dict[str, Any])
async def create_equipment(data: EquipmentCreateSchema):
    """Create new equipment from a template."""
    try:
        bdb = get_bdb()
        from bloom_lims.bobjs import BloomEquipment
        
        be = BloomEquipment(bdb)
        
        if data.template_euid:
            result = be.create_empty_equipment(data.template_euid)
            equipment = result[0][0] if isinstance(result, list) else result
        else:
            raise HTTPException(status_code=400, detail="template_euid is required")
        
        return {
            "success": True,
            "euid": equipment.euid,
            "uuid": str(equipment.uuid),
            "message": "Equipment created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating equipment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{euid}/maintenance")
async def record_maintenance(euid: str, data: MaintenanceRecordSchema):
    """Record a maintenance event for equipment."""
    try:
        bdb = get_bdb()
        from bloom_lims.domain.equipment import BloomEquipment
        
        be = BloomEquipment(bdb)
        equipment = be.record_maintenance(
            euid,
            maintenance_type=data.maintenance_type,
            performed_by=data.performed_by,
            notes=data.notes,
        )
        
        return {"success": True, "message": "Maintenance recorded", "euid": equipment.euid}
    except Exception as e:
        logger.error(f"Error recording maintenance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

