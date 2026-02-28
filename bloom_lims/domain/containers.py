"""
BLOOM LIMS Domain - Container Classes

This module contains container-related classes for physical containers
like plates, tubes, racks, etc.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm.attributes import flag_modified

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

    def link_biospecimen(self, container_euid: str, biospecimen_euid: str) -> Dict[str, Any]:
        """Link a container to a biospecimen EUID.

        Stores the biospecimen_euid in the container's json_addl under
        the key 'biospecimen_euid'. This is a string reference — the
        biospecimen entity does not need to exist in Bloom yet.

        Args:
            container_euid: EUID of the container (CTN-* prefix).
            biospecimen_euid: EUID of the biospecimen (BSP-* prefix).

        Returns:
            Dict with container_euid, biospecimen_euid, and success status.

        Raises:
            Exception: If the container is not found.
        """
        container = self.get_by_euid(container_euid)
        if container.json_addl is None:
            container.json_addl = {}
        container.json_addl["biospecimen_euid"] = biospecimen_euid
        flag_modified(container, "json_addl")
        self.session.commit()
        logger.info(
            "Linked container %s to biospecimen %s",
            container_euid,
            biospecimen_euid,
        )
        return {
            "container_euid": container_euid,
            "biospecimen_euid": biospecimen_euid,
            "success": True,
        }

    def set_atlas_references(
        self,
        container_euid: str,
        atlas_requisition_euid: Optional[str] = None,
        atlas_kit_euid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store Atlas reference EUIDs on a container.

        These are opaque string references to Atlas-owned entities.
        Bloom never resolves them — they exist for cross-system traceability.

        Args:
            container_euid: EUID of the container.
            atlas_requisition_euid: Atlas requisition EUID (nullable).
            atlas_kit_euid: Atlas kit EUID (nullable).

        Returns:
            Dict with the updated reference fields.
        """
        container = self.get_by_euid(container_euid)
        if container.json_addl is None:
            container.json_addl = {}
        if atlas_requisition_euid is not None:
            container.json_addl["atlas_requisition_euid"] = atlas_requisition_euid
        if atlas_kit_euid is not None:
            container.json_addl["atlas_kit_euid"] = atlas_kit_euid
        flag_modified(container, "json_addl")
        self.session.commit()
        logger.info(
            "Set Atlas references on container %s: requisition=%s, kit=%s",
            container_euid,
            atlas_requisition_euid,
            atlas_kit_euid,
        )
        return {
            "container_euid": container_euid,
            "atlas_requisition_euid": container.json_addl.get("atlas_requisition_euid"),
            "atlas_kit_euid": container.json_addl.get("atlas_kit_euid"),
            "success": True,
        }

    def get_container_chain(self, container_euid: str) -> Dict[str, Any]:
        """Return the container and its linked biospecimen + patient EUID chain.

        Traverses: container → biospecimen_euid (from json_addl) →
        patient_euid (looked up from the biospecimen's json_addl if the
        biospecimen entity exists in Bloom).

        Args:
            container_euid: EUID of the container.

        Returns:
            Dict containing the container info, linked biospecimen EUID,
            patient EUID (if resolvable), and Atlas reference EUIDs.
        """
        container = self.get_by_euid(container_euid)
        json_addl = container.json_addl or {}

        biospecimen_euid = json_addl.get("biospecimen_euid")
        patient_euid = None

        # Attempt to resolve patient EUID from the biospecimen entity
        if biospecimen_euid:
            try:
                biospecimen = self.get_by_euid(biospecimen_euid)
                bio_addl = biospecimen.json_addl or {}
                # Patient EUID may be stored directly or under properties
                patient_euid = bio_addl.get("patient_euid") or (
                    bio_addl.get("properties", {}).get("patient_euid")
                )
            except Exception:
                # Biospecimen entity may not exist yet — that's fine.
                logger.debug(
                    "Could not resolve biospecimen %s for chain lookup",
                    biospecimen_euid,
                )

        return {
            "container_euid": container.euid,
            "container_name": container.name,
            "container_type": container.type,
            "container_status": container.bstatus,
            "biospecimen_euid": biospecimen_euid,
            "patient_euid": patient_euid,
            "atlas_requisition_euid": json_addl.get("atlas_requisition_euid"),
            "atlas_kit_euid": json_addl.get("atlas_kit_euid"),
        }


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
