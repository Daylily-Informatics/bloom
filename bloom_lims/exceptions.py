"""
BLOOM LIMS Custom Exception Hierarchy

This module provides a standardized exception hierarchy for the BLOOM LIMS system.
All custom exceptions inherit from BloomError, enabling consistent error handling
and logging throughout the application.

Usage:
    from bloom_lims.exceptions import ValidationError, NotFoundError
    
    if not is_valid_euid(euid):
        raise ValidationError(f"Invalid EUID format: {euid}", field="euid")
    
    obj = get_by_euid(euid)
    if obj is None:
        raise NotFoundError(f"Object not found", resource_type="instance", resource_id=euid)
"""

import logging
from typing import Any, Dict, Optional
from datetime import datetime


logger = logging.getLogger(__name__)


class BloomError(Exception):
    """
    Base exception for all BLOOM LIMS errors.
    
    Provides structured error information including:
    - Error code for programmatic handling
    - Detailed message for logging
    - Optional context data for debugging
    - Timestamp for error tracking
    
    Args:
        message: Human-readable error description
        error_code: Machine-readable error code (default: BLOOM_ERROR)
        details: Additional context data for debugging
        cause: Original exception that caused this error
    """
    
    default_error_code = "BLOOM_ERROR"
    default_http_status = 500
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        self.message = message
        self.error_code = error_code or self.default_error_code
        self.details = details or {}
        self.cause = cause
        self.timestamp = datetime.utcnow().isoformat()
        self.http_status = self.default_http_status
        
        super().__init__(self.message)
        
        # Log the error with structured data
        self._log_error()
    
    def _log_error(self) -> None:
        """Log error with structured format."""
        log_data = {
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details,
        }
        if self.cause:
            log_data["cause"] = str(self.cause)
        
        logger.error(f"BloomError: {self.error_code} - {self.message}", extra=log_data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        result = {
            "error": True,
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp,
        }
        if self.details:
            result["details"] = self.details
        return result
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.error_code}, message={self.message})"


class ValidationError(BloomError):
    """
    Raised when input validation fails.
    
    Args:
        message: Description of validation failure
        field: Name of the field that failed validation
        value: The invalid value (will be sanitized in logs)
        constraints: Description of validation constraints
    """
    
    default_error_code = "VALIDATION_ERROR"
    default_http_status = 400
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        constraints: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if field:
            details["field"] = field
        if value is not None:
            # Sanitize value for logging (truncate long values)
            str_value = str(value)
            details["value"] = str_value[:100] + "..." if len(str_value) > 100 else str_value
        if constraints:
            details["constraints"] = constraints
        
        super().__init__(message, details=details, **kwargs)


class DatabaseError(BloomError):
    """
    Raised when database operations fail.

    Args:
        message: Description of database error
        operation: The database operation that failed (query, insert, update, delete)
        table: The table involved in the operation
    """

    default_error_code = "DATABASE_ERROR"
    default_http_status = 500

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        table: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if operation:
            details["operation"] = operation
        if table:
            details["table"] = table

        super().__init__(message, details=details, **kwargs)


class SessionError(DatabaseError):
    """
    Raised when database session management fails.

    Used for connection issues, session lifecycle problems, and transaction errors.
    """

    default_error_code = "SESSION_ERROR"
    default_http_status = 500


