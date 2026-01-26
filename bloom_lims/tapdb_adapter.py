"""
BLOOM ↔ TapDB Adapter Module.

This module provides compatibility between BLOOM's existing API and daylily-tapdb.
It implements:
1. Field name translation via SQLAlchemy synonyms (super_type ↔ category, etc.)
2. Class aliases for BLOOM-specific names (file_set_instance → file_instance)
3. BLOOMdb3 wrapper that preserves BLOOM's public API

Phase 1 of BLOOM Database Refactor Plan.
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker, Session, synonym

# Import TapDB models
from daylily_tapdb.models.base import Base as TapDBBase, tapdb_core
from daylily_tapdb.models.audit import audit_log
from daylily_tapdb.models.template import (
    generic_template,
    workflow_template,
    workflow_step_template,
    container_template,
    content_template,
    equipment_template,
    data_template,
    test_requisition_template,
    actor_template,
    action_template,
    health_event_template,
    file_template,
    subject_template,
)
from daylily_tapdb.models.instance import (
    generic_instance,
    workflow_instance,
    workflow_step_instance,
    container_instance,
    content_instance,
    equipment_instance,
    data_instance,
    test_requisition_instance,
    actor_instance,
    action_instance,
    health_event_instance,
    file_instance,
    subject_instance,
)
from daylily_tapdb.models.lineage import (
    generic_instance_lineage,
    workflow_instance_lineage,
    workflow_step_instance_lineage,
    container_instance_lineage,
    content_instance_lineage,
    equipment_instance_lineage,
    data_instance_lineage,
    test_requisition_instance_lineage,
    actor_instance_lineage,
    action_instance_lineage,
    health_event_instance_lineage,
    file_instance_lineage,
    subject_instance_lineage,
)


# =============================================================================
# Field Compatibility: SQLAlchemy synonyms for BLOOM field names
# =============================================================================
# BLOOM uses: super_type, btype, b_sub_type
# TapDB uses: category, type, subtype
#
# We use hybrid_property to create aliases that work both for:
# - Instance attribute access: obj.super_type
# - Query filter expressions: cls.super_type == 'file'
#
# Note: synonym() doesn't work for filter expressions - it generates Python
# boolean comparisons instead of SQL expressions.
# =============================================================================
from sqlalchemy.ext.hybrid import hybrid_property


def _add_bloom_field_aliases(cls):
    """
    Add BLOOM field aliases (super_type, btype, b_sub_type) to a TapDB class.

    Uses hybrid_property so the aliases work both for:
    - Instance attribute access: obj.super_type (getter/setter)
    - Query filter expressions: Model.super_type == 'value'

    This must be called on each concrete class (not just the base) because
    hybrid_property needs to reference the actual Column objects.
    """
    # super_type -> category
    @hybrid_property
    def super_type(self):
        return self.category

    @super_type.setter
    def super_type(self, value):
        self.category = value

    @super_type.expression
    def super_type(cls):
        return cls.category

    # btype -> type
    @hybrid_property
    def btype(self):
        return self.type

    @btype.setter
    def btype(self, value):
        self.type = value

    @btype.expression
    def btype(cls):
        return cls.type

    # b_sub_type -> subtype
    @hybrid_property
    def b_sub_type(self):
        return self.subtype

    @b_sub_type.setter
    def b_sub_type(self, value):
        self.subtype = value

    @b_sub_type.expression
    def b_sub_type(cls):
        return cls.subtype

    # Attach to class
    cls.super_type = super_type
    cls.btype = btype
    cls.b_sub_type = b_sub_type

    return cls


# Apply BLOOM field aliases to the base class - inherited by all subclasses
_add_bloom_field_aliases(tapdb_core)


# =============================================================================
# Constructor Compatibility: Translate BLOOM field names in __init__
# =============================================================================
# SQLAlchemy synonyms only work for attribute access, not constructor kwargs.
# We need to intercept __init__ to translate super_type→category, etc.
# =============================================================================

def _translate_bloom_kwargs(kwargs: dict) -> dict:
    """Translate BLOOM field names to TapDB field names in kwargs."""
    translations = {
        "super_type": "category",
        "btype": "type",
        "b_sub_type": "subtype",
    }
    result = {}
    for key, value in kwargs.items():
        translated_key = translations.get(key, key)
        result[translated_key] = value
    return result


def _patch_init_for_bloom_compat(cls):
    """
    Patch a TapDB class's __init__ to accept BLOOM field names.

    This modifies the class in-place to translate super_type→category,
    btype→type, b_sub_type→subtype in constructor calls.

    This approach preserves the class identity so it works with:
    - session.query(cls)
    - cls.column_name == value filters
    - cls(**kwargs) instantiation with BLOOM field names
    """
    original_init = cls.__init__

    def patched_init(self, **kwargs):
        translated = _translate_bloom_kwargs(kwargs)
        original_init(self, **translated)

    cls.__init__ = patched_init
    return cls


# =============================================================================
# Class Compatibility: Aliases for BLOOM-specific class names
# =============================================================================
# BLOOM references Base.classes.file_set_instance but TapDB doesn't define it.
# We alias these to the corresponding TapDB classes.
# =============================================================================

# Template aliases
file_set_template = file_template
file_reference_template = file_template

# Instance aliases
file_set_instance = file_instance
file_reference_instance = file_instance

# Lineage aliases
file_set_instance_lineage = file_instance_lineage
file_reference_instance_lineage = file_instance_lineage


# =============================================================================
# Alias tapdb_core as bloom_core for BLOOM compatibility
# =============================================================================
bloom_core = tapdb_core

# Use TapDB's Base
Base = TapDBBase


# =============================================================================
# BLOOMdb3: Database connection manager preserving BLOOM's public API
# =============================================================================

class _TransactionContext:
    """
    Context manager for database transactions.
    Provides automatic commit on success and rollback on failure.
    """

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__ + "._TransactionContext")

    def __enter__(self) -> Session:
        """Begin transaction and return session."""
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """End transaction - commit or rollback."""
        if exc_type is not None:
            self.logger.warning(f"Transaction rollback due to: {exc_type.__name__}: {exc_val}")
            self.session.rollback()
        else:
            try:
                self.session.commit()
                self.logger.debug("Transaction committed")
            except Exception as e:
                self.logger.error(f"Commit failed, rolling back: {e}")
                self.session.rollback()
                raise
        return False  # Don't suppress exceptions


class BLOOMdb3:
    """
    BLOOM LIMS Database Connection Manager (TapDB-backed).

    Preserves BLOOM's public API while using TapDB models underneath.

    Usage:
        # Standard usage
        bdb = BLOOMdb3()
        result = bdb.session.query(...)
        bdb.close()

        # Context manager (recommended)
        with BLOOMdb3() as bdb:
            result = bdb.session.query(...)

        # Transaction context
        with bdb.transaction() as session:
            session.add(obj)
    """

    def __init__(
        self,
        db_url_prefix: str = "postgresql://",
        db_hostname: str = "localhost:" + os.environ.get("PGPORT", "5445"),
        db_pass: str = (
            None if "PGPASSWORD" not in os.environ else os.environ.get("PGPASSWORD")
        ),
        db_user: str = os.environ.get("USER", "bloom"),
        db_name: str = "bloom",
        app_username: str = os.environ.get("USER", "bloomdborm"),
        echo_sql: bool = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 1800,
    ):
        """Initialize database connection with BLOOM-compatible defaults."""
        self.logger = logging.getLogger(__name__ + ".BLOOMdb3")
        self.logger.debug("STARTING BLOOMDB3 (TapDB-backed)")
        self.app_username = app_username
        self._owns_session = True

        # Resolve echo_sql from environment if not explicitly set
        if echo_sql is None:
            echo_env = os.environ.get("ECHO_SQL", "").lower()
            echo_sql = echo_env in ("true", "1", "yes")

        # Build database URL
        db_url = f"{db_url_prefix}{db_user}:{db_pass}@{db_hostname}/{db_name}"

        # Create engine with connection pooling
        self.engine = create_engine(
            db_url,
            echo=echo_sql,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,
        )

        # Create session factory
        self._Session = sessionmaker(bind=self.engine)

        # Create metadata and automap base for compatibility
        metadata = MetaData()
        self.Base = automap_base(metadata=metadata)

        # Create session
        self.session = self._Session()

        # Set application username for audit logging
        self._set_session_username()

        # Reflect tables (for any tables not in TapDB models)
        self.Base.prepare(autoload_with=self.engine)

        # Register ORM classes
        self._register_orm_classes()

    def _set_session_username(self) -> None:
        """Set the session username for audit logging."""
        try:
            set_current_username_sql = text("SET session.current_username = :username")
            self.session.execute(set_current_username_sql, {"username": self.app_username})
            self.session.commit()
        except Exception as e:
            self.logger.warning(f"Could not set session username: {e}")

    def _register_orm_classes(self) -> None:
        """Register TapDB ORM classes with the automap base."""
        classes_to_register = [
            # Generic classes
            generic_template,
            generic_instance,
            generic_instance_lineage,
            # Typed templates
            workflow_template,
            workflow_step_template,
            container_template,
            content_template,
            equipment_template,
            data_template,
            test_requisition_template,
            actor_template,
            action_template,
            health_event_template,
            file_template,
            subject_template,
            # Typed instances
            workflow_instance,
            workflow_step_instance,
            container_instance,
            content_instance,
            equipment_instance,
            data_instance,
            test_requisition_instance,
            actor_instance,
            action_instance,
            health_event_instance,
            file_instance,
            subject_instance,
            # Typed lineages
            workflow_instance_lineage,
            workflow_step_instance_lineage,
            container_instance_lineage,
            content_instance_lineage,
            equipment_instance_lineage,
            data_instance_lineage,
            test_requisition_instance_lineage,
            actor_instance_lineage,
            action_instance_lineage,
            health_event_instance_lineage,
            file_instance_lineage,
            subject_instance_lineage,
            # Audit
            audit_log,
        ]
        for cls in classes_to_register:
            class_name = cls.__name__
            # Patch __init__ to accept BLOOM field names, then register
            _patch_init_for_bloom_compat(cls)
            setattr(self.Base.classes, class_name, cls)

        # Register BLOOM-specific aliases (classes already patched above)
        setattr(self.Base.classes, "file_set_template", file_template)
        setattr(self.Base.classes, "file_reference_template", file_template)
        setattr(self.Base.classes, "file_set_instance", file_instance)
        setattr(self.Base.classes, "file_reference_instance", file_instance)
        setattr(self.Base.classes, "file_set_instance_lineage", file_instance_lineage)
        setattr(self.Base.classes, "file_reference_instance_lineage", file_instance_lineage)

    def __enter__(self) -> "BLOOMdb3":
        """Context manager entry - returns self."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit - ensures proper cleanup."""
        if exc_type is not None:
            self.logger.warning(f"Exception in context: {exc_type.__name__}: {exc_val}")
            self.session.rollback()
        self.close()
        return False

    def transaction(self):
        """
        Get a transaction context manager for atomic operations.

        Returns:
            Transaction context manager
        """
        return _TransactionContext(self.session)

    def new_session(self) -> Session:
        """
        Create a new session from the factory.
        Caller is responsible for closing the session.
        """
        session = self._Session()
        try:
            set_current_username_sql = text("SET session.current_username = :username")
            session.execute(set_current_username_sql, {"username": self.app_username})
            session.commit()
        except Exception as e:
            self.logger.warning(f"Could not set session username on new session: {e}")
        return session

    def close(self) -> None:
        """Close the session and dispose of the engine."""
        if self.session:
            try:
                self.session.close()
                self.logger.debug("Session closed")
            except Exception as e:
                self.logger.warning(f"Error closing session: {e}")

        if self.engine and self._owns_session:
            try:
                self.engine.dispose()
                self.logger.debug("Engine disposed")
            except Exception as e:
                self.logger.warning(f"Error disposing engine: {e}")


