"""
BLOOM LIMS Core Module

This module contains the core domain objects for BLOOM LIMS, organized into
focused submodules.

Submodules:
    - base_objects: BloomObj base class and common methods
    - workflows: BloomWorkflow and BloomWorkflowStep classes
    - content: Content and sample management
    - validation: Input validation utilities
    - exceptions: Custom exception hierarchy
    - cache: Caching utilities

Usage:
    # Core imports
    from bloom_lims.core import BloomObj, BloomWorkflow

    # Validation
    from bloom_lims.core.validation import validate_euid, validated

    # Exceptions
    from bloom_lims.core.exceptions import BloomNotFoundError

    # Caching
    from bloom_lims.core.cache import cached, get_cache_stats
"""

# Async operations
from .async_operations import (
    AsyncDatabaseSession,
    BackgroundTaskManager,
    TaskResult,
    TaskStatus,
    async_bulk_insert,
    async_query,
    get_task_manager,
    parallel_execute,
    run_async,
    run_in_background,
)
from .base_objects import (
    BloomObj,
    BloomObjMixin,
    create_bloom_obj,
    get_bloom_obj_by_euid,
)

# Batch operations
from .batch_operations import (
    BatchJob,
    BatchProcessor,
    BatchProgress,
    JobStatus,
    bulk_create,
    bulk_delete,
    bulk_update,
    get_batch_processor,
)

# Caching utilities
from .cache import (
    CacheStats,
    LRUCache,
    cache_clear,
    cache_invalidate,
    cached,
    cached_method,
    create_cache,
    get_cache_stats,
    get_global_cache,
)

# Cache backends (Redis/Memcached)
from .cache_backends import (
    CacheBackend,
    MemcachedCache,
    RedisCache,
    get_cache_backend,
)

# Cached repository
from .cached_repository import CachedRepository
from .content import (
    BloomContent,
    BloomSample,
    create_aliquot,
    create_sample,
    get_sample_by_euid,
    get_sample_lineage,
)

# Exception hierarchy
from .exceptions import (
    BloomConfigurationError,
    BloomConnectionError,
    BloomDatabaseError,
    BloomError,
    BloomIntegrityError,
    BloomLineageError,
    BloomNotFoundError,
    BloomPermissionError,
    BloomSingletonError,
    BloomTransactionError,
    BloomValidationError,
    BloomWorkflowError,
    BloomWorkflowStateError,
    BloomWorkflowTransitionError,
)

# Read replica support
from .read_replicas import (
    ReplicaConfig,
    ReplicaRouter,
    ReplicaStatus,
    configure_replicas,
    get_replica_router,
)

# Template validation
from .template_validation import (
    TemplateDefinition,
    TemplateValidator,
    ValidationResult,
)

# Validation utilities
from .validation import (
    ValidationError,
    validate_euid,
    validate_json_addl,
    validate_not_empty,
    validate_positive_int,
    validate_schema,
    validate_type,
    validated,
)
from .workflows import (
    BloomWorkflow,
    BloomWorkflowStep,
    advance_workflow,
    create_workflow,
    create_workflow_step,
    get_workflow_by_euid,
    get_workflow_steps,
)

__all__ = [
    # Base objects
    "BloomObj",
    "BloomObjMixin",
    "create_bloom_obj",
    "get_bloom_obj_by_euid",
    # Workflows
    "BloomWorkflow",
    "BloomWorkflowStep",
    "create_workflow",
    "create_workflow_step",
    "get_workflow_by_euid",
    "get_workflow_steps",
    "advance_workflow",
    # Content
    "BloomContent",
    "BloomSample",
    "create_sample",
    "get_sample_by_euid",
    "create_aliquot",
    "get_sample_lineage",
    # Validation
    "ValidationError",
    "validate_euid",
    "validate_json_addl",
    "validate_type",
    "validate_not_empty",
    "validate_positive_int",
    "validated",
    "validate_schema",
    # Exceptions
    "BloomError",
    "BloomDatabaseError",
    "BloomConnectionError",
    "BloomTransactionError",
    "BloomIntegrityError",
    "BloomNotFoundError",
    "BloomValidationError",
    "BloomPermissionError",
    "BloomConfigurationError",
    "BloomWorkflowError",
    "BloomWorkflowStateError",
    "BloomWorkflowTransitionError",
    "BloomLineageError",
    "BloomSingletonError",
    # Cache
    "cached",
    "cached_method",
    "cache_invalidate",
    "cache_clear",
    "get_cache_stats",
    "get_global_cache",
    "create_cache",
    "LRUCache",
    "CacheStats",
    # Template validation
    "TemplateValidator",
    "ValidationResult",
    "TemplateDefinition",
    # Cached repository
    "CachedRepository",
    # Cache backends
    "CacheBackend",
    "RedisCache",
    "MemcachedCache",
    "get_cache_backend",
    # Read replicas
    "ReplicaRouter",
    "ReplicaConfig",
    "ReplicaStatus",
    "get_replica_router",
    "configure_replicas",
    # Async operations
    "AsyncDatabaseSession",
    "BackgroundTaskManager",
    "TaskResult",
    "TaskStatus",
    "async_query",
    "async_bulk_insert",
    "get_task_manager",
    "run_async",
    "run_in_background",
    "parallel_execute",
    # Batch operations
    "BatchProcessor",
    "BatchJob",
    "BatchProgress",
    "JobStatus",
    "bulk_create",
    "bulk_update",
    "bulk_delete",
    "get_batch_processor",
]