class AuthenticationError(BloomError):
    """
    Raised when authentication fails.

    Args:
        message: Description of authentication failure
        username: The username that failed authentication (optional)
        auth_method: The authentication method used
    """

    default_error_code = "AUTHENTICATION_ERROR"
    default_http_status = 401

    def __init__(
        self,
        message: str,
        username: Optional[str] = None,
        auth_method: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if username:
            details["username"] = username
        if auth_method:
            details["auth_method"] = auth_method

        super().__init__(message, details=details, **kwargs)


class AuthorizationError(BloomError):
    """
    Raised when user lacks required permissions.

    Args:
        message: Description of authorization failure
        user_id: The user who was denied access
        resource: The resource access was denied to
        required_permission: The permission that was required
    """

    default_error_code = "AUTHORIZATION_ERROR"
    default_http_status = 403

    def __init__(
        self,
        message: str,
        user_id: Optional[str] = None,
        resource: Optional[str] = None,
        required_permission: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if user_id:
            details["user_id"] = user_id
        if resource:
            details["resource"] = resource
        if required_permission:
            details["required_permission"] = required_permission

        super().__init__(message, details=details, **kwargs)


class NotFoundError(BloomError):
    """
    Raised when a requested resource cannot be found.

    Args:
        message: Description of what was not found
        resource_type: Type of resource (instance, template, lineage, etc.)
        resource_id: Identifier of the resource (EUID, UUID, etc.)
    """

    default_error_code = "NOT_FOUND"
    default_http_status = 404

    def __init__(
        self,
        message: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if resource_type:
            details["resource_type"] = resource_type
        if resource_id:
            details["resource_id"] = resource_id

        super().__init__(message, details=details, **kwargs)


class DuplicateError(BloomError):
    """
    Raised when attempting to create a duplicate resource.

    Args:
        message: Description of duplicate conflict
        resource_type: Type of resource
        identifier: The conflicting identifier
    """

    default_error_code = "DUPLICATE_ERROR"
    default_http_status = 409

    def __init__(
        self,
        message: str,
        resource_type: Optional[str] = None,
        identifier: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if resource_type:
            details["resource_type"] = resource_type
        if identifier:
            details["identifier"] = identifier

        super().__init__(message, details=details, **kwargs)


class ConfigurationError(BloomError):
    """
    Raised when configuration is invalid or missing.

    Args:
        message: Description of configuration error
        config_key: The configuration key that is problematic
        expected: What was expected
    """

    default_error_code = "CONFIGURATION_ERROR"
    default_http_status = 500

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        expected: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if config_key:
            details["config_key"] = config_key
        if expected:
            details["expected"] = expected

        super().__init__(message, details=details, **kwargs)


class WorkflowError(BloomError):
    """
    Raised when workflow operations fail.

    Args:
        message: Description of workflow error
        workflow_euid: EUID of the workflow
        step_euid: EUID of the workflow step (if applicable)
        action: The action that failed
    """

    default_error_code = "WORKFLOW_ERROR"
    default_http_status = 400

    def __init__(
        self,
        message: str,
        workflow_euid: Optional[str] = None,
        step_euid: Optional[str] = None,
        action: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if workflow_euid:
            details["workflow_euid"] = workflow_euid
        if step_euid:
            details["step_euid"] = step_euid
        if action:
            details["action"] = action

        super().__init__(message, details=details, **kwargs)


class StorageError(BloomError):
    """
    Raised when file/object storage operations fail.

    Args:
        message: Description of storage error
        storage_type: Type of storage (S3, local, etc.)
        path: The path or key that had issues
        operation: The operation that failed
    """

    default_error_code = "STORAGE_ERROR"
    default_http_status = 500

    def __init__(
        self,
        message: str,
        storage_type: Optional[str] = None,
        path: Optional[str] = None,
        operation: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if storage_type:
            details["storage_type"] = storage_type
        if path:
            details["path"] = path
        if operation:
            details["operation"] = operation

        super().__init__(message, details=details, **kwargs)


class ExternalServiceError(BloomError):
    """
    Raised when external service calls fail.

    Args:
        message: Description of external service error
        service_name: Name of the external service
        endpoint: The endpoint that was called
        status_code: HTTP status code from the service (if applicable)
    """

    default_error_code = "EXTERNAL_SERVICE_ERROR"
    default_http_status = 502

    def __init__(
        self,
        message: str,
        service_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        if service_name:
            details["service_name"] = service_name
        if endpoint:
            details["endpoint"] = endpoint
        if status_code is not None:
            details["status_code"] = status_code

        super().__init__(message, details=details, **kwargs)


# Convenience function for creating error responses in FastAPI
def create_error_response(error: BloomError) -> Dict[str, Any]:
    """
    Create a standardized error response dictionary for FastAPI.

    Args:
        error: The BloomError instance

    Returns:
        Dictionary suitable for JSONResponse
    """
    return {
        "success": False,
        "error": error.to_dict(),
    }
