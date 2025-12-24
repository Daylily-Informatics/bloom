"""
BLOOM LIMS Domain - Object Set Classes

This module contains classes for object sets and audit logging.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging

from bloom_lims.domain.base import BloomObj

logger = logging.getLogger(__name__)


class BloomObjectSet(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

# TODO -- is this used at all, and if so, is it used correctly?

class AuditLog(BloomObj):
    def __init__(self, session, base):
        super().__init__(session, base)




__all__ = [
    "BloomObjectSet",
    "AuditLog",
]
