"""
BLOOM LIMS Domain Module

This module contains domain-specific classes for the BLOOM LIMS system.
These classes extend the base BloomObj class to provide specialized
functionality for different object types.

The classes here are extracted from the original bobjs.py monolith
to improve code organization and maintainability.

For backward compatibility, all classes are also exported from
bloom_lims.bobjs.

Usage:
    from bloom_lims.domain import BloomContainer, BloomWorkflow, BloomFile
    
    # Or via backward-compatible imports:
    from bloom_lims.bobjs import BloomContainer, BloomWorkflow, BloomFile
"""

from bloom_lims.domain.containers import (
    BloomContainer,
    BloomContainerPlate,
)
from bloom_lims.domain.content import (
    BloomContent,
    BloomReagent,
)
from bloom_lims.domain.workflows import (
    BloomWorkflow,
    BloomWorkflowStep,
)
from bloom_lims.domain.equipment import (
    BloomEquipment,
    BloomHealthEvent,
)
from bloom_lims.domain.files import (
    BloomFile,
    BloomFileSet,
    BloomFileReference,
)
from bloom_lims.domain.object_sets import (
    BloomObjectSet,
    AuditLog,
)

__all__ = [
    # Containers
    "BloomContainer",
    "BloomContainerPlate",
    # Content
    "BloomContent",
    "BloomReagent",
    # Workflows
    "BloomWorkflow",
    "BloomWorkflowStep",
    # Equipment
    "BloomEquipment",
    "BloomHealthEvent",
    # Files
    "BloomFile",
    "BloomFileSet",
    "BloomFileReference",
    # Misc
    "BloomObjectSet",
    "AuditLog",
]

