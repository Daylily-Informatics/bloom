"""
Pydantic schemas for content objects in BLOOM LIMS.

Content objects represent samples, specimens, reagents, controls, pools, etc.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import Field, field_validator, model_validator

from .base import BloomBaseSchema, TimestampMixin, validate_euid


class ContentBaseSchema(BloomBaseSchema):
    """Base schema for content objects (samples, specimens, reagents, etc.)."""

    name: str = Field(..., min_length=1, max_length=500, description="Content name")
    content_type: str = Field(..., description="Content type (sample, specimen, reagent, control, pool)")
    subtype: Optional[str] = Field(None, description="Content subtype")
    barcode: Optional[str] = Field(None, max_length=100, description="Physical barcode")

    # Scientific properties
    volume_ul: Optional[float] = Field(None, ge=0, description="Volume in microliters")
    concentration_ng_ul: Optional[float] = Field(None, ge=0, description="Concentration in ng/µL")
    mass_ng: Optional[float] = Field(None, ge=0, description="Mass in nanograms")

    # Metadata
    json_addl: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")

    @field_validator("content_type", "subtype", mode="before")
    @classmethod
    def normalize_types(cls, v):
        """Normalize type fields to lowercase."""
        if v:
            return str(v).strip().lower()
        return v


class SampleCreateSchema(ContentBaseSchema):
    """Schema for creating a sample."""
    
    content_type: str = Field(default="sample", description="Content type")
    specimen_euid: Optional[str] = Field(None, description="Source specimen EUID")
    container_euid: Optional[str] = Field(None, description="Container to place sample")
    container_position: Optional[str] = Field(None, description="Position in container")
    
    # Sample-specific fields
    sample_type: Optional[str] = Field(None, description="Sample type (DNA, RNA, protein, etc.)")
    extraction_method: Optional[str] = Field(None, description="Extraction method used")
    quality_score: Optional[float] = Field(None, ge=0, le=100, description="Quality score (0-100)")
    
    @field_validator("specimen_euid", "container_euid", mode="before")
    @classmethod
    def validate_euids(cls, v):
        if v is not None and str(v).strip():
            return validate_euid(v)
        return None


class SpecimenCreateSchema(ContentBaseSchema):
    """Schema for creating a specimen."""
    
    content_type: str = Field(default="specimen", description="Content type")
    
    # Specimen-specific fields
    specimen_type: str = Field(..., description="Specimen type (blood, tissue, saliva, etc.)")
    collection_date: Optional[datetime] = Field(None, description="Collection date")
    collected_by: Optional[str] = Field(None, max_length=200, description="Collector name")
    source_id: Optional[str] = Field(None, max_length=100, description="External source ID")
    
    # Subject info (anonymized)
    subject_id: Optional[str] = Field(None, max_length=100, description="Subject identifier")
    
    @field_validator("specimen_type", mode="before")
    @classmethod
    def normalize_specimen_type(cls, v):
        if v:
            return str(v).strip().lower()
        return v


class ReagentCreateSchema(ContentBaseSchema):
    """Schema for creating a reagent."""
    
    content_type: str = Field(default="reagent", description="Content type")
    
    # Reagent-specific fields
    reagent_type: str = Field(..., description="Reagent type")
    lot_number: Optional[str] = Field(None, max_length=100, description="Lot number")
    expiration_date: Optional[datetime] = Field(None, description="Expiration date")
    manufacturer: Optional[str] = Field(None, max_length=200, description="Manufacturer")
    catalog_number: Optional[str] = Field(None, max_length=100, description="Catalog number")
    storage_conditions: Optional[str] = Field(None, description="Storage requirements")


class ControlCreateSchema(ContentBaseSchema):
    """Schema for creating a control."""
    
    content_type: str = Field(default="control", description="Content type")
    
    # Control-specific fields
    control_type: str = Field(..., description="Control type (positive, negative, NTC, etc.)")
    expected_result: Optional[str] = Field(None, description="Expected result")
    acceptable_range_min: Optional[float] = Field(None, description="Min acceptable value")
    acceptable_range_max: Optional[float] = Field(None, description="Max acceptable value")


class PoolCreateSchema(ContentBaseSchema):
    """Schema for creating a pool of samples."""
    
    content_type: str = Field(default="pool", description="Content type")
    
    # Pool-specific fields
    member_euids: List[str] = Field(default_factory=list, description="Pool member EUIDs")
    pooling_ratio: Optional[str] = Field(None, description="Pooling ratio (e.g., '1:1:1')")
    
    @field_validator("member_euids", mode="before")
    @classmethod
    def validate_member_euids(cls, v):
        if v is None:
            return []
        return [validate_euid(euid) for euid in v if euid and str(euid).strip()]


class ContentUpdateSchema(BloomBaseSchema):
    """Schema for updating content objects."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    status: Optional[str] = Field(None, max_length=50)
    volume_ul: Optional[float] = Field(None, ge=0)
    concentration_ng_ul: Optional[float] = Field(None, ge=0)
    mass_ng: Optional[float] = Field(None, ge=0)
    json_addl: Optional[Dict[str, Any]] = Field(None)
    is_deleted: Optional[bool] = Field(None)


class ContentResponseSchema(ContentBaseSchema, TimestampMixin):
    """Schema for content API responses."""
    
    euid: str = Field(..., description="Content EUID")
    uuid: str = Field(..., description="Content UUID")
    status: str = Field(default="active", description="Content status")
    is_deleted: bool = Field(default=False, description="Soft delete flag")
    
    # Location
    container_euid: Optional[str] = Field(None, description="Current container")
    container_position: Optional[str] = Field(None, description="Position in container")
    
    # Lineage
    parent_euid: Optional[str] = Field(None, description="Parent content EUID")
    children_count: int = Field(default=0, description="Number of child objects")
    
    # Quality
    quality_score: Optional[float] = Field(None, description="Quality score")
    quality_status: Optional[str] = Field(None, description="Quality status (pass/fail/pending)")

