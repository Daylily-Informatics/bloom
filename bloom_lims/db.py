import os
## import ast
## import sys
import subprocess

import json
import re
import random
import string
import yaml

from pathlib import Path
import urllib.parse

import logging
from logging.handlers import RotatingFileHandler
from .logging_config import setup_logging
from datetime import datetime, timedelta, date, UTC


os.makedirs("logs", exist_ok=True)

def get_clean_timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def setup_logging():
    # uvicorn to capture logs from all libs
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Define the log file name with a timestamp
    log_filename = f"logs/bdb_{get_clean_timestamp()}.log"

    # Stream handler (to console)
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.INFO)

    # File handler (to file, with rotation)
    f_handler = RotatingFileHandler(log_filename, maxBytes=10485760, backupCount=10)
    f_handler.setLevel(logging.INFO)

    # Common log format
    formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d"
    )
    c_handler.setFormatter(formatter)
    f_handler.setFormatter(formatter)

    # Add handlers to the logger
    logger.addHandler(c_handler)
    logger.addHandler(f_handler)


setup_logging()

from datetime import datetime
import pytz

import socket
import boto3
import requests
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

boto3.set_stream_logger(name="botocore")

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
    and_,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm.attributes import flag_modified

import sqlalchemy.orm as sqla_orm

import zebra_day.print_mgr as zdpm

try:
    import fedex_tracking_day.fedex_track as FTD
except Exception as e:
    pass  # not running in github action for some reason

# Universal printer behavior on
PGLOBAL = False if os.environ.get("PGLOBAL", False) else True


def generate_random_string(length=10):
    characters = string.ascii_letters + string.digits
    random_string = "".join(random.choice(characters) for _ in range(length))
    return random_string


def get_datetime_string():
    # Choose your desired timezone, e.g., 'US/Eastern', 'Europe/London', etc.
    timezone = pytz.timezone("US/Eastern")

    # Get current datetime with timezone
    current_datetime_with_tz = datetime.now(timezone)

    # Format as string
    datetime_string = current_datetime_with_tz.strftime("%Y-%m-%d %H:%M:%S %Z%z")

    return str(datetime_string)


def _update_recursive(orig_dict, update_with):
    for key, value in update_with.items():
        if (
            key in orig_dict
            and isinstance(orig_dict[key], dict)
            and isinstance(value, dict)
        ):
            _update_recursive(orig_dict[key], value)
        else:
            orig_dict[key] = value


def unique_non_empty_strings(arr):
    """
    Return a new array with unique strings and empty strings removed.

    :param arr: List of strings
    :return: List of unique non-empty strings
    """
    # Using a set to maintain uniqueness
    unique_strings = set()
    for string in arr:
        if string and string not in unique_strings:
            unique_strings.add(string)
    return list(unique_strings)


Base = sqla_orm.declarative_base()


class bloom_core(Base):
    __abstract__ = True

    uuid = Column(UUID, primary_key=True, nullable=True, server_default=FetchedValue())

    euid = Column(Text, nullable=True, server_default=FetchedValue())
    name = Column(Text, nullable=True)

    created_dt = Column(TIMESTAMP, nullable=True, server_default=FetchedValue())
    modified_dt = Column(TIMESTAMP, nullable=True, server_default=FetchedValue())

    polymorphic_discriminator = Column(Text, nullable=True)

    super_type = Column(Text, nullable=True)
    btype = Column(Text, nullable=True)
    b_sub_type = Column(Text, nullable=True)
    version = Column(Text, nullable=True)

    bstatus = Column(Text, nullable=True)

    json_addl = Column(JSON, nullable=True)

    is_singleton = Column(BOOLEAN, nullable=False, server_default=FetchedValue())

    is_deleted = Column(BOOLEAN, nullable=True, server_default=FetchedValue())

    @staticmethod
    def sort_by_euid(a_list):
        return sorted(a_list, key=lambda a: a.euid)


## Generic
class generic_template(bloom_core):
    __tablename__ = "generic_template"
    __mapper_args__ = {
        "polymorphic_identity": "generic_template",
        "polymorphic_on": "polymorphic_discriminator",
    }
    instance_prefix = Column(Text, nullable=True)
    json_addl_schema = Column(JSON, nullable=True)

    # removed ,generic_instance.is_deleted == False)
    child_instances = relationship(
        "generic_instance",
        primaryjoin="and_(generic_template.uuid == foreign(generic_instance.template_uuid))",
        backref="parent_template",
    )


