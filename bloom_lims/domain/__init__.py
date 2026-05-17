"""
BLOOM LIMS Domain Module

This module contains domain-specific classes for the BLOOM LIMS system.
Classes are organized by functional area:

- base: BloomObj base class with core functionality
- containers: Container classes (plates, tubes, racks)
- content: Content classes (samples, reagents)
- equipment: Lab equipment and health events
- files: File handling and storage
- object_sets: Object sets and audit logging
- utils: Utility functions

Usage:
    from bloom_lims.domain import BloomContainer, BloomFile
    from bloom_lims.domain.utils import get_datetime_string
"""

from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.containers import BloomContainer, BloomContainerPlate
from bloom_lims.domain.content import BloomContent, BloomReagent
from bloom_lims.domain.equipment import BloomEquipment, BloomHealthEvent
from bloom_lims.domain.files import BloomFile, BloomFileReference, BloomFileSet
from bloom_lims.domain.object_sets import AuditLog, BloomObjectSet
from bloom_lims.domain.utils import (
    generate_random_string,
    get_clean_timestamp,
    get_datetime_string,
    unique_non_empty_strings,
    update_recursive,
)

__all__ = [
    # Base
    "BloomObj",
    # Containers
    "BloomContainer",
    "BloomContainerPlate",
    # Content
    "BloomContent",
    "BloomReagent",
    # Equipment
    "BloomEquipment",
    "BloomHealthEvent",
    # Files
    "BloomFile",
    "BloomFileReference",
    "BloomFileSet",
    # Object Sets
    "BloomObjectSet",
    "AuditLog",
    # Utilities
    "get_datetime_string",
    "generate_random_string",
    "update_recursive",
    "unique_non_empty_strings",
    "get_clean_timestamp",
]
