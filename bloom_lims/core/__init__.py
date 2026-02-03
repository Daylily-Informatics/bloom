"""
BLOOM LIMS Core Module

This module contains the core domain objects for BLOOM LIMS, organized into
focused submodules. For backward compatibility, all classes are re-exported
from this module and from bloom_lims.bobjs.

Submodules:
    - base_objects: BloomObj base class and common methods
    - workflows: BloomWorkflow and BloomWorkflowStep classes
    - containers: Container-related functionality
    - content: Content and sample management
    - lineage: Lineage tracking
    - validation: Input validation utilities
    - exceptions: Custom exception hierarchy
    - cache: Caching utilities

Usage:
    # New style (recommended)
    from bloom_lims.core import BloomObj, BloomWorkflow

    # Legacy style (backward compatible)
    from bloom_lims.bobjs import BloomObj, BloomWorkflow

    # Validation
    from bloom_lims.core.validation import validate_euid, validated

    # Exceptions
    from bloom_lims.core.exceptions import BloomNotFoundError

    # Caching
    from bloom_lims.core.cache import cached, get_cache_stats
"""

from .base_objects import (
    BloomObj,
    BloomObjMixin,
    create_bloom_obj,
    get_bloom_obj_by_euid,
    get_bloom_obj_by_uuid,
)

from .workflows import (
    BloomWorkflow,
    BloomWorkflowStep,
    create_workflow,
    create_workflow_step,
    get_workflow_by_euid,
    get_workflow_steps,
    advance_workflow,
)

from .containers import (
    BloomContainer,
    ContainerPosition,
    get_container_layout,
    get_container_contents,
    place_in_container,
    remove_from_container,
)

from .content import (
    BloomContent,
    BloomSample,
    create_sample,
    get_sample_by_euid,
    create_aliquot,
    get_sample_lineage,
)

from .lineage import (
    BloomLineage,
    create_lineage,
    get_lineage_by_euid,
    get_lineage_tree,
    add_to_lineage,
    get_object_lineage,
)

# Validation utilities
from .validation import (
    ValidationError,
    validate_euid,
    validate_uuid,
    validate_json_addl,
    validate_type,
    validate_btype,  # Backward compatibility alias
    validate_not_empty,
    validate_positive_int,
    validated,
    validate_schema,
)

# Exception hierarchy
from .exceptions import (
    BloomError,
    BloomDatabaseError,
    BloomConnectionError,
    BloomTransactionError,
    BloomIntegrityError,
    BloomNotFoundError,
    BloomValidationError,
    BloomPermissionError,
    BloomConfigurationError,
    BloomWorkflowError,
    BloomWorkflowStateError,
    BloomWorkflowTransitionError,
    BloomLineageError,
    BloomSingletonError,
)

# Caching utilities
from .cache import (
    cached,
    cached_method,
    cache_invalidate,
    cache_clear,
    get_cache_stats,
    get_global_cache,
    create_cache,
    LRUCache,
    CacheStats,
)

# Template validation
from .template_validation import (
    TemplateValidator,
    ValidationResult,
    TemplateDefinition,
)

# Cached repository
from .cached_repository import CachedRepository

# Cache backends (Redis/Memcached)
from .cache_backends import (
    CacheBackend,
    RedisCache,
    MemcachedCache,
    get_cache_backend,
)

# Read replica support
from .read_replicas import (
    ReplicaRouter,
    ReplicaConfig,
    ReplicaStatus,
    get_replica_router,
    configure_replicas,
)

# Async operations
from .async_operations import (
    AsyncDatabaseSession,
    BackgroundTaskManager,
    TaskResult,
    TaskStatus,
    get_task_manager,
    run_async,
    run_in_background,
    parallel_execute,
)

# Batch operations
from .batch_operations import (
    BatchProcessor,
    BatchJob,
    BatchProgress,
    JobStatus,
    bulk_create,
    bulk_update,
    bulk_delete,
    get_batch_processor,
)

__all__ = [
    # Base objects
    "BloomObj",
    "BloomObjMixin",
    "create_bloom_obj",
    "get_bloom_obj_by_euid",
    "get_bloom_obj_by_uuid",
    # Workflows
    "BloomWorkflow",
    "BloomWorkflowStep",
    "create_workflow",
    "create_workflow_step",
    "get_workflow_by_euid",
    "get_workflow_steps",
    "advance_workflow",
    # Containers
    "BloomContainer",
    "ContainerPosition",
    "get_container_layout",
    "get_container_contents",
    "place_in_container",
    "remove_from_container",
    # Content
    "BloomContent",
    "BloomSample",
    "create_sample",
    "get_sample_by_euid",
    "create_aliquot",
    "get_sample_lineage",
    # Lineage
    "BloomLineage",
    "create_lineage",
    "get_lineage_by_euid",
    "get_lineage_tree",
    "add_to_lineage",
    "get_object_lineage",
    # Validation
    "ValidationError",
    "validate_euid",
    "validate_uuid",
    "validate_json_addl",
    "validate_type",
    "validate_btype",  # Backward compatibility alias
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

