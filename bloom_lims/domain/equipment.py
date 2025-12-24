"""
BLOOM LIMS Domain - Equipment Classes

This module contains equipment-related classes for lab equipment
like instruments, storage units, etc.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging

from bloom_lims.domain.base import BloomObj

logger = logging.getLogger(__name__)


class BloomEquipment(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_equipment(self, template_euid):
        return self.create_instances(template_euid)



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
