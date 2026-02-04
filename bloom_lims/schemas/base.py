"""
Base Pydantic schemas and common validators for BLOOM LIMS.
"""

import re
from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field, field_validator, ConfigDict


# Type variable for generic paginated responses
T = TypeVar("T")


# EUID validation pattern - matches format like "CX1", "CX123", "WX1000", "MRX42"
# Enterprise Unique Identifier: 2-3 letter prefix + sequence number (no leading zeros)
EUID_PATTERN = re.compile(r"^[A-Z]{2,3}[1-9][0-9]*$")


def validate_euid(value: str) -> str:
    """
    Validate EUID (Enterprise Unique Identifier) format.

    EUIDs follow the pattern: PREFIX + SEQUENCE_NUMBER
    - PREFIX: 2-3 uppercase letters identifying object type (e.g., CX, WX, MRX)
    - SEQUENCE_NUMBER: Integer with NO leading zeros (critical LIMS design principle)

    Examples: CX1, CX123, WX1000, MRX42, CWX5

    Args:
        value: The EUID string to validate

    Returns:
        The validated EUID string (uppercase)

    Raises:
        ValueError: If the EUID format is invalid
    """
    value = value.upper().strip()
    if not EUID_PATTERN.match(value):
        raise ValueError(
            f"Invalid EUID format: {value}. "
            "Expected format: PREFIX + sequence number (e.g., CX123, WX1000). "
            "No leading zeros allowed in sequence number."
        )
    return value


def EUIDField(description: str = "Enterprise Unique Identifier") -> Any:
    """Create a Field with EUID validation."""
    return Field(..., description=description, min_length=3, max_length=20)


class BloomBaseSchema(BaseModel):
    """
    Base schema for all BLOOM LIMS Pydantic models.
    
    Provides common configuration and utility methods.
    """
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
        from_attributes=True,
    )


class TimestampMixin(BaseModel):
    """Mixin for models with timestamp fields."""
    
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")


class AuditMixin(BaseModel):
    """Mixin for models with audit fields."""
    
    created_by: Optional[str] = Field(None, description="User who created")
    updated_by: Optional[str] = Field(None, description="User who last updated")


class PaginationParams(BloomBaseSchema):
    """
    Pagination parameters for list endpoints.
    """
    
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=50, ge=1, le=1000, description="Items per page")
    sort_by: Optional[str] = Field(None, description="Field to sort by")
    sort_order: str = Field(default="asc", pattern="^(asc|desc)$", description="Sort order")
    
    @property
    def offset(self) -> int:
        """Calculate SQL offset."""
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        """Get limit (alias for page_size)."""
        return self.page_size


class PaginatedResponse(BloomBaseSchema, Generic[T]):
    """
    Generic paginated response wrapper.
    """
    
    items: List[T] = Field(description="List of items")
    total: int = Field(description="Total number of items")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    pages: int = Field(description="Total number of pages")
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        pagination: PaginationParams,
    ) -> "PaginatedResponse[T]":
        """Create a paginated response from items and pagination params."""
        pages = (total + pagination.page_size - 1) // pagination.page_size
        return cls(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pages,
        )


class SuccessResponse(BloomBaseSchema):
    """Standard success response."""
    
    success: bool = Field(default=True, description="Operation success flag")
    message: str = Field(default="Operation completed successfully", description="Success message")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data")


class ErrorResponse(BloomBaseSchema):
    """Standard error response."""

    success: bool = Field(default=False, description="Operation success flag")
    error_code: str = Field(description="Error code for programmatic handling")
    message: str = Field(description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Error timestamp")


# =============================================================================
# Dashboard Statistics Schemas
# =============================================================================


class DashboardStatsSchema(BloomBaseSchema):
    """Dashboard statistics response schema."""

    assays_total: int = Field(default=0, description="Total number of assays")
    assays_in_progress: int = Field(default=0, description="Assays in progress")
    assays_complete: int = Field(default=0, description="Completed assays")
    assays_exception: int = Field(default=0, description="Assays with exceptions")

    workflows_total: int = Field(default=0, description="Total number of workflows")
    workflows_active: int = Field(default=0, description="Active workflows")
    workflows_complete: int = Field(default=0, description="Completed workflows")

    equipment_total: int = Field(default=0, description="Total equipment items")
    equipment_active: int = Field(default=0, description="Active equipment")
    equipment_maintenance: int = Field(default=0, description="Equipment in maintenance")

    reagents_total: int = Field(default=0, description="Total reagent lots")
    reagents_low_stock: int = Field(default=0, description="Reagents with low stock")
    reagents_expired: int = Field(default=0, description="Expired reagents")

    samples_total: int = Field(default=0, description="Total samples")
    containers_total: int = Field(default=0, description="Total containers")


class RecentActivityItem(BloomBaseSchema):
    """Single recent activity item."""

    euid: str = Field(description="Enterprise Unique Identifier")
    name: Optional[str] = Field(None, description="Object name")
    type: str = Field(description="Object type")
    subtype: Optional[str] = Field(None, description="Object subtype")
    status: Optional[str] = Field(None, description="Current status")
    created_dt: Optional[datetime] = Field(None, description="Creation timestamp")


class RecentActivitySchema(BloomBaseSchema):
    """Recent activity response schema."""

    recent_assays: List[RecentActivityItem] = Field(
        default_factory=list, description="Recent assay activities"
    )
    recent_workflows: List[RecentActivityItem] = Field(
        default_factory=list, description="Recent workflow activities"
    )
    recent_samples: List[RecentActivityItem] = Field(
        default_factory=list, description="Recent sample activities"
    )


class DashboardResponseSchema(BloomBaseSchema):
    """Complete dashboard response combining stats and recent activity."""

    stats: DashboardStatsSchema = Field(description="Dashboard statistics")
    recent_activity: RecentActivitySchema = Field(description="Recent activity data")
    generated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Response generation timestamp"
    )

