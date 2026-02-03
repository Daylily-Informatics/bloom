"""
BLOOM LIMS Lineage Module

This module contains lineage tracking functionality for BLOOM LIMS.
Lineage tracks the relationships and history of objects as they move
through processing workflows.

For backward compatibility, this module re-exports functionality that was
originally in bloom_lims/bobjs.py.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from bloom_lims.exceptions import (
    NotFoundError,
    ValidationError,
    DatabaseError,
)


logger = logging.getLogger(__name__)


class BloomLineageMixin:
    """
    Mixin class providing common lineage functionality.
    """
    
    @property
    def lineage_depth(self) -> int:
        """Get depth in lineage tree (0 for root)."""
        if hasattr(self, 'json_addl') and self.json_addl:
            return self.json_addl.get('lineage_depth', 0)
        return 0
    
    @property
    def is_lineage_root(self) -> bool:
        """Check if this is the root of a lineage tree."""
        return self.lineage_depth == 0


def create_lineage(
    session: Session,
    base,
    name: str,
    lineage_type: str,
    root_object: Optional[Any] = None,
    json_addl: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Any:
    """
    Create a new lineage tracking object.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        name: Lineage name
        lineage_type: Type of lineage
        root_object: Root object of the lineage (optional)
        json_addl: Additional JSON data (optional)
        **kwargs: Additional fields
        
    Returns:
        The created lineage object
        
    Raises:
        ValidationError: If required fields are missing
        DatabaseError: If database operation fails
    """
    logger.debug(f"Creating lineage: name={name}, type={lineage_type}")
    
    if not name or not lineage_type:
        raise ValidationError("name and lineage_type are required")
    
    try:
        lineage_class = getattr(base.classes, 'generic_instance_lineage')
        
        lineage_json = {
            'created_at': datetime.utcnow().isoformat(),
            'members': [],
            **(json_addl or {}),
        }
        
        if root_object:
            lineage_json['root_euid'] = root_object.euid
            lineage_json['root_uuid'] = str(root_object.uuid)
            lineage_json['members'].append({
                'euid': root_object.euid,
                'uuid': str(root_object.uuid),
                'depth': 0,
                'added_at': datetime.utcnow().isoformat(),
            })
        
        lineage = lineage_class(
            name=name,
            type=lineage_type.lower(),
            json_addl=lineage_json,
            **kwargs,
        )
        
        session.add(lineage)
        session.flush()
        return lineage
        
    except Exception as e:
        logger.error(f"Error creating lineage: {e}")
        raise DatabaseError(f"Failed to create lineage: {e}", operation="insert")


def get_lineage_by_euid(
    session: Session,
    base,
    euid: str,
) -> Optional[Any]:
    """
    Get a lineage by its EUID.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        euid: Lineage EUID
        
    Returns:
        The lineage object or None
    """
    logger.debug(f"Looking up lineage by EUID: {euid}")
    
    if not euid:
        return None
    
    try:
        return session.query(base.classes.generic_instance_lineage).filter(
            base.classes.generic_instance_lineage.euid == euid.upper()
        ).first()
    except Exception as e:
        logger.error(f"Error looking up lineage {euid}: {e}")
        return None


def add_to_lineage(
    session: Session,
    base,
    lineage_euid: str,
    object_euid: str,
    parent_euid: Optional[str] = None,
) -> bool:
    """
    Add an object to a lineage.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        lineage_euid: Lineage EUID
        object_euid: Object to add
        parent_euid: Parent object in lineage (optional)
        
    Returns:
        True if successful
    """
    logger.debug(f"Adding {object_euid} to lineage {lineage_euid}")

    try:
        lineage = get_lineage_by_euid(session, base, lineage_euid)
        if not lineage:
            raise NotFoundError(
                f"Lineage not found: {lineage_euid}",
                resource_type="lineage",
                resource_id=lineage_euid
            )

        obj = session.query(base.classes.generic_instance).filter(
            base.classes.generic_instance.euid == object_euid.upper()
        ).first()

        if not obj:
            raise NotFoundError(
                f"Object not found: {object_euid}",
                resource_type="object",
                resource_id=object_euid
            )

        # Calculate depth
        depth = 0
        if parent_euid and lineage.json_addl:
            for member in lineage.json_addl.get('members', []):
                if member.get('euid') == parent_euid.upper():
                    depth = member.get('depth', 0) + 1
                    break

        # Add to members list
        if not lineage.json_addl:
            lineage.json_addl = {'members': []}
        if 'members' not in lineage.json_addl:
            lineage.json_addl['members'] = []

        lineage.json_addl['members'].append({
            'euid': obj.euid,
            'uuid': str(obj.uuid),
            'depth': depth,
            'parent_euid': parent_euid.upper() if parent_euid else None,
            'added_at': datetime.utcnow().isoformat(),
        })

        # Update object's lineage reference
        if not obj.json_addl:
            obj.json_addl = {}
        obj.json_addl['lineage_euid'] = lineage.euid
        obj.json_addl['lineage_depth'] = depth

        session.flush()
        return True

    except NotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error adding to lineage: {e}")
        return False


def get_lineage_tree(
    session: Session,
    base,
    lineage_euid: str,
) -> Dict[str, Any]:
    """
    Get the full lineage tree structure.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        lineage_euid: Lineage EUID

    Returns:
        Dict with tree structure
    """
    logger.debug(f"Getting lineage tree for: {lineage_euid}")

    lineage = get_lineage_by_euid(session, base, lineage_euid)
    if not lineage:
        raise NotFoundError(
            f"Lineage not found: {lineage_euid}",
            resource_type="lineage",
            resource_id=lineage_euid
        )

    tree = {
        'euid': lineage.euid,
        'name': lineage.name,
        'type': lineage.type,
        'members': [],
        'root': None,
    }

    if lineage.json_addl:
        members = lineage.json_addl.get('members', [])
        tree['members'] = members

        # Find root
        for member in members:
            if member.get('depth', 0) == 0:
                tree['root'] = member
                break

    return tree


def get_object_lineage(
    session: Session,
    base,
    object_euid: str,
) -> Optional[Dict[str, Any]]:
    """
    Get lineage information for an object.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        object_euid: Object EUID

    Returns:
        Lineage info dict or None
    """
    logger.debug(f"Getting lineage for object: {object_euid}")

    obj = session.query(base.classes.generic_instance).filter(
        base.classes.generic_instance.euid == object_euid.upper()
    ).first()

    if not obj:
        return None

    if not obj.json_addl or 'lineage_euid' not in obj.json_addl:
        return None

    lineage_euid = obj.json_addl['lineage_euid']
    return get_lineage_tree(session, base, lineage_euid)


# Re-export for backward compatibility
try:
    from bloom_lims.bobjs import BloomObj as _BloomObj
    BloomLineage = _BloomObj
except ImportError:
    BloomLineage = None

