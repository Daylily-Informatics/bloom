"""
BLOOM LIMS Domain - Containers

Container classes for plates, racks, boxes, and other physical containers.
Extracted from bloom_lims/bobjs.py for better code organization.
"""

import json
import logging
from typing import Any, List, Optional


logger = logging.getLogger(__name__)


# Import BloomObj at module level - the actual class definition is in bobjs.py
# This works because Python loads modules lazily and bobjs.py defines BloomObj first
def _get_base_class():
    """Get BloomObj base class lazily."""
    from bloom_lims.bobjs import BloomObj
    return BloomObj


class BloomContainer:
    """
    Container class for managing physical containers (plates, racks, etc.).
    
    This class extends BloomObj to provide container-specific functionality
    for managing containers and their contents.
    """
    
    _base_class = None
    
    def __new__(cls, *args, **kwargs):
        # Dynamically inherit from BloomObj on first instantiation
        if cls._base_class is None:
            cls._base_class = _get_base_class()
            # Update class bases to include BloomObj
            if cls._base_class not in cls.__bases__:
                cls.__bases__ = (cls._base_class,) + cls.__bases__[1:] if len(cls.__bases__) > 1 else (cls._base_class,)
        return super().__new__(cls)
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_container(self, template_euid: str):
        """Create an empty container from a template."""
        return self.create_instances(template_euid)

    def link_content(self, container_euid: str, content_euid: str):
        """Link content to a container."""
        container = self.get_by_euid(container_euid)
        content = self.get_by_euid(content_euid)
        container.contents.append(content)
        self.session.commit()

    def unlink_content(self, container_euid: str, content_euid: str):
        """Unlink content from a container."""
        container = self.get_by_euid(container_euid)
        content = self.get_by_euid(content_euid)
        container.contents.remove(content)
        self.session.commit()


class BloomContainerPlate(BloomContainer):
    """
    Specialized container class for plate management.
    
    Provides plate-specific operations like well organization.
    """
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_plate(self, template_euid: str):
        """Create an empty plate from a template."""
        return self.create_instances(template_euid)

    def organize_wells(self, wells: List[Any], parent_container: Any) -> List[List[Any]]:
        """
        Returns the wells of a plate in the format the parent plate specifies.

        Args:
            wells: Well objects in an array
            parent_container: One container.plate object

        Returns:
            2D array as specified in parent plate json_addl['instantiation_layouts']
        """
        if not self.validate_object_vs_pattern(
            parent_container, "container/(plate.*|rack.*)"
        ):
            raise Exception(
                f"Parent container {parent_container.name} is not a container"
            )

        try:
            layout = parent_container.json_addl["instantiation_layouts"]
        except Exception:
            layout = json.loads(parent_container.json_addl)["instantiation_layouts"]
        
        num_rows = len(layout)
        num_cols = len(layout[0]) if num_rows > 0 else 0

        # Initialize the 2D array (matrix) with None
        matrix = [[None for _ in range(num_cols)] for _ in range(num_rows)]

        # Place each well in its corresponding position
        for well in wells:
            try:
                json_addl = well.json_addl if isinstance(well.json_addl, dict) else json.loads(well.json_addl)
                row_idx = int(json_addl["cont_address"]["row_idx"])
                col_idx = int(json_addl["cont_address"]["col_idx"])
            except (KeyError, TypeError, json.JSONDecodeError) as e:
                logger.warning(f"Could not get position for well {well.name}: {e}")
                continue

            # Check if the indices are within the bounds of the matrix
            if 0 <= row_idx < num_rows and 0 <= col_idx < num_cols:
                matrix[row_idx][col_idx] = well
            else:
                logger.debug(
                    f"Well {well.name} has out-of-bounds indices: row {row_idx}, column {col_idx}"
                )

        return matrix
    
    def get_well_at_position(self, plate_euid: str, row: int, col: int) -> Optional[Any]:
        """
        Get the well at a specific position in a plate.
        
        Args:
            plate_euid: Plate EUID
            row: Row index (0-based)
            col: Column index (0-based)
            
        Returns:
            Well object or None if position is empty
        """
        plate = self.get_by_euid(plate_euid)
        if not plate:
            return None
            
        wells = self.get_child_objects(plate.uuid)
        matrix = self.organize_wells(wells, plate)
        
        if 0 <= row < len(matrix) and 0 <= col < len(matrix[0]):
            return matrix[row][col]
        return None