class generic_instance(bloom_core):
    __tablename__ = "generic_instance"
    __mapper_args__ = {
        "polymorphic_identity": "generic_instance",
        "polymorphic_on": "polymorphic_discriminator",
    }
    template_uuid = Column(UUID, ForeignKey("generic_template.uuid"), nullable=True)

    # Way black magic the reference selctor is filtering out records which are soft deleted
    # removed : ,generic_instance_lineage.is_deleted == False) no )
    parent_of_lineages = relationship(
        "generic_instance_lineage",
        primaryjoin="and_(generic_instance.uuid == foreign(generic_instance_lineage.parent_instance_uuid))",
        backref="parent_instance",
        lazy="dynamic",
    )

    # removed ,generic_instance_lineage.is_deleted == False
    child_of_lineages = relationship(
        "generic_instance_lineage",
        primaryjoin="and_(generic_instance.uuid == foreign(generic_instance_lineage.child_instance_uuid))",
        backref="child_instance",
        lazy="dynamic",
    )

    def get_sorted_parent_of_lineages(
        self, priority_discriminators=["workflow_step_instance"]
    ):
        """
        Returns parent_of_lineages sorted by polymorphism_discriminator.
        Steps with polymorphism_discriminator in priority_discriminators are put at the front.

        :param priority_discriminators: List of polymorphism_discriminator values to prioritize.
        :return: Sorted list of parent_of_lineages.
        """
        if priority_discriminators is None:
            priority_discriminators = []

        # First, separate the lineages based on whether they are in the priority list
        priority_lineages = [
            lineage
            for lineage in self.parent_of_lineages
            if lineage.child_instance.polymorphic_discriminator
            in priority_discriminators
        ]
        other_lineages = [
            lineage
            for lineage in self.parent_of_lineages
            if lineage.child_instance.polymorphic_discriminator
            not in priority_discriminators
        ]

        # Optionally, sort each list individually if needed
        # For example, sort by some attribute of the child_instance
        priority_lineages.sort(key=lambda x: x.child_instance.euid)
        other_lineages.sort(key=lambda x: x.child_instance.euid)

        # Combine the lists, with priority_lineages first
        return priority_lineages + other_lineages

    def get_sorted_child_of_lineages(
        self, priority_discriminators=["workflow_step_instance"]
    ):
        """
        Returns child_of_lineages sorted by polymorphic_discriminator.
        Lineages with polymorphic_discriminator in priority_discriminators are put at the front.

        :param priority_discriminators: List of polymorphic_discriminator values to prioritize.
        :return: Sorted list of child_of_lineages.
        """

        print("THIS METHOD IS NOT YET TESTED")

        if priority_discriminators is None:
            priority_discriminators = []

        # First, separate the lineages based on whether they are in the priority list
        priority_lineages = [
            lineage
            for lineage in self.child_of_lineages
            if lineage.parent_instance.polymorphic_discriminator
            in priority_discriminators
        ]
        other_lineages = [
            lineage
            for lineage in self.child_of_lineages
            if lineage.parent_instance.polymorphic_discriminator
            not in priority_discriminators
        ]

        # Optionally, sort each list individually if needed
        # For example, sort by some attribute of the parent_instance
        priority_lineages.sort(key=lambda x: x.parent_instance.euid)
        other_lineages.sort(key=lambda x: x.parent_instance.euid)

        # Combine the lists, with priority_lineages first
        return priority_lineages + other_lineages

    def filter_lineage_members(
        self, of_lineage_type, lineage_member_type, filter_criteria
    ):
        """
        WARNING NOT TESTED!!!!

        Filters lineage members based on given criteria.

        :param of_lineage_type: 'parent_of_lineages' or 'child_of_lineages' to specify which lineage to filter.
        :param lineage_member_type: 'parent_instance' or 'child_instance' to specify which of the two members to check.
        :param filter_criteria: Dictionary with keys corresponding to properties of the instance object.
                                The values in the dictionary are the criteria for filtering.
        :return: Filtered list of lineage members.
        """
        print("THIS METHOD IS NOT YET TESTED")
        if of_lineage_type not in ["parent_of_lineages", "child_of_lineages"]:
            raise ValueError(
                "Invalid of_lineage_type. Must be 'parent_of_lineages' or 'child_of_lineages'."
            )

        if lineage_member_type not in ["parent_instance", "child_instance"]:
            raise ValueError(
                "Invalid lineage_member_type. Must be 'parent_instance' or 'child_instance'."
            )

        if not filter_criteria:
            raise ValueError("Filter criteria is empty.")

        lineage_members = getattr(self, of_lineage_type)

        filtered_members = []
        for member in lineage_members:
            instance = getattr(member, lineage_member_type)
            if all(
                getattr(instance, key, None) == value
                or instance.json_addl.get(key) == value
                for key, value in filter_criteria.items()
            ):
                filtered_members.append(member)

        return filtered_members


