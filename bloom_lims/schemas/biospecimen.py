"""
Pydantic schemas for biospecimen API request/response validation.

These schemas validate API input/output for biospecimen operations.
They do NOT define the object type -- that is handled by JSON templates
in bloom_lims/config/content/specimen.json and the generic BloomContent
domain class.

Valid statuses mirror the biospecimen lifecycle:
  REGISTERED -> IN_TRANSIT -> RECEIVED -> IN_PROCESS -> COMPLETE | FAILED | REJECTED
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import Field, field_validator

from .base import BloomBaseSchema, TimestampMixin, validate_euid


class BioSpecimenStatus(str, Enum):
    """Biospecimen lifecycle statuses."""

    REGISTERED = "REGISTERED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    IN_PROCESS = "IN_PROCESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class BioSpecimenCreate(BloomBaseSchema):
    """Schema for creating a biospecimen instance via API.

    The caller provides the specimen subtype (e.g. 'blood-whole') and
    optional property overrides. The API layer resolves the template EUID
    and calls BloomContent.create_empty_content(template_euid).
    """

    specimen_subtype: str = Field(
        ...,
        description="Specimen subtype matching a template key in specimen.json "
        "(e.g. blood-whole, ffpe-block, saliva, buccal-swab)",
    )
    specimen_barcode: Optional[str] = Field(
        None, max_length=200, description="Scannable specimen barcode"
    )
    collection_date: Optional[datetime] = Field(
        None, description="Date/time specimen was collected"
    )
    condition: Optional[str] = Field(
        None, max_length=200, description="Specimen condition on receipt"
    )
    volume: Optional[str] = Field(None, description="Volume value")
    volume_units: Optional[str] = Field(None, description="Volume units (mL, uL, etc.)")
    atlas_patient_euid: Optional[str] = Field(
        None, description="Reference EUID to Atlas patient (no PHI)"
    )
    atlas_order_euid: Optional[str] = Field(
        None, description="Reference EUID to Atlas order"
    )
    comments: Optional[str] = Field(None, description="Free-text comments")
    lab_code: Optional[str] = Field(None, max_length=100, description="Lab code")

    @field_validator("specimen_subtype", mode="before")
    @classmethod
    def normalize_subtype(cls, v: str) -> str:
        if v:
            return str(v).strip().lower()
        return v

    @field_validator("atlas_patient_euid", "atlas_order_euid", mode="before")
    @classmethod
    def validate_optional_euids(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and str(v).strip():
            return validate_euid(v)
        return None


class BioSpecimenUpdate(BloomBaseSchema):
    """Schema for updating biospecimen properties in json_addl."""

    specimen_barcode: Optional[str] = Field(None, max_length=200)
    condition: Optional[str] = Field(None, max_length=200)
    volume: Optional[str] = Field(None)
    volume_units: Optional[str] = Field(None)
    atlas_patient_euid: Optional[str] = Field(None)
    atlas_order_euid: Optional[str] = Field(None)
    comments: Optional[str] = Field(None)
    lab_code: Optional[str] = Field(None, max_length=100)

    @field_validator("atlas_patient_euid", "atlas_order_euid", mode="before")
    @classmethod
    def validate_optional_euids(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and str(v).strip():
            return validate_euid(v)
        return None


class BioSpecimenStatusUpdate(BloomBaseSchema):
    """Schema for updating biospecimen status."""

    status: BioSpecimenStatus = Field(..., description="New lifecycle status")


class BioSpecimenResponse(BloomBaseSchema, TimestampMixin):
    """Schema for biospecimen API responses."""

    euid: str = Field(..., description="Instance EUID")
    uuid: str = Field(..., description="Instance UUID")
    name: str = Field(..., description="Specimen name (from template)")
    subtype: str = Field(..., description="Specimen subtype")
    status: str = Field(default="REGISTERED", description="Lifecycle status")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Full properties from json_addl"
    )
    is_deleted: bool = Field(default=False)

    @classmethod
    def from_instance(cls, instance) -> "BioSpecimenResponse":
        """Build response from a generic_instance ORM object."""
        props = instance.json_addl.get("properties", {})
        return cls(
            euid=instance.euid,
            uuid=str(instance.uuid),
            name=instance.name,
            subtype=instance.subtype,
            status=props.get("status", "REGISTERED"),
            properties=props,
            is_deleted=instance.is_deleted,
            created_at=instance.created_dt,
            updated_at=getattr(instance, "modified_dt", instance.created_dt),
        )
