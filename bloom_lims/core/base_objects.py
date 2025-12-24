"""
BLOOM LIMS Base Objects Module

This module contains the BloomObj base class and common utility functions
for working with BLOOM LIMS objects.

For backward compatibility, this module re-exports functionality that was
originally in bloom_lims/bobjs.py.
"""

import logging
from typing import Any, Dict, List, Optional, Type, Union
from datetime import datetime

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from bloom_lims.exceptions import (
    NotFoundError,
    ValidationError,
    DatabaseError,
)


logger = logging.getLogger(__name__)


class BloomObjMixin:
    """
    Mixin class providing common functionality for BLOOM objects.
    
    This mixin can be used to add standard BLOOM object methods to
    any SQLAlchemy model class.
    """
    
    @property
    def is_template(self) -> bool:
        """Check if this object is a template."""
        return hasattr(self, 'polymorphic_discriminator') and \
               self.polymorphic_discriminator and \
               '_template' in self.polymorphic_discriminator
    
    @property
    def is_instance(self) -> bool:
        """Check if this object is an instance."""
        return hasattr(self, 'polymorphic_discriminator') and \
               self.polymorphic_discriminator and \
               '_instance' in self.polymorphic_discriminator
    
    def get_json_addl_value(self, key: str, default: Any = None) -> Any:
        """
        Safely get a value from json_addl.
        
        Args:
            key: The key to look up
            default: Default value if key not found
            
        Returns:
            The value or default
        """
        if hasattr(self, 'json_addl') and self.json_addl:
            return self.json_addl.get(key, default)
        return default
    
    def set_json_addl_value(self, key: str, value: Any) -> None:
        """
        Set a value in json_addl.
        
        Args:
            key: The key to set
            value: The value to set
        """
        if not hasattr(self, 'json_addl') or self.json_addl is None:
            self.json_addl = {}
        self.json_addl[key] = value
    
    def merge_json_addl(self, data: Dict[str, Any]) -> None:
        """
        Merge data into json_addl recursively.
        
        Args:
            data: Dictionary to merge into json_addl
        """
        if not hasattr(self, 'json_addl') or self.json_addl is None:
            self.json_addl = {}
        _update_recursive(self.json_addl, data)


def _update_recursive(orig_dict: Dict, update_with: Dict) -> None:
    """
    Recursively update a dictionary.
    
    Args:
        orig_dict: Original dictionary to update
        update_with: Dictionary with updates
    """
    for key, value in update_with.items():
        if (
            key in orig_dict
            and isinstance(orig_dict[key], dict)
            and isinstance(value, dict)
        ):
            _update_recursive(orig_dict[key], value)
        else:
            orig_dict[key] = value


def create_bloom_obj(
    session: Session,
    base,
    obj_class: str,
    name: str,
    btype: str,
    b_sub_type: Optional[str] = None,
    json_addl: Optional[Dict[str, Any]] = None,
    template_uuid: Optional[str] = None,
    **kwargs,
) -> Any:
    """
    Create a new BloomObj instance.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        obj_class: Object class name (e.g., 'content_instance')
        name: Object name
        btype: Object type
        b_sub_type: Object subtype (optional)
        json_addl: Additional JSON data (optional)
        template_uuid: Template UUID if creating from template (optional)
        **kwargs: Additional fields to set
        
    Returns:
        The created object
        
    Raises:
        ValidationError: If required fields are missing
        DatabaseError: If database operation fails
    """
    logger.debug(f"Creating {obj_class} with name={name}, btype={btype}")
    
    if not name or not btype:
        raise ValidationError("name and btype are required", field="name,btype")
    
    try:
        obj_class_ref = getattr(base.classes, obj_class)
        obj = obj_class_ref(
            name=name,
            btype=btype,
            b_sub_type=b_sub_type,
            json_addl=json_addl or {},
            template_uuid=template_uuid,
            **kwargs,
        )
        session.add(obj)
        session.flush()
        return obj
    except AttributeError as e:
        raise ValidationError(f"Invalid object class: {obj_class}", field="obj_class")
    except Exception as e:
        logger.error(f"Error creating {obj_class}: {e}")
        raise DatabaseError(f"Failed to create {obj_class}: {e}", operation="insert")


def get_bloom_obj_by_euid(
    session: Session,
    base,
    euid: str,
    include_deleted: bool = False,
) -> Optional[Any]:
    """
    Get a BloomObj by its EUID.

    Searches across all generic_instance types for the given EUID.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        euid: Entity Unique Identifier
        include_deleted: Include soft-deleted objects

    Returns:
        The object if found, None otherwise
    """
    logger.debug(f"Looking up object by EUID: {euid}")

    if not euid:
        return None

    euid = euid.strip().upper()

    try:
        query = session.query(base.classes.generic_instance).filter(
            base.classes.generic_instance.euid == euid
        )

        if not include_deleted:
            query = query.filter(
                base.classes.generic_instance.is_deleted == False
            )

        return query.first()
    except Exception as e:
        logger.error(f"Error looking up EUID {euid}: {e}")
        return None


def get_bloom_obj_by_uuid(
    session: Session,
    base,
    uuid: str,
    include_deleted: bool = False,
) -> Optional[Any]:
    """
    Get a BloomObj by its UUID.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        uuid: Universal Unique Identifier
        include_deleted: Include soft-deleted objects

    Returns:
        The object if found, None otherwise
    """
    logger.debug(f"Looking up object by UUID: {uuid}")

    if not uuid:
        return None

    try:
        query = session.query(base.classes.generic_instance).filter(
            base.classes.generic_instance.uuid == uuid
        )

        if not include_deleted:
            query = query.filter(
                base.classes.generic_instance.is_deleted == False
            )

        return query.first()
    except Exception as e:
        logger.error(f"Error looking up UUID {uuid}: {e}")
        return None


def query_objects(
    session: Session,
    base,
    btype: Optional[str] = None,
    b_sub_type: Optional[str] = None,
    super_type: Optional[str] = None,
    status: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> List[Any]:
    """
    Query BloomObj instances with filters.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        btype: Filter by type
        b_sub_type: Filter by subtype
        super_type: Filter by super type
        status: Filter by status
        include_deleted: Include soft-deleted objects
        limit: Maximum results
        offset: Results offset

    Returns:
        List of matching objects
    """
    logger.debug(f"Querying objects: btype={btype}, b_sub_type={b_sub_type}")

    try:
        query = session.query(base.classes.generic_instance)

        if btype:
            query = query.filter(base.classes.generic_instance.btype == btype.lower())

        if b_sub_type:
            query = query.filter(base.classes.generic_instance.b_sub_type == b_sub_type.lower())

        if super_type:
            query = query.filter(base.classes.generic_instance.super_type == super_type)

        if status:
            query = query.filter(base.classes.generic_instance.bstatus == status)

        if not include_deleted:
            query = query.filter(base.classes.generic_instance.is_deleted == False)

        return query.limit(limit).offset(offset).all()
    except Exception as e:
        logger.error(f"Error querying objects: {e}")
        return []


# Re-export BloomObj for backward compatibility
# The actual BloomObj class is still in bobjs.py for now
# This reference will be updated when full migration is complete
try:
    from bloom_lims.bobjs import BloomObj
except ImportError:
    # During initial import, bobjs may not be available yet
    BloomObj = None

