"""
BLOOM LIMS Domain - Container Classes

This module contains container-related classes for physical containers
like plates, tubes, racks, etc.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging

from bloom_lims.domain.base import BloomObj

logger = logging.getLogger(__name__)


class BloomContainer(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_container(self, template_euid):
        return self.create_instances(template_euid)

    def link_content(self, container_euid, content_euid):
        container = self.get_by_euid(container_euid)
        content = self.get_by_euid(content_euid)
        container.contents.append(content)
        self.session.commit()

    def unlink_content(self, container_euid, content_euid):
        container = self.get_by_euid(container_euid)
        content = self.get_by_euid(content_euid)
        container.contents.remove(content)
        self.session.commit()


class BloomContainerPlate(BloomContainer):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_plate(self, template_euid):
        return self.create_instances(template_euid)

    def organize_wells(self, wells, parent_container):
        """Returns the wells of a plate in the format the parent plate specifies.

        Args:
            wells [container.well]: wells objects in an array
            parent_container container.plate : one container.plate object

        Returns:
            ndarray: as specified in the parent plate json_addl['instantiation_layouts']
        """

        if not self.validate_object_vs_pattern(
            parent_container, "container/(plate.*|rack.*)"
        ):
            raise Exception(
                f"""Parent container {parent_container.name} is not a container"""
            )

        try:
            layout = parent_container.json_addl["instantiation_layouts"]
        except Exception as e:
            layout = json.loads(parent_container.json_addl)["instantiation_layouts"]
        num_rows = len(layout)
        num_cols = len(layout[0]) if num_rows > 0 else 0

        # Initialize the 2D array (matrix) with None
        matrix = [[None for _ in range(num_cols)] for _ in range(num_rows)]

        # Place each well in its corresponding position
        for well in wells:
            row_idx = (
                int(json.loads(well.json_addl)["cont_address"]["row_idx"])
                if type(well.json_addl) == str()
                else int(well.json_addl["cont_address"]["row_idx"])
            )
            col_idx = (
                int(json.loads(well.json_addl)["cont_address"]["col_idx"])
                if type(well.json_addl) == str()
                else int(well.json_addl["cont_address"]["col_idx"])
            )

            # Check if the indices are within the bounds of the matrix
            if 0 <= row_idx < num_rows and 0 <= col_idx < num_cols:
                matrix[row_idx][col_idx] = well
            else:
                # Handle the case where the well's indices are out of bounds
                self.logger.debug(
                    f"Well {well.name} has out-of-bounds indices: row {row_idx}, column {col_idx}"
                )

        return matrix




__all__ = [
    "BloomContainer",
    "BloomContainerPlate",
]
