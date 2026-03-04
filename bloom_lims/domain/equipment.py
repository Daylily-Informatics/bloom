"""
BLOOM LIMS Domain - Equipment Classes

This module contains equipment-related classes for lab equipment
like instruments, storage units, etc.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging
from datetime import datetime, timezone

from bloom_lims.domain.base import BloomObj

logger = logging.getLogger(__name__)


class BloomEquipment(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_equipment(self, template_euid):
        return self.create_instances(template_euid)

    def record_maintenance(
        self,
        euid: str,
        *,
        maintenance_type: str,
        performed_by: str,
        notes: str | None = None,
    ):
        """
        Append a maintenance record to an equipment instance.

        Stored in `json_addl.properties.maintenance_records` with
        `json_addl.properties.last_maintenance` updated for convenience.
        """
        from sqlalchemy.orm.attributes import flag_modified

        equipment = self.get_by_euid(euid)
        if not equipment:
            raise ValueError(f"Equipment not found: {euid}")

        json_addl = equipment.json_addl or {}
        if not isinstance(json_addl, dict):
            json_addl = {}

        props = json_addl.get("properties")
        if not isinstance(props, dict):
            props = {}

        records = props.get("maintenance_records")
        if not isinstance(records, list):
            records = []

        performed_at = datetime.now(timezone.utc).isoformat()
        record = {
            "maintenance_type": str(maintenance_type),
            "performed_by": str(performed_by),
            "notes": str(notes or ""),
            "performed_at": performed_at,
        }

        records.append(record)
        props["maintenance_records"] = records
        props["last_maintenance"] = performed_at
        json_addl["properties"] = props

        equipment.json_addl = json_addl
        flag_modified(equipment, "json_addl")

        self.session.commit()
        return equipment



class BloomHealthEvent(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_event(self):

        new_event = self.create_instance(
            self.query_template_by_component_v2(
                "health_event", "generic", "health-event", "1.0"
            )[0].euid
        )
        self.session.commit()

        return new_event




__all__ = [
    "BloomEquipment",
    "BloomHealthEvent",
]
