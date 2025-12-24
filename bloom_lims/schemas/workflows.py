"""
Pydantic schemas for workflows and workflow steps in BLOOM LIMS.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import Field, field_validator, model_validator

from .base import BloomBaseSchema, TimestampMixin, validate_euid


class WorkflowStepSchema(BloomBaseSchema):
    """Schema for workflow step definition."""
    
    name: str = Field(..., min_length=1, max_length=200, description="Step name")
    step_number: int = Field(..., ge=1, description="Step order number")
    description: Optional[str] = Field(None, max_length=2000, description="Step description")
    step_type: str = Field(default="standard", description="Type of step")
    required: bool = Field(default=True, description="Whether step is required")
    
    # Configuration
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Step configuration")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="Expected input schema")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="Expected output schema")
    
    # Conditions
    preconditions: Optional[List[str]] = Field(None, description="Preconditions to check")
    skip_conditions: Optional[List[str]] = Field(None, description="Conditions to skip step")


class WorkflowStepUpdateSchema(BloomBaseSchema):
    """Schema for updating a workflow step."""
    
    euid: str = Field(..., description="Step EUID to update")
    status: Optional[str] = Field(None, description="New status")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    completed_by: Optional[str] = Field(None, description="User who completed")
    result: Optional[Dict[str, Any]] = Field(None, description="Step result data")
    notes: Optional[str] = Field(None, max_length=5000, description="Step notes")
    
    @field_validator("euid", mode="before")
    @classmethod
    def validate_euid(cls, v):
        """Validate step EUID."""
        return validate_euid(v)


class WorkflowBaseSchema(BloomBaseSchema):
    """Base schema for workflows."""
    
    name: str = Field(..., min_length=1, max_length=300, description="Workflow name")
    workflow_type: str = Field(..., min_length=1, max_length=100, description="Workflow type")
    description: Optional[str] = Field(None, max_length=5000, description="Workflow description")
    
    # Configuration
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Workflow config")
    
    @field_validator("workflow_type", mode="before")
    @classmethod
    def normalize_workflow_type(cls, v):
        """Normalize workflow type to lowercase."""
        if v:
            return str(v).strip().lower()
        return v


class WorkflowCreateSchema(WorkflowBaseSchema):
    """Schema for creating a new workflow."""
    
    steps: List[WorkflowStepSchema] = Field(
        default_factory=list,
        description="Workflow steps definition"
    )
    template_euid: Optional[str] = Field(None, description="Template to create from")
    
    # Objects to process
    object_euids: Optional[List[str]] = Field(None, description="Objects to attach to workflow")
    
    @field_validator("template_euid", mode="before")
    @classmethod
    def validate_template_euid(cls, v):
        """Validate template EUID if provided."""
        if v is not None and v.strip():
            return validate_euid(v)
        return None
    
    @field_validator("object_euids", mode="before")
    @classmethod
    def validate_object_euids(cls, v):
        """Validate object EUIDs if provided."""
        if v is None:
            return None
        validated = []
        for euid in v:
            if euid and euid.strip():
                validated.append(validate_euid(euid))
        return validated if validated else None
    
    @model_validator(mode="after")
    def validate_steps_or_template(self):
        """Ensure either steps or template is provided."""
        if not self.steps and not self.template_euid:
            raise ValueError("Either 'steps' or 'template_euid' must be provided")
        return self


class WorkflowStepResponseSchema(WorkflowStepSchema, TimestampMixin):
    """Schema for workflow step in API responses."""
    
    euid: str = Field(..., description="Step EUID")
    uuid: str = Field(..., description="Step UUID")
    status: str = Field(default="pending", description="Step status")
    workflow_euid: str = Field(..., description="Parent workflow EUID")
    
    # Execution info
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    completed_by: Optional[str] = Field(None, description="User who completed")
    result: Optional[Dict[str, Any]] = Field(None, description="Step result data")
    
    # Timing
    duration_seconds: Optional[int] = Field(None, description="Execution duration")


class WorkflowResponseSchema(WorkflowBaseSchema, TimestampMixin):
    """Schema for workflow API responses."""
    
    euid: str = Field(..., description="Workflow EUID")
    uuid: str = Field(..., description="Workflow UUID")
    status: str = Field(default="pending", description="Workflow status")
    
    # Progress tracking
    current_step: Optional[int] = Field(None, description="Current step number")
    total_steps: int = Field(default=0, description="Total number of steps")
    completed_steps: int = Field(default=0, description="Number of completed steps")
    
    # Steps
    steps: List[WorkflowStepResponseSchema] = Field(default_factory=list, description="Workflow steps")
    
    # Timing
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    
    @property
    def progress_percent(self) -> float:
        """Calculate completion percentage."""
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100

