"""
BLOOM LIMS Domain - Object Sets and Audit

Object set and audit log classes.
Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _get_base_class():
    """Get BloomObj base class lazily."""
    from bloom_lims.bobjs import BloomObj
    return BloomObj


class BloomObjectSet:
    """
    Object Set class for managing collections of BLOOM objects.
    
    An ObjectSet groups multiple objects together for batch operations,
    reporting, or organizational purposes.
    """
    
    _base_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._base_class is None:
            cls._base_class = _get_base_class()
            if cls._base_class not in cls.__bases__:
                cls.__bases__ = (cls._base_class,) + cls.__bases__[1:] if len(cls.__bases__) > 1 else (cls._base_class,)
        return super().__new__(cls)
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)
    
    def create_object_set(
        self,
        name: str,
        description: Optional[str] = None,
        object_euids: Optional[List[str]] = None,
    ) -> Any:
        """
        Create a new object set.
        
        Args:
            name: Name for the object set
            description: Optional description
            object_euids: Optional list of object EUIDs to include
            
        Returns:
            Created object set
        """
        obj_set = self.create_instance(
            self.query_template_by_component_v2(
                "object_set", "generic", "object-set", "1.0"
            )[0].euid,
            {"properties": {"name": name, "description": description or ""}},
        )
        self.session.commit()
        
        if object_euids:
            for euid in object_euids:
                self.create_generic_instance_lineage_by_euids(obj_set.euid, euid)
            self.session.commit()
        
        return obj_set
    
    def add_to_set(self, set_euid: str, object_euid: str) -> None:
        """Add an object to a set."""
        self.create_generic_instance_lineage_by_euids(set_euid, object_euid)
        self.session.commit()
    
    def remove_from_set(self, set_euid: str, object_euid: str) -> None:
        """Remove an object from a set."""
        obj_set = self.get_by_euid(set_euid)
        obj = self.get_by_euid(object_euid)
        
        for lineage in obj_set.parent_of_lineages:
            if lineage.child_instance.euid == object_euid:
                self.session.delete(lineage)
                break
        self.session.commit()
    
    def get_set_members(self, set_euid: str) -> List[Any]:
        """Get all objects in a set."""
        obj_set = self.get_by_euid(set_euid)
        if not obj_set:
            return []
        
        return [lineage.child_instance for lineage in obj_set.parent_of_lineages]


class AuditLog:
    """
    Audit Log class for tracking changes to BLOOM objects.
    
    Note: This class may need review - the original implementation
    has a TODO comment questioning its usage.
    """
    
    _base_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._base_class is None:
            cls._base_class = _get_base_class()
            if cls._base_class not in cls.__bases__:
                cls.__bases__ = (cls._base_class,) + cls.__bases__[1:] if len(cls.__bases__) > 1 else (cls._base_class,)
        return super().__new__(cls)
    
    def __init__(self, session, base):
        # Note: Original signature differs from other classes
        super().__init__(session, base)
    
    def log_action(
        self,
        target_euid: str,
        action: str,
        user: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Log an action on an object.
        
        Args:
            target_euid: EUID of the target object
            action: Action performed
            user: User who performed the action
            details: Additional details
            
        Returns:
            Created audit log entry
        """
        from bloom_lims.bobjs import get_datetime_string
        
        log_entry = {
            "target_euid": target_euid,
            "action": action,
            "user": user,
            "timestamp": get_datetime_string(),
            "details": details or {},
        }
        
        # Create audit log entry
        audit = self.create_instance(
            self.query_template_by_component_v2(
                "audit", "log", "action", "1.0"
            )[0].euid,
            {"properties": log_entry},
        )
        self.session.commit()
        
        # Link to target object
        self.create_generic_instance_lineage_by_euids(target_euid, audit.euid)
        self.session.commit()
        
        return audit