class generic_instance_lineage(bloom_core):
    __tablename__ = "generic_instance_lineage"
    __mapper_args__ = {
        "polymorphic_identity": "generic_instance_lineage",
        "polymorphic_on": "polymorphic_discriminator",
    }

    parent_type = Column(Text, nullable=True)
    child_type = Column(Text, nullable=True)
    relationship_type = Column(Text, nullable=True)

    parent_instance_uuid = Column(
        UUID, ForeignKey("generic_instance.uuid"), nullable=False
    )
    child_instance_uuid = Column(
        UUID, ForeignKey("generic_instance.uuid"), nullable=False
    )


# I tried to dynamically generate these, and believe its doable, but had burned the allotted time for this task :-)
class workflow_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "workflow_template",
    }


class workflow_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "workflow_instance",
    }


class workflow_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "workflow_instance_lineage",
    }


class workflow_step_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "workflow_step_template",
    }


class workflow_step_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "workflow_step_instance",
    }


class workflow_step_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "workflow_step_instance_lineage",
    }


class content_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "content_template",
    }


class content_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "content_instance",
    }


class content_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "content_instance_lineage",
    }


class container_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "container_template",
    }


class container_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "container_instance",
    }


class container_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "container_instance_lineage",
    }


class equipment_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "equipment_template",
    }


class equipment_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "equipment_instance",
    }


class equipment_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "equipment_instance_lineage",
    }


class data_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "data_template",
    }


class data_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "data_instance",
    }


class data_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "data_instance_lineage",
    }


class test_requisition_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "test_requisition_template",
    }


class test_requisition_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "test_requisition_instance",
    }


class test_requisition_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "test_requisition_instance_lineage",
    }


class actor_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "actor_template",
    }


class actor_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "actor_instance",
    }


class actor_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "actor_instance_lineage",
    }


class action_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "action_template",
    }


class action_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "action_instance",
    }


class action_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "action_instance_lineage",
    }


class health_event_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "health_event_template",
    }


class health_event_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "health_event_instance",
    }


class health_event_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "health_event_instance_lineage",
    }


class file_template(generic_template):
    __mapper_args__ = {
        "polymorphic_identity": "file_template",
    }


class file_instance(generic_instance):
    __mapper_args__ = {
        "polymorphic_identity": "file_instance",
    }


class file_instance_lineage(generic_instance_lineage):
    __mapper_args__ = {
        "polymorphic_identity": "file_instance_lineage",
    }


class BLOOMdb3:
    def __init__(
        self,
        db_url_prefix="postgresql://",
        db_hostname="localhost:" + os.environ.get("PGPORT", "5445"),  # 5432
        db_pass=(
            None if "PGPASSWORD" not in os.environ else os.environ.get("PGPASSWORD")
        ),
        db_user=os.environ.get("USER", "bloom"),
        db_name="bloom",
        app_username=os.environ.get("USER", "bloomdborm"),
        echo_sql=os.environ.get("ECHO_SQL", False),
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.debug("STARTING BLOOMDB3")
        self.app_username = app_username
        self.engine = create_engine(
            f"{db_url_prefix}{db_user}:{db_pass}@{db_hostname}/{db_name}", echo=echo_sql
        )
        metadata = MetaData()
        self.Base = automap_base(metadata=metadata)

        self.session = sessionmaker(bind=self.engine)()

        # This is so the database can log a user if changes are made
        set_current_username_sql = text("SET session.current_username = :username")
        self.session.execute(set_current_username_sql, {"username": self.app_username})
        self.session.commit()

        # reflect and load the support tables just in case they are needed, but this can prob be disabled in prod
        self.Base.prepare(autoload_with=self.engine)

        classes_to_register = [
            generic_template,
            generic_instance,
            generic_instance_lineage,
            container_template,
            container_instance,
            container_instance_lineage,
            content_template,
            content_instance,
            content_instance_lineage,
            workflow_template,
            workflow_instance,
            workflow_instance_lineage,
            workflow_step_template,
            workflow_step_instance,
            workflow_step_instance_lineage,
            equipment_template,
            equipment_instance,
            equipment_instance_lineage,
            data_template,
            data_instance,
            data_instance_lineage,
            test_requisition_template,
            test_requisition_instance,
            test_requisition_instance_lineage,
            actor_template,
            actor_instance,
            actor_instance_lineage,
            action_template,
            action_instance,
            action_instance_lineage,
            file_template,
            file_instance,
            file_instance_lineage,
            health_event_template,
            health_event_instance,
            health_event_instance_lineage,
        ]
        for cls in classes_to_register:
            class_name = cls.__name__
            setattr(self.Base.classes, class_name, cls)

    def close(self):
        self.session.close()
        self.engine.dispose()

 
