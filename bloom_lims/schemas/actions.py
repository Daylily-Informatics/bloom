"""
Pydantic schemas for actions in BLOOM LIMS.

Actions represent executable operations that can be performed on objects,
such as label printing, data capture, workflow transitions, etc.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import Field, field_validator, model_validator

from .base import BloomBaseSchema, TimestampMixin, validate_euid


class ActionParameterSchema(BloomBaseSchema):
    """Schema for action parameter definition."""
    
    name: str = Field(..., min_length=1, max_length=100, description="Parameter name")
    param_type: str = Field(..., description="Parameter type (string, number, boolean, select, date)")
    required: bool = Field(default=False, description="Whether parameter is required")
    default_value: Optional[Any] = Field(None, description="Default value")
    description: Optional[str] = Field(None, max_length=500, description="Parameter description")
    
    # For select type
    options: Optional[List[str]] = Field(None, description="Options for select type")
    
    # Validation
    min_value: Optional[Union[int, float]] = Field(None, description="Minimum value (for numbers)")
    max_value: Optional[Union[int, float]] = Field(None, description="Maximum value (for numbers)")
    pattern: Optional[str] = Field(None, description="Regex pattern (for strings)")


class ActionGroupSchema(BloomBaseSchema):
    """Schema for action group definition."""
    
    group_name: str = Field(..., min_length=1, max_length=100, description="Group name")
    group_order: int = Field(default=0, ge=0, description="Display order")
    description: Optional[str] = Field(None, max_length=500, description="Group description")
    actions: Dict[str, Any] = Field(default_factory=dict, description="Actions in this group")


class ActionBaseSchema(BloomBaseSchema):
    """Base schema for actions."""
    
    name: str = Field(..., min_length=1, max_length=200, description="Action name")
    action_type: str = Field(..., description="Action type")
    description: Optional[str] = Field(None, max_length=2000, description="Action description")
    
    # Configuration
    parameters: Optional[List[ActionParameterSchema]] = Field(None, description="Action parameters")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Action configuration")
    
    # Execution limits
    max_executions: Optional[int] = Field(None, ge=0, description="Max times action can be executed")
    cooldown_seconds: Optional[int] = Field(None, ge=0, description="Cooldown between executions")
    
    @field_validator("action_type", mode="before")
    @classmethod
    def normalize_action_type(cls, v):
        if v:
            return str(v).strip().lower()
        return v


class ActionCreateSchema(ActionBaseSchema):
    """Schema for creating a new action."""
    
    template_euid: Optional[str] = Field(None, description="Template to create from")
    target_euid: Optional[str] = Field(None, description="Target object EUID")
    
    @field_validator("template_euid", "target_euid", mode="before")
    @classmethod
    def validate_euids(cls, v):
        if v is not None and str(v).strip():
            return validate_euid(v)
        return None


class ActionExecuteSchema(BloomBaseSchema):
    """Schema for executing an action."""
    
    action_name: str = Field(..., description="Action name to execute")
    target_euid: str = Field(..., description="Target object EUID")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Action parameters")
    executed_by: Optional[str] = Field(None, description="User executing action")
    
    @field_validator("target_euid", mode="before")
    @classmethod
    def validate_target_euid(cls, v):
        return validate_euid(v)


class ActionResultSchema(BloomBaseSchema, TimestampMixin):
    """Schema for action execution result."""
    
    success: bool = Field(..., description="Whether action succeeded")
    action_name: str = Field(..., description="Action name")
    target_euid: str = Field(..., description="Target object EUID")
    
    # Result details
    result_data: Optional[Dict[str, Any]] = Field(None, description="Result data")
    message: Optional[str] = Field(None, description="Result message")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    # Execution info
    executed_by: Optional[str] = Field(None, description="User who executed")
    execution_time_ms: Optional[int] = Field(None, ge=0, description="Execution time in ms")


class ActionResponseSchema(ActionBaseSchema, TimestampMixin):
    """Schema for action API responses."""
    
    euid: str = Field(..., description="Action EUID")
    uuid: str = Field(..., description="Action UUID")
    status: str = Field(default="active", description="Action status")
    
    # Execution stats
    execution_count: int = Field(default=0, description="Times executed")
    last_executed_at: Optional[datetime] = Field(None, description="Last execution time")
    last_executed_by: Optional[str] = Field(None, description="Last executor")


class BulkActionExecuteSchema(BloomBaseSchema):
    """Schema for executing an action on multiple objects."""
    
    action_name: str = Field(..., description="Action name to execute")
    target_euids: List[str] = Field(..., min_length=1, description="Target object EUIDs")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Action parameters")
    executed_by: Optional[str] = Field(None, description="User executing action")
    stop_on_error: bool = Field(default=False, description="Stop on first error")
    
    @field_validator("target_euids", mode="before")
    @classmethod
    def validate_target_euids(cls, v):
        if v is None or len(v) == 0:
            raise ValueError("At least one target EUID required")
        return [validate_euid(euid) for euid in v]


class BulkActionResultSchema(BloomBaseSchema):
    """Schema for bulk action execution result."""
    
    action_name: str = Field(..., description="Action name")
    total_targets: int = Field(..., ge=0, description="Total targets processed")
    successful: int = Field(default=0, ge=0, description="Successful executions")
    failed: int = Field(default=0, ge=0, description="Failed executions")
    
    results: List[ActionResultSchema] = Field(default_factory=list, description="Individual results")
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_targets == 0:
            return 0.0
        return (self.successful / self.total_targets) * 100

