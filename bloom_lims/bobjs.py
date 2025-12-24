"""
BLOOM LIMS - Backward Compatibility Module

This module re-exports all domain classes from the bloom_lims.domain package
to maintain backward compatibility with existing code that imports from bobjs.

For new code, prefer importing directly from bloom_lims.domain:
    from bloom_lims.domain import BloomContainer, BloomWorkflow, BloomFile

Legacy imports still work:
    from bloom_lims.bobjs import BloomContainer, BloomWorkflow, BloomFile
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

os.makedirs("logs", exist_ok=True)


def get_clean_timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def setup_logging():
    """Setup logging for the module."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    log_filename = f"logs/bdb_objs_{get_clean_timestamp()}.log"

    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.INFO)

    f_handler = RotatingFileHandler(log_filename, maxBytes=10485760, backupCount=10)
    f_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d"
    )
    c_handler.setFormatter(formatter)
    f_handler.setFormatter(formatter)

    logger.addHandler(c_handler)
    logger.addHandler(f_handler)


setup_logging()

# Re-export all domain classes for backward compatibility
from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.containers import BloomContainer, BloomContainerPlate
from bloom_lims.domain.content import BloomContent, BloomReagent
from bloom_lims.domain.workflows import BloomWorkflow, BloomWorkflowStep
from bloom_lims.domain.equipment import BloomEquipment, BloomHealthEvent
from bloom_lims.domain.files import BloomFile, BloomFileReference, BloomFileSet
from bloom_lims.domain.object_sets import BloomObjectSet, AuditLog

# Re-export utility functions
from bloom_lims.domain.utils import (
    get_datetime_string,
    generate_random_string,
    update_recursive as _update_recursive,
    unique_non_empty_strings,
)

__all__ = [
    # Classes
    "BloomObj",
    "BloomContainer",
    "BloomContainerPlate",
    "BloomContent",
    "BloomReagent",
    "BloomWorkflow",
    "BloomWorkflowStep",
    "BloomEquipment",
    "BloomHealthEvent",
    "BloomFile",
    "BloomFileReference",
    "BloomFileSet",
    "BloomObjectSet",
    "AuditLog",
    # Utility functions
    "get_datetime_string",
    "generate_random_string",
    "_update_recursive",
    "unique_non_empty_strings",
    "get_clean_timestamp",
    "setup_logging",
]
