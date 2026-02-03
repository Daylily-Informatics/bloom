"""
BLOOM LIMS Pydantic Schemas

This module provides Pydantic models for input validation, serialization,
and API documentation in the BLOOM LIMS system.

Usage:
    from bloom_lims.schemas import ObjectCreateSchema, ObjectUpdateSchema
    from bloom_lims.schemas import WorkflowStepSchema, AuthLoginSchema
    from bloom_lims.schemas import ContainerCreateSchema, SampleCreateSchema
"""

from .base import (
    BloomBaseSchema,
    PaginationParams,
    PaginatedResponse,
    SuccessResponse,
    ErrorResponse,
    EUIDField,
    validate_euid,
    TimestampMixin,
    AuditMixin,
    DashboardStatsSchema,
    RecentActivityItem,
    RecentActivitySchema,
    DashboardResponseSchema,
)
from .objects import (
    ObjectBaseSchema,
    ObjectCreateSchema,
    ObjectUpdateSchema,
    ObjectResponseSchema,
    ObjectQueryParams,
    JsonAddlSchema,
)
from .workflows import (
    WorkflowBaseSchema,
    WorkflowCreateSchema,
    WorkflowStepSchema,
    WorkflowStepUpdateSchema,
    WorkflowResponseSchema,
    WorkflowStepResponseSchema,
)
from .auth import (
    AuthLoginSchema,
    AuthTokenSchema,
    UserSchema,
    UserCreateSchema,
    UserUpdateSchema,
    PasswordResetRequestSchema,
    PasswordResetSchema,
)
from .containers import (
    ContainerLayoutSchema,
    ContainerPositionSchema,
    ContainerBaseSchema,
    ContainerCreateSchema,
    ContainerUpdateSchema,
    ContainerResponseSchema,
    PlaceInContainerSchema,
    BulkPlaceInContainerSchema,
)
from .content import (
    ContentBaseSchema,
    SampleCreateSchema,
    SpecimenCreateSchema,
    ReagentCreateSchema,
    ControlCreateSchema,
    PoolCreateSchema,
    ContentUpdateSchema,
    ContentResponseSchema,
)
from .actions import (
    ActionParameterSchema,
    ActionGroupSchema,
    ActionBaseSchema,
    ActionCreateSchema,
    ActionExecuteSchema,
    ActionResultSchema,
    ActionResponseSchema,
    BulkActionExecuteSchema,
    BulkActionResultSchema,
)
from .files import (
    FileBaseSchema,
    FileUploadSchema,
    FileResponseSchema,
    FileSetBaseSchema,
    FileSetCreateSchema,
    FileSetResponseSchema,
    FileReferenceSchema,
    FileReferenceResponseSchema,
    FileSearchSchema,
)
from .equipment import (
    MaintenanceRecordSchema,
    CalibrationRecordSchema,
    EquipmentBaseSchema,
    EquipmentCreateSchema,
    EquipmentUpdateSchema,
    EquipmentResponseSchema,
    EquipmentRunSchema,
    EquipmentSearchSchema,
)

__all__ = [
    # Base schemas
    "BloomBaseSchema",
    "PaginationParams",
    "PaginatedResponse",
    "SuccessResponse",
    "ErrorResponse",
    "EUIDField",
    "validate_euid",
    "TimestampMixin",
    "AuditMixin",
    "DashboardStatsSchema",
    "RecentActivityItem",
    "RecentActivitySchema",
    "DashboardResponseSchema",
    # Object schemas
    "ObjectBaseSchema",
    "ObjectCreateSchema",
    "ObjectUpdateSchema",
    "ObjectResponseSchema",
    "ObjectQueryParams",
    "JsonAddlSchema",
    # Workflow schemas
    "WorkflowBaseSchema",
    "WorkflowCreateSchema",
    "WorkflowStepSchema",
    "WorkflowStepUpdateSchema",
    "WorkflowResponseSchema",
    "WorkflowStepResponseSchema",
    # Auth schemas
    "AuthLoginSchema",
    "AuthTokenSchema",
    "UserSchema",
    "UserCreateSchema",
    "UserUpdateSchema",
    "PasswordResetRequestSchema",
    "PasswordResetSchema",
    # Container schemas
    "ContainerLayoutSchema",
    "ContainerPositionSchema",
    "ContainerBaseSchema",
    "ContainerCreateSchema",
    "ContainerUpdateSchema",
    "ContainerResponseSchema",
    "PlaceInContainerSchema",
    "BulkPlaceInContainerSchema",
    # Content schemas
    "ContentBaseSchema",
    "SampleCreateSchema",
    "SpecimenCreateSchema",
    "ReagentCreateSchema",
    "ControlCreateSchema",
    "PoolCreateSchema",
    "ContentUpdateSchema",
    "ContentResponseSchema",
    # Action schemas
    "ActionParameterSchema",
    "ActionGroupSchema",
    "ActionBaseSchema",
    "ActionCreateSchema",
    "ActionExecuteSchema",
    "ActionResultSchema",
    "ActionResponseSchema",
    "BulkActionExecuteSchema",
    "BulkActionResultSchema",
    # File schemas
    "FileBaseSchema",
    "FileUploadSchema",
    "FileResponseSchema",
    "FileSetBaseSchema",
    "FileSetCreateSchema",
    "FileSetResponseSchema",
    "FileReferenceSchema",
    "FileReferenceResponseSchema",
    "FileSearchSchema",
    # Equipment schemas
    "MaintenanceRecordSchema",
    "CalibrationRecordSchema",
    "EquipmentBaseSchema",
    "EquipmentCreateSchema",
    "EquipmentUpdateSchema",
    "EquipmentResponseSchema",
    "EquipmentRunSchema",
    "EquipmentSearchSchema",
]

