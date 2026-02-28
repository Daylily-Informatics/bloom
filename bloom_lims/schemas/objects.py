"""
Pydantic schemas for BloomObj (generic instances) in BLOOM LIMS.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import Field, field_validator, model_validator

from .base import BloomBaseSchema, TimestampMixin, validate_euid


class JsonAddlSchema(BloomBaseSchema):
    """
    Schema for json_addl field validation.
    
    The json_addl field stores additional metadata as JSON. This schema
    validates common fields while allowing extension.
    """
    
    # Common optional fields
    notes: Optional[str] = Field(None, max_length=10000, description="General notes")
    tags: Optional[List[str]] = Field(None, description="Tags for categorization")
    custom_fields: Optional[Dict[str, Any]] = Field(None, description="Custom field values")
    
    # Allow extra fields for flexibility
    model_config = {"extra": "allow"}
    
    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, v):
        """Normalize tags to lowercase strings."""
        if v is None:
            return None
        if isinstance(v, str):
            return [t.strip().lower() for t in v.split(",") if t.strip()]
        return [str(t).strip().lower() for t in v if t]


class ObjectBaseSchema(BloomBaseSchema):
    """Base schema for BloomObj/generic_instance objects."""

    name: str = Field(..., min_length=1, max_length=500, description="Object name")
    type: str = Field(..., min_length=1, max_length=100, description="Object type (e.g., sample, plate)")
    subtype: Optional[str] = Field(None, max_length=100, description="Object subtype")
    category: str = Field(default="instance", max_length=50, description="Category (formerly super_type)")
    json_addl: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional JSON data")

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v):
        """Normalize type to lowercase."""
        if v:
            return str(v).strip().lower()
        return v
    
    @field_validator("json_addl", mode="before")
    @classmethod
    def ensure_json_addl_dict(cls, v):
        """Ensure json_addl is a dictionary."""
        if v is None:
            return {}
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("json_addl must be valid JSON")
        return v


class ObjectCreateSchema(ObjectBaseSchema):
    """Schema for creating a new BloomObj."""
    
    parent_euid: Optional[str] = Field(None, description="Parent object EUID for lineage")
    lineage_euid: Optional[str] = Field(None, description="Lineage EUID to attach to")
    container_euid: Optional[str] = Field(None, description="Container EUID for placement")
    container_position: Optional[str] = Field(None, description="Position in container (e.g., A1)")
    
    @field_validator("parent_euid", "lineage_euid", "container_euid", mode="before")
    @classmethod
    def validate_euids(cls, v):
        """Validate EUID fields if provided."""
        if v is not None and v.strip():
            return validate_euid(v)
        return None


class ObjectUpdateSchema(BloomBaseSchema):
    """Schema for updating an existing BloomObj."""

    name: Optional[str] = Field(None, min_length=1, max_length=500, description="Object name")
    json_addl: Optional[Dict[str, Any]] = Field(None, description="Additional JSON data (merged)")
    status: Optional[str] = Field(None, max_length=50, description="Object status")
    is_deleted: Optional[bool] = Field(None, description="Soft delete flag")
    created_dt: Optional[datetime] = Field(None, description="Creation datetime (admin only)")

    @model_validator(mode="after")
    def check_at_least_one_field(self):
        """Ensure at least one field is provided for update."""
        if not any([self.name, self.json_addl, self.status, self.is_deleted is not None, self.created_dt]):
            raise ValueError("At least one field must be provided for update")
        return self


class ObjectResponseSchema(ObjectBaseSchema, TimestampMixin):
    """Schema for BloomObj API responses."""
    
    euid: str = Field(..., description="Entity Unique Identifier")
    uuid: str = Field(..., description="Universal Unique Identifier")
    status: str = Field(default="active", description="Object status")
    is_deleted: bool = Field(default=False, description="Soft delete flag")
    is_singleton: bool = Field(default=False, description="Singleton instance flag")
    polymorphic_discriminator: Optional[str] = Field(None, description="Type discriminator")
    
    # Relationship info (optional)
    parent_euid: Optional[str] = Field(None, description="Parent object EUID")
    lineage_euid: Optional[str] = Field(None, description="Lineage EUID")
    container_euid: Optional[str] = Field(None, description="Container EUID")
    container_position: Optional[str] = Field(None, description="Position in container")


class ObjectQueryParams(BloomBaseSchema):
    """Query parameters for listing/searching objects."""

    type: Optional[str] = Field(None, description="Filter by object type")
    subtype: Optional[str] = Field(None, description="Filter by subtype")
    category: Optional[str] = Field(None, description="Filter by category")
    status: Optional[str] = Field(None, description="Filter by status")
    name_contains: Optional[str] = Field(None, description="Filter by name (contains)")
    parent_euid: Optional[str] = Field(None, description="Filter by parent")
    lineage_euid: Optional[str] = Field(None, description="Filter by lineage")
    container_euid: Optional[str] = Field(None, description="Filter by container")
    created_after: Optional[datetime] = Field(None, description="Filter by creation date")
    created_before: Optional[datetime] = Field(None, description="Filter by creation date")
    include_deleted: bool = Field(default=False, description="Include soft-deleted objects")

    @field_validator("type", "subtype", mode="before")
    @classmethod
    def normalize_types(cls, v):
        """Normalize type fields to lowercase."""
        if v:
            return str(v).strip().lower()
        return v

