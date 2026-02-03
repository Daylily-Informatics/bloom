"""
Pydantic schemas for equipment in BLOOM LIMS.

Equipment represents lab instruments, devices, and other physical assets
that are tracked within the LIMS.
"""

from datetime import datetime, date
from typing import Any, Dict, List, Optional
from pydantic import Field, field_validator

from .base import BloomBaseSchema, TimestampMixin, validate_euid


class MaintenanceRecordSchema(BloomBaseSchema):
    """Schema for equipment maintenance record."""
    
    maintenance_type: str = Field(..., description="Type of maintenance")
    performed_date: datetime = Field(..., description="When maintenance was performed")
    performed_by: Optional[str] = Field(None, description="Who performed maintenance")
    notes: Optional[str] = Field(None, max_length=2000, description="Maintenance notes")
    next_due_date: Optional[date] = Field(None, description="Next scheduled maintenance")
    cost: Optional[float] = Field(None, ge=0, description="Maintenance cost")


class CalibrationRecordSchema(BloomBaseSchema):
    """Schema for equipment calibration record."""
    
    calibration_date: datetime = Field(..., description="Calibration date")
    calibrated_by: Optional[str] = Field(None, description="Calibration technician")
    certificate_number: Optional[str] = Field(None, description="Calibration certificate")
    expiration_date: Optional[date] = Field(None, description="Calibration expiry")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Calibration parameters")
    passed: bool = Field(default=True, description="Whether calibration passed")


class EquipmentBaseSchema(BloomBaseSchema):
    """Base schema for equipment objects."""

    name: str = Field(..., min_length=1, max_length=500, description="Equipment name")
    equipment_type: str = Field(..., description="Equipment type (sequencer, liquid_handler, etc.)")
    subtype: Optional[str] = Field(None, description="Equipment subtype")

    # Identification
    serial_number: Optional[str] = Field(None, max_length=100, description="Serial number")
    model: Optional[str] = Field(None, max_length=200, description="Model name/number")
    manufacturer: Optional[str] = Field(None, max_length=200, description="Manufacturer")

    # Location
    location: Optional[str] = Field(None, max_length=200, description="Physical location")
    room: Optional[str] = Field(None, max_length=100, description="Room/area")

    # Status
    operational_status: str = Field(default="operational", description="Operational status")

    # Metadata
    json_addl: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional data")

    @field_validator("equipment_type", "subtype", mode="before")
    @classmethod
    def normalize_types(cls, v):
        if v:
            return str(v).strip().lower()
        return v


class EquipmentCreateSchema(EquipmentBaseSchema):
    """Schema for creating equipment."""
    
    template_euid: Optional[str] = Field(None, description="Template to create from")
    
    # Purchase/acquisition info
    purchase_date: Optional[date] = Field(None, description="Purchase date")
    purchase_price: Optional[float] = Field(None, ge=0, description="Purchase price")
    warranty_expiration: Optional[date] = Field(None, description="Warranty expiration")
    
    @field_validator("template_euid", mode="before")
    @classmethod
    def validate_template_euid(cls, v):
        if v is not None and str(v).strip():
            return validate_euid(v)
        return None


class EquipmentUpdateSchema(BloomBaseSchema):
    """Schema for updating equipment."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    location: Optional[str] = Field(None, max_length=200)
    room: Optional[str] = Field(None, max_length=100)
    operational_status: Optional[str] = Field(None)
    json_addl: Optional[Dict[str, Any]] = Field(None)
    is_deleted: Optional[bool] = Field(None)


class EquipmentResponseSchema(EquipmentBaseSchema, TimestampMixin):
    """Schema for equipment API responses."""
    
    euid: str = Field(..., description="Equipment EUID")
    uuid: str = Field(..., description="Equipment UUID")
    status: str = Field(default="active", description="Record status")
    is_deleted: bool = Field(default=False, description="Soft delete flag")
    
    # Dates
    purchase_date: Optional[date] = Field(None, description="Purchase date")
    warranty_expiration: Optional[date] = Field(None, description="Warranty expiration")
    last_maintenance: Optional[datetime] = Field(None, description="Last maintenance")
    next_maintenance: Optional[date] = Field(None, description="Next scheduled maintenance")
    last_calibration: Optional[datetime] = Field(None, description="Last calibration")
    calibration_expiration: Optional[date] = Field(None, description="Calibration expiry")
    
    # Usage stats
    total_runs: int = Field(default=0, description="Total runs/uses")
    total_runtime_hours: float = Field(default=0, description="Total runtime hours")
    
    # Records
    maintenance_records: Optional[List[MaintenanceRecordSchema]] = Field(None)
    calibration_records: Optional[List[CalibrationRecordSchema]] = Field(None)


class EquipmentRunSchema(BloomBaseSchema):
    """Schema for recording equipment usage/run."""
    
    equipment_euid: str = Field(..., description="Equipment EUID")
    run_type: str = Field(..., description="Type of run")
    started_at: datetime = Field(..., description="Run start time")
    ended_at: Optional[datetime] = Field(None, description="Run end time")
    operator: Optional[str] = Field(None, description="Operator name")
    
    # Run details
    parameters: Optional[Dict[str, Any]] = Field(None, description="Run parameters")
    result_status: Optional[str] = Field(None, description="Run result (success/fail)")
    notes: Optional[str] = Field(None, max_length=2000, description="Run notes")
    
    # Associated objects
    input_euids: Optional[List[str]] = Field(None, description="Input object EUIDs")
    output_euids: Optional[List[str]] = Field(None, description="Output object EUIDs")
    
    @field_validator("equipment_euid", mode="before")
    @classmethod
    def validate_equipment_euid(cls, v):
        return validate_euid(v)


class EquipmentSearchSchema(BloomBaseSchema):
    """Schema for equipment search parameters."""
    
    name_contains: Optional[str] = Field(None, description="Search by name")
    equipment_type: Optional[str] = Field(None, description="Filter by type")
    manufacturer: Optional[str] = Field(None, description="Filter by manufacturer")
    location: Optional[str] = Field(None, description="Filter by location")
    operational_status: Optional[str] = Field(None, description="Filter by status")
    calibration_due_before: Optional[date] = Field(None, description="Calibration due before")
    maintenance_due_before: Optional[date] = Field(None, description="Maintenance due before")