# =============================================================================
# Public API exports
# =============================================================================
__all__ = [
    # Core
    "Base",
    "bloom_core",
    "tapdb_core",
    "BLOOMdb3",
    # Generic classes
    "generic_template",
    "generic_instance",
    "generic_instance_lineage",
    # Typed templates
    "workflow_template",
    "workflow_step_template",
    "container_template",
    "content_template",
    "equipment_template",
    "data_template",
    "test_requisition_template",
    "actor_template",
    "action_template",
    "health_event_template",
    "file_template",
    "subject_template",
    # Typed instances
    "workflow_instance",
    "workflow_step_instance",
    "container_instance",
    "content_instance",
    "equipment_instance",
    "data_instance",
    "test_requisition_instance",
    "actor_instance",
    "action_instance",
    "health_event_instance",
    "file_instance",
    "subject_instance",
    # Typed lineages
    "workflow_instance_lineage",
    "workflow_step_instance_lineage",
    "container_instance_lineage",
    "content_instance_lineage",
    "equipment_instance_lineage",
    "data_instance_lineage",
    "test_requisition_instance_lineage",
    "actor_instance_lineage",
    "action_instance_lineage",
    "health_event_instance_lineage",
    "file_instance_lineage",
    "subject_instance_lineage",
    # BLOOM-specific aliases
    "file_set_template",
    "file_reference_template",
    "file_set_instance",
    "file_reference_instance",
    "file_set_instance_lineage",
    "file_reference_instance_lineage",
    # Audit
    "audit_log",
]

