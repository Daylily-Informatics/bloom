"""
BLOOM LIMS Containers Module

This module contains container-related functionality for BLOOM LIMS.
Containers are objects that can hold other objects (plates, racks, boxes, etc.).

For backward compatibility, this module re-exports functionality that was
originally in bloom_lims/bobjs.py.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session

from bloom_lims.exceptions import (
    NotFoundError,
    ValidationError,
    DatabaseError,
)


logger = logging.getLogger(__name__)


@dataclass
class ContainerPosition:
    """
    Represents a position within a container.
    
    Positions can be specified as:
    - Well format: A1, B12, etc. (rows A-Z, columns 1-n)
    - Index format: 0, 1, 2, etc.
    - Coordinate format: (row, col)
    """
    row: int
    column: int
    
    @classmethod
    def from_well(cls, well: str) -> "ContainerPosition":
        """
        Create position from well notation (e.g., 'A1', 'B12').
        
        Args:
            well: Well string like 'A1' or 'H12'
            
        Returns:
            ContainerPosition instance
            
        Raises:
            ValidationError: If well format is invalid
        """
        well = well.upper().strip()
        match = re.match(r'^([A-Z])(\d+)$', well)
        if not match:
            raise ValidationError(f"Invalid well format: {well}", field="position")
        
        row = ord(match.group(1)) - ord('A')
        column = int(match.group(2)) - 1
        return cls(row=row, column=column)
    
    @classmethod
    def from_index(cls, index: int, num_columns: int) -> "ContainerPosition":
        """
        Create position from linear index.
        
        Args:
            index: Linear index (0-based)
            num_columns: Number of columns in container
            
        Returns:
            ContainerPosition instance
        """
        row = index // num_columns
        column = index % num_columns
        return cls(row=row, column=column)
    
    def to_well(self) -> str:
        """Convert to well notation."""
        return f"{chr(ord('A') + self.row)}{self.column + 1}"
    
    def to_index(self, num_columns: int) -> int:
        """Convert to linear index."""
        return self.row * num_columns + self.column
    
    def __str__(self) -> str:
        return self.to_well()


def get_container_layout(container: Any) -> Dict[str, Any]:
    """
    Get the layout configuration for a container.
    
    Args:
        container: Container object
        
    Returns:
        Layout configuration dict with rows, columns, type info
    """
    if not container or not hasattr(container, 'json_addl'):
        return {'rows': 1, 'columns': 1, 'type': 'unknown'}
    
    json_addl = container.json_addl or {}
    layout = json_addl.get('layout', {})
    
    return {
        'rows': layout.get('rows', 8),
        'columns': layout.get('columns', 12),
        'type': container.b_sub_type or container.btype,
        'total_positions': layout.get('rows', 8) * layout.get('columns', 12),
    }


def get_container_contents(
    session: Session,
    base,
    container_euid: str,
) -> List[Dict[str, Any]]:
    """
    Get all contents of a container with their positions.
    
    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        container_euid: Container EUID
        
    Returns:
        List of dicts with object info and position
    """
    logger.debug(f"Getting contents of container: {container_euid}")
    
    try:
        # Query for objects in this container
        container = session.query(base.classes.generic_instance).filter(
            base.classes.generic_instance.euid == container_euid.upper()
        ).first()
        
        if not container:
            raise NotFoundError(
                f"Container not found: {container_euid}",
                resource_type="container",
                resource_id=container_euid
            )
        
        # Get contents via relationship or json_addl
        contents = []
        if hasattr(container, 'json_addl') and container.json_addl:
            positions = container.json_addl.get('contents', {})
            for pos, obj_info in positions.items():
                contents.append({
                    'position': pos,
                    'euid': obj_info.get('euid'),
                    'uuid': obj_info.get('uuid'),
                    'name': obj_info.get('name'),
                    'btype': obj_info.get('btype'),
                })
        
        return contents
        
    except NotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error getting container contents: {e}")
        return []


def place_in_container(
    session: Session,
    base,
    container_euid: str,
    object_euid: str,
    position: str,
) -> bool:
    """
    Place an object in a container at a specific position.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        container_euid: Container EUID
        object_euid: Object to place EUID
        position: Position in container (e.g., 'A1')

    Returns:
        True if successful

    Raises:
        NotFoundError: If container or object not found
        ValidationError: If position is invalid or occupied
    """
    logger.debug(f"Placing {object_euid} in {container_euid} at {position}")

    try:
        # Get container
        container = session.query(base.classes.generic_instance).filter(
            base.classes.generic_instance.euid == container_euid.upper()
        ).first()

        if not container:
            raise NotFoundError(
                f"Container not found: {container_euid}",
                resource_type="container",
                resource_id=container_euid
            )

        # Get object
        obj = session.query(base.classes.generic_instance).filter(
            base.classes.generic_instance.euid == object_euid.upper()
        ).first()

        if not obj:
            raise NotFoundError(
                f"Object not found: {object_euid}",
                resource_type="object",
                resource_id=object_euid
            )

        # Validate position
        position = position.upper().strip()
        ContainerPosition.from_well(position)  # Validates format

        # Initialize contents if needed
        if not container.json_addl:
            container.json_addl = {}
        if 'contents' not in container.json_addl:
            container.json_addl['contents'] = {}

        # Check if position is occupied
        if position in container.json_addl['contents']:
            raise ValidationError(
                f"Position {position} is already occupied",
                field="position"
            )

        # Place object
        container.json_addl['contents'][position] = {
            'euid': obj.euid,
            'uuid': str(obj.uuid),
            'name': obj.name,
            'btype': obj.btype,
            'placed_at': __import__('datetime').datetime.utcnow().isoformat(),
        }

        # Update object's container reference
        if not obj.json_addl:
            obj.json_addl = {}
        obj.json_addl['container_euid'] = container.euid
        obj.json_addl['container_position'] = position

        session.flush()
        return True

    except (NotFoundError, ValidationError):
        raise
    except Exception as e:
        logger.error(f"Error placing object in container: {e}")
        raise DatabaseError(f"Failed to place object in container: {e}")


def remove_from_container(
    session: Session,
    base,
    container_euid: str,
    position: str,
) -> Optional[str]:
    """
    Remove an object from a container position.

    Args:
        session: SQLAlchemy session
        base: SQLAlchemy automap base
        container_euid: Container EUID
        position: Position to clear (e.g., 'A1')

    Returns:
        EUID of removed object, or None if position was empty
    """
    logger.debug(f"Removing object from {container_euid} at {position}")

    try:
        container = session.query(base.classes.generic_instance).filter(
            base.classes.generic_instance.euid == container_euid.upper()
        ).first()

        if not container:
            raise NotFoundError(
                f"Container not found: {container_euid}",
                resource_type="container",
                resource_id=container_euid
            )

        position = position.upper().strip()

        if not container.json_addl or 'contents' not in container.json_addl:
            return None

        if position not in container.json_addl['contents']:
            return None

        # Get object info before removing
        obj_info = container.json_addl['contents'][position]
        removed_euid = obj_info.get('euid')

        # Remove from container
        del container.json_addl['contents'][position]

        # Clear object's container reference
        if removed_euid:
            obj = session.query(base.classes.generic_instance).filter(
                base.classes.generic_instance.euid == removed_euid
            ).first()

            if obj and obj.json_addl:
                obj.json_addl.pop('container_euid', None)
                obj.json_addl.pop('container_position', None)

        session.flush()
        return removed_euid

    except NotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error removing from container: {e}")
        return None


# Re-export for backward compatibility
try:
    from bloom_lims.bobjs import BloomObj as _BloomObj
    BloomContainer = _BloomObj
except ImportError:
    BloomContainer = None

