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

from bloom_lims._version import __version__, get_version

# Core imports for convenience
from bloom_lims.config import BloomSettings, get_settings
from bloom_lims.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BloomError,
    DatabaseError,
    NotFoundError,
    ValidationError,
    WorkflowError,
)

__all__ = [
    "__version__",
    "get_version",
    "get_settings",
    "BloomSettings",
    "BloomError",
    "ValidationError",
    "NotFoundError",
    "AuthenticationError",
    "AuthorizationError",
    "DatabaseError",
    "WorkflowError",
]
