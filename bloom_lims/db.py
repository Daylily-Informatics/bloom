"""
BLOOM LIMS Database Module.

This module is the public entrypoint for BLOOM's database layer.
It re-exports all symbols from the TapDB adapter to maintain backward compatibility.

Phase 2 of BLOOM Database Refactor Plan.
"""

# Re-export everything from the TapDB adapter
from bloom_lims.tapdb_adapter import (
    # Core
    Base,
    bloom_core,
    tapdb_core,
    BLOOMdb3,
    # Generic classes
    generic_template,
    generic_instance,
    generic_instance_lineage,
    # Typed templates
    workflow_template,
    workflow_step_template,
    container_template,
    content_template,
    equipment_template,
    data_template,
    test_requisition_template,
    actor_template,
    action_template,
    health_event_template,
    file_template,
    subject_template,
    # Typed instances
    workflow_instance,
    workflow_step_instance,
    container_instance,
    content_instance,
    equipment_instance,
    data_instance,
    test_requisition_instance,
    actor_instance,
    action_instance,
    health_event_instance,
    file_instance,
    subject_instance,
    # Typed lineages
    workflow_instance_lineage,
    workflow_step_instance_lineage,
    container_instance_lineage,
    content_instance_lineage,
    equipment_instance_lineage,
    data_instance_lineage,
    test_requisition_instance_lineage,
    actor_instance_lineage,
    action_instance_lineage,
    health_event_instance_lineage,
    file_instance_lineage,
    subject_instance_lineage,
    # BLOOM-specific aliases
    file_set_template,
    file_reference_template,
    file_set_instance,
    file_reference_instance,
    file_set_instance_lineage,
    file_reference_instance_lineage,
    # Audit
    audit_log,
)

# Re-export utility functions and imports that legacy code may depend on
import os
import json
import re
import random
import string
import yaml
import logging
import pytz
import socket
import boto3
import requests
import subprocess

from pathlib import Path
from datetime import datetime, timedelta, date
from logging.handlers import RotatingFileHandler

from sqlalchemy import (
    and_,
    create_engine,
    MetaData,
    event,
    desc,
    text,
    FetchedValue,
    BOOLEAN,
    Column,
    String,
    Integer,
    Text,
    TIMESTAMP,
    JSON,
    CheckConstraint,
    DateTime,
    Boolean,
    ForeignKey,
    or_,
)
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import (
    sessionmaker,
    Query,
    Session,
    relationship,
    configure_mappers,
    foreign,
    backref,
)
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm.attributes import flag_modified
import sqlalchemy.orm as sqla_orm

# Zebra day printer manager
import zebra_day.print_mgr as zdpm

try:
    import fedex_tracking_day.fedex_track as FTD
except Exception:
    pass

# Universal printer behavior
PGLOBAL = False if os.environ.get("PGLOBAL", False) else True


# Utility functions from legacy db.py
def generate_random_string(length=10):
    characters = string.ascii_letters + string.digits
    return "".join(random.choice(characters) for _ in range(length))


def get_datetime_string():
    timezone = pytz.timezone("US/Eastern")
    current_datetime_with_tz = datetime.now(timezone)
    return current_datetime_with_tz.strftime("%Y-%m-%d %H:%M:%S %Z%z")


def _update_recursive(orig_dict, update_with):
    for key, value in update_with.items():
        if key in orig_dict and isinstance(orig_dict[key], dict) and isinstance(value, dict):
            _update_recursive(orig_dict[key], value)
        else:
            orig_dict[key] = value


def unique_non_empty_strings(arr):
    unique_strings = set()
    for s in arr:
        if s and s not in unique_strings:
            unique_strings.add(s)
    return list(unique_strings)

