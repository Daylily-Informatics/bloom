"""
BLOOM LIMS Exception Hierarchy

Provides a structured exception hierarchy for BLOOM LIMS operations.

Usage:
    from bloom_lims.core.exceptions import BloomNotFoundError, BloomValidationError
    
    try:
        obj = get_by_euid(euid)
    except BloomNotFoundError as e:
        logger.error(f"Object not found: {e.euid}")
    except BloomDatabaseError as e:
        logger.error(f"Database error: {e}")

Exception Hierarchy:
    BloomError (base)
    ├── BloomDatabaseError
    │   ├── BloomConnectionError
    │   ├── BloomTransactionError
    │   └── BloomIntegrityError
    ├── BloomNotFoundError
    ├── BloomValidationError
    ├── BloomPermissionError
    ├── BloomConfigurationError
    ├── BloomWorkflowError
    │   ├── BloomWorkflowStateError
    │   └── BloomWorkflowTransitionError
    └── BloomLineageError
"""

import logging
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


class BloomError(Exception):
    """
    Base exception for all BLOOM LIMS errors.
    
    Attributes:
        message: Human-readable error message
        details: Additional error details (dict)
        original_error: Original exception if wrapping another error
    """
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        self.message = message
        self.details = details or {}
        self.original_error = original_error
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        result = {
            "error_type": self.__class__.__name__,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        if self.original_error:
            result["original_error"] = str(self.original_error)
        return result


# Database Errors
class BloomDatabaseError(BloomError):
    """Base exception for database-related errors."""
    pass


class BloomConnectionError(BloomDatabaseError):
    """Exception raised when database connection fails."""
    
    def __init__(
        self,
        message: str = "Failed to connect to database",
        host: Optional[str] = None,
        port: Optional[int] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        if host:
            details["host"] = host
        if port:
            details["port"] = port
        super().__init__(message, details=details, **kwargs)


class BloomTransactionError(BloomDatabaseError):
    """Exception raised when a database transaction fails."""
    
    def __init__(
        self,
        message: str = "Transaction failed",
        operation: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        if operation:
            details["operation"] = operation
        super().__init__(message, details=details, **kwargs)


class BloomIntegrityError(BloomDatabaseError):
    """Exception raised when a database integrity constraint is violated."""
    
    def __init__(
        self,
        message: str = "Integrity constraint violated",
        constraint: Optional[str] = None,
        table: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        if constraint:
            details["constraint"] = constraint
        if table:
            details["table"] = table
        super().__init__(message, details=details, **kwargs)


# Not Found Errors
class BloomNotFoundError(BloomError):
    """Exception raised when a requested object is not found."""
    
    def __init__(
        self,
        message: str = "Object not found",
        euid: Optional[str] = None,
        uuid: Optional[str] = None,
        object_type: Optional[str] = None,
        **kwargs
    ):
        self.euid = euid
        self.uuid = uuid
        self.object_type = object_type
        
        details = kwargs.pop("details", {})
        if euid:
            details["euid"] = euid
        if uuid:
            details["uuid"] = uuid
        if object_type:
            details["object_type"] = object_type
        
        super().__init__(message, details=details, **kwargs)


# Validation Errors
class BloomValidationError(BloomError):
    """Exception raised when validation fails."""
    
    def __init__(
        self,
        message: str = "Validation failed",
        field: Optional[str] = None,
        value: Any = None,
        errors: Optional[List[str]] = None,
        **kwargs
    ):
        self.field = field
        self.value = value
        self.errors = errors or []
        
        details = kwargs.pop("details", {})
        if field:
            details["field"] = field
        if value is not None:
            details["value"] = str(value)
        if errors:
            details["errors"] = errors

        super().__init__(message, details=details, **kwargs)


# Permission Errors
class BloomPermissionError(BloomError):
    """Exception raised when permission is denied."""

    def __init__(
        self,
        message: str = "Permission denied",
        user: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        **kwargs
    ):
        self.user = user
        self.action = action
        self.resource = resource

        details = kwargs.pop("details", {})
        if user:
            details["user"] = user
        if action:
            details["action"] = action
        if resource:
            details["resource"] = resource

        super().__init__(message, details=details, **kwargs)


# Configuration Errors
class BloomConfigurationError(BloomError):
    """Exception raised when configuration is invalid."""

    def __init__(
        self,
        message: str = "Configuration error",
        config_key: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
        **kwargs
    ):
        self.config_key = config_key

        details = kwargs.pop("details", {})
        if config_key:
            details["config_key"] = config_key
        if expected:
            details["expected"] = expected
        if actual:
            details["actual"] = actual

        super().__init__(message, details=details, **kwargs)


# Workflow Errors
class BloomWorkflowError(BloomError):
    """Base exception for workflow-related errors."""

    def __init__(
        self,
        message: str = "Workflow error",
        workflow_euid: Optional[str] = None,
        **kwargs
    ):
        self.workflow_euid = workflow_euid

        details = kwargs.pop("details", {})
        if workflow_euid:
            details["workflow_euid"] = workflow_euid

        super().__init__(message, details=details, **kwargs)


class BloomWorkflowStateError(BloomWorkflowError):
    """Exception raised when workflow is in an invalid state."""

    def __init__(
        self,
        message: str = "Invalid workflow state",
        current_state: Optional[str] = None,
        expected_state: Optional[str] = None,
        **kwargs
    ):
        self.current_state = current_state
        self.expected_state = expected_state

        details = kwargs.pop("details", {})
        if current_state:
            details["current_state"] = current_state
        if expected_state:
            details["expected_state"] = expected_state

        super().__init__(message, details=details, **kwargs)


class BloomWorkflowTransitionError(BloomWorkflowError):
    """Exception raised when a workflow transition is invalid."""

    def __init__(
        self,
        message: str = "Invalid workflow transition",
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        **kwargs
    ):
        self.from_state = from_state
        self.to_state = to_state

        details = kwargs.pop("details", {})
        if from_state:
            details["from_state"] = from_state
        if to_state:
            details["to_state"] = to_state

        super().__init__(message, details=details, **kwargs)


# Lineage Errors
class BloomLineageError(BloomError):
    """Exception raised for lineage-related errors."""

    def __init__(
        self,
        message: str = "Lineage error",
        parent_euid: Optional[str] = None,
        child_euid: Optional[str] = None,
        **kwargs
    ):
        self.parent_euid = parent_euid
        self.child_euid = child_euid

        details = kwargs.pop("details", {})
        if parent_euid:
            details["parent_euid"] = parent_euid
        if child_euid:
            details["child_euid"] = child_euid

        super().__init__(message, details=details, **kwargs)


# Singleton Error
class BloomSingletonError(BloomError):
    """Exception raised when singleton constraint is violated."""

    def __init__(
        self,
        message: str = "Singleton constraint violated",
        template_euid: Optional[str] = None,
        existing_instance_euid: Optional[str] = None,
        **kwargs
    ):
        self.template_euid = template_euid
        self.existing_instance_euid = existing_instance_euid

        details = kwargs.pop("details", {})
        if template_euid:
            details["template_euid"] = template_euid
        if existing_instance_euid:
            details["existing_instance_euid"] = existing_instance_euid

        super().__init__(message, details=details, **kwargs)
