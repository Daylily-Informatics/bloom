"""
Pydantic schemas for containers in BLOOM LIMS.

Containers are objects that hold other objects: plates, racks, boxes, shelves, etc.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import Field, field_validator, model_validator
import re

from .base import BloomBaseSchema, TimestampMixin, validate_euid


# Well position pattern - matches A1, B12, H8, etc.
WELL_POSITION_PATTERN = re.compile(r'^[A-P]([1-9]|1[0-9]|2[0-4])$')


def validate_well_position(value: str) -> str:
    """Validate well position format."""
    value = value.upper().strip()
    if not WELL_POSITION_PATTERN.match(value):
        raise ValueError(f"Invalid well position: {value}. Expected format: A1-P24")
    return value


class ContainerLayoutSchema(BloomBaseSchema):
    """Schema for container layout configuration."""
    
    rows: int = Field(default=8, ge=1, le=26, description="Number of rows (1-26)")
    columns: int = Field(default=12, ge=1, le=48, description="Number of columns (1-48)")
    row_labels: str = Field(default="letters", pattern="^(letters|numbers)$", description="Row labeling scheme")
    column_labels: str = Field(default="numbers", pattern="^(letters|numbers)$", description="Column labeling scheme")
    fill_direction: str = Field(default="row", pattern="^(row|column)$", description="Fill direction")
    
    @property
    def total_positions(self) -> int:
        """Total number of positions in container."""
        return self.rows * self.columns
    
    @property
    def well_format(self) -> str:
        """Get well format string (e.g., '96-well', '384-well')."""
        total = self.total_positions
        return f"{total}-well"


class ContainerPositionSchema(BloomBaseSchema):
    """Schema for a position within a container."""
    
    position: str = Field(..., description="Well position (e.g., A1)")
    euid: Optional[str] = Field(None, description="EUID of object at this position")
    uuid: Optional[str] = Field(None, description="UUID of object at this position")
    name: Optional[str] = Field(None, description="Name of object at this position")
    btype: Optional[str] = Field(None, description="Type of object at this position")
    placed_at: Optional[datetime] = Field(None, description="When object was placed")
    
    @field_validator("position", mode="before")
    @classmethod
    def normalize_position(cls, v):
        """Normalize position to uppercase."""
        if v:
            return validate_well_position(v)
        return v


class ContainerBaseSchema(BloomBaseSchema):
    """Base schema for container objects."""
    
    name: str = Field(..., min_length=1, max_length=500, description="Container name")
    container_type: str = Field(..., description="Container type (plate, rack, box, etc.)")
    b_sub_type: Optional[str] = Field(None, description="Container subtype (e.g., 96-well, 384-well)")
    barcode: Optional[str] = Field(None, max_length=100, description="Physical barcode")
    layout: Optional[ContainerLayoutSchema] = Field(None, description="Container layout")
    json_addl: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    
    @field_validator("container_type", mode="before")
    @classmethod
    def normalize_container_type(cls, v):
        """Normalize container type to lowercase."""
        if v:
            return str(v).strip().lower()
        return v


class ContainerCreateSchema(ContainerBaseSchema):
    """Schema for creating a new container."""
    
    template_euid: Optional[str] = Field(None, description="Template to create from")
    parent_euid: Optional[str] = Field(None, description="Parent container EUID")
    
    @field_validator("template_euid", "parent_euid", mode="before")
    @classmethod
    def validate_euids(cls, v):
        """Validate EUID fields if provided."""
        if v is not None and str(v).strip():
            return validate_euid(v)
        return None


class ContainerUpdateSchema(BloomBaseSchema):
    """Schema for updating a container."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    barcode: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(None, max_length=50)
    json_addl: Optional[Dict[str, Any]] = Field(None)
    is_deleted: Optional[bool] = Field(None)


class ContainerResponseSchema(ContainerBaseSchema, TimestampMixin):
    """Schema for container API responses."""
    
    euid: str = Field(..., description="Container EUID")
    uuid: str = Field(..., description="Container UUID")
    status: str = Field(default="active", description="Container status")
    is_deleted: bool = Field(default=False, description="Soft delete flag")
    
    # Layout info
    total_positions: int = Field(default=0, description="Total positions in container")
    occupied_positions: int = Field(default=0, description="Number of occupied positions")
    available_positions: int = Field(default=0, description="Number of available positions")
    
    # Contents summary
    contents_count: int = Field(default=0, description="Number of objects in container")
    contents: Optional[List[ContainerPositionSchema]] = Field(None, description="Container contents")
    
    # Hierarchy
    parent_euid: Optional[str] = Field(None, description="Parent container EUID")
    children_count: int = Field(default=0, description="Number of child containers")


class PlaceInContainerSchema(BloomBaseSchema):
    """Schema for placing an object in a container."""
    
    container_euid: str = Field(..., description="Container EUID")
    object_euid: str = Field(..., description="Object to place EUID")
    position: str = Field(..., description="Position (e.g., A1)")
    
    @field_validator("container_euid", "object_euid", mode="before")
    @classmethod
    def validate_euids(cls, v):
        return validate_euid(v)
    
    @field_validator("position", mode="before")
    @classmethod
    def validate_position(cls, v):
        return validate_well_position(v)


class BulkPlaceInContainerSchema(BloomBaseSchema):
    """Schema for placing multiple objects in a container."""
    
    container_euid: str = Field(..., description="Container EUID")
    placements: List[Dict[str, str]] = Field(..., description="List of {object_euid, position}")
    
    @field_validator("container_euid", mode="before")
    @classmethod
    def validate_container_euid(cls, v):
        return validate_euid(v)

