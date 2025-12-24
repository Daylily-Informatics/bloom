"""
BLOOM LIMS - Laboratory Information Management System

A comprehensive LIMS solution for managing laboratory workflows,
samples, containers, and data.

Main modules:
    - config: Configuration management
    - exceptions: Custom exception classes
    - schemas: Pydantic schemas for validation
    - health: Health check endpoints
    - auth: Authentication and authorization
    - core: Core business logic modules
    - api: Versioned API endpoints
"""

__version__ = "0.1.0"

# Core imports for convenience
from bloom_lims.config import get_settings, BloomSettings

# Import exceptions - handle both old and new exception modules
try:
    from bloom_lims.exceptions import (
        BloomError,
        ValidationError,
        NotFoundError,
        AuthenticationError,
        AuthorizationError,
        DatabaseError,
        WorkflowError,
    )
except ImportError:
    # Fall back to core exceptions if old module doesn't exist
    from bloom_lims.core.exceptions import (
        BloomError,
        BloomValidationError as ValidationError,
        BloomNotFoundError as NotFoundError,
        BloomPermissionError as AuthenticationError,
        BloomPermissionError as AuthorizationError,
        BloomDatabaseError as DatabaseError,
        BloomWorkflowError as WorkflowError,
    )

# Alias for backward compatibility
Settings = BloomSettings

__all__ = [
    "__version__",
    "get_settings",
    "Settings",
    "BloomSettings",
    "BloomError",
    "ValidationError",
    "NotFoundError",
    "AuthenticationError",
    "AuthorizationError",
    "DatabaseError",
    "WorkflowError",
]
