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

from bloom_lims.db import BLOOMdb3


os.makedirs("logs", exist_ok=True)

def get_clean_timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def setup_logging():
    # uvicorn to capture logs from all libs
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Define the log file name with a timestamp
    log_filename = f"logs/bdb_objs_{get_clean_timestamp()}.log"

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
    cast,
    func,
    select
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

from sqlalchemy.sql import alias
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



class BloomObj:
    def __init__(
        self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False
    ):  # ERROR -- the is_deleted flag should be set, I think, at the db level...
        self.logger = logging.getLogger(__name__ + ".BloomObj")
        self.logger.debug("Instantiating BloomObj")

        # Zebra Day Print Manager
        self.zpld = zdpm.zpl()
        if cfg_printers:
            self._config_printers()


        # Move the  fedex and zebra stuff outside these objs
        if cfg_fedex:
            try:
                self.track_fedex = FTD.FedexTrack()
            except Exception as e:
                self.track_fedex = None
        else:
            self.track_fedex = None
    
        self._bdb = bdb
        self.is_deleted = is_deleted
        self.session = bdb.session
        self.Base = bdb.Base


    def _rebuild_printer_json(self, lab="BLOOM"):
        self.zpld.probe_zebra_printers_add_to_printers_json(lab=lab)
        self.zpld.save_printer_json(self.zpld.printers_filename.split("zebra_day")[-1])
        self._config_printers()

    def _config_printers(self):
        if len(self.zpld.printers["labs"].keys()) == 0:
            self.logger.warning(
                "No printers found, attempting to rebuild printer json\n\n"
            )
            self.logger.warning(
                'This may take a few minutes, lab code will be set to "BLOOM" ... please sit tight...\n\n'
            )
            self._rebuild_printer_json()

        self.printer_labs = self.zpld.printers["labs"].keys()
        self.selected_lab = sorted(self.printer_labs)[0]
        self.site_printers = self.zpld.printers["labs"][self.selected_lab].keys()
        _zpl_label_styles = []
        for zpl_f in os.listdir(
            os.path.dirname(self.zpld.printers_filename) + "/label_styles/"
        ):
            if zpl_f.endswith(".zpl"):
                _zpl_label_styles.append(zpl_f.removesuffix(".zpl"))
        self.zpl_label_styles = sorted(_zpl_label_styles)
        self.selected_label_style = "tube_2inX1in"

    def set_printers_lab(self, lab):
        self.selected_lab = lab

    def get_lab_printers(self, lab):
        self.selected_lab = lab
        try:
            self.site_printers = self.zpld.printers["labs"][self.selected_lab].keys()
        except Exception as e:
            self.logger.error(f"Error getting printers for lab {lab}")
            self.logger.error(e)
            self.logger.error(
                "\n\n\nAttempting to rebuild printer json !!! THIS WILL TAKE TIME !!!\n\n\n"
            )
            self._rebuild_printer_json()

    def print_label(
        self,
        lab=None,
        printer_name=None,
        label_zpl_style="tube_2inX1in",
        euid="",
        alt_a="",
        alt_b="",
        alt_c="",
        alt_d="",
        alt_e="",
        alt_f="",
        print_n=1,
    ):

        bc = self.zpld.print_zpl(
            lab=lab,
            printer_name=printer_name,
            uid_barcode=euid,
            alt_a=alt_a,
            alt_b=alt_b,
            alt_c=alt_c,
            alt_d=alt_d,
            alt_e=alt_e,
            alt_f=alt_f,
            label_zpl_style=label_zpl_style,
            client_ip="pkg",
            print_n=print_n,
        )

    # For use by the cytoscape UI in order to determine if the dag needs regenerating
    def get_most_recent_schema_audit_log_entry(self):
        return (
            self.session.query(self.Base.classes.audit_log)
            .order_by(desc(self.Base.classes.audit_log.changed_at))
            .first()
        )

    # centralizing creation more cleanly.
    def create_instance(self, template_euid, json_addl_overrides={}):
        """Given an EUID for an object template, instantiate an instance from the template.
            No child objects defined by the tmplate will be generated.

            json_addl_overrides is a dict of key value pairs that will be merged into the json_addl of the template, with new keys created and existing keys over written.
        Args:
            template_euid (_type_): _description_
        """

        self.logger.debug(f"Creating instance from template EUID {template_euid}")

        template = self.get_by_euid(template_euid)

        if not template:
            self.logger.debug(f"No template found with euid: " + template_euid)
            return

        is_singleton = (
            False if template.json_addl.get("singleton", "0") in [0, "0"] else True
        )

        cname = template.polymorphic_discriminator.replace("_template", "_instance")
        parent_instance = getattr(self.Base.classes, f"{cname}")(
            name=template.name,
            btype=template.btype,
            b_sub_type=template.b_sub_type,
            version=template.version,
            json_addl=template.json_addl,
            template_uuid=template.uuid,
            bstatus=template.bstatus,
            super_type=template.super_type,
            is_singleton=is_singleton,
            polymorphic_discriminator=template.polymorphic_discriminator.replace(
                "_template", "_instance"
            ),
        )
        # Lots of fun stuff happening when instantiating action_imports!
        ai = (
            self._create_action_ds(parent_instance.json_addl["action_imports"])
            if "action_imports" in parent_instance.json_addl
            else {}
        )
        try:
            json_addl_overrides["action_groups"] = ai
            _update_recursive(parent_instance.json_addl, json_addl_overrides)
            self.session.add(parent_instance)
            ##self.session.flush()
            self.session.commit()
        except Exception as e:
            self.logger.error(f"Error creating instance from template {template_euid}")
            self.logger.error(e)
            self.session.rollback()
            raise Exception(
                f"Error creating instance from template {template_euid} ... {e} .. Likely Singleton Violation"
            )

        return parent_instance

    def create_instances_from_uuid(self, uuid):
        return self.create_instances(self.get(uuid).euid)

    # fix naming, instance_type==table_name_prefix
    def create_instances(self, template_euid):
        """
        IMPORTANTLY: this method creates the requested object from the template, and also will recurse one level to create any children objects defined by the template.
        You get back an array with the first element being the parent the second an array of children.

        Create instances from exsiting templates in the *_template table that the euid is a member of.
        The class subclassing is an experiment, see the docs (hopefully) for more, in short:
            TABLE_template entries hold the TABLE_instance definitions (and to a large extend, the TABLE_instance_lineage as well)
            TABLE_template is seeded initially from json files in
            bloom_lims/config/{container,content,workflow,workflow_step,equipment,data,test_requisition,...}/*.json
            These are only used to seed the templates... the idea is to allow users to add subtypes as they see fit. (TBD)

            ~ TABLE_template/{btype}/{b_sub_type}/{version} is the pattern used to for the template table name
        This is a recursive function that will only create one level of children instances.

        Args:
            template_euid (_type_): a template euid of the pattern [A-Z][A-Z]T[0-9]+ , which is a nicety and nothing at all is ever inferred from the prefix.
            For more on enterprise uuids see: my rants, and (need to find stripe primary ref: https://clerk.com/blog/generating-sortable-stripe-like-ids-with-segment-ksuids)

        Returns:
            [[],[]]: arr[0][:] are parents (presently, there is only ever 1 parent), arr[1][:] are children, if any.
        """

        self.logger.debug(f"Creating instances from template EUID {template_euid}")
        template = self.get_by_euid(
            template_euid
        )  # needed to get this for the child recrods if any
        parent_instance = self.create_instance(template_euid)
        ret_objs = [[], []]
        ret_objs[0].append(parent_instance)

        # template_json_addl = template.json_addl
        if "instantiation_layouts" in template.json_addl:
            ret_objs = self._process_instantiation_layouts(
                template.json_addl["instantiation_layouts"],
                parent_instance,
                ret_objs,
            )
        ##self.session.flush()
        self.session.commit()

        return ret_objs

    # I am of two minds re: if actions should be full objects, or pseudo-objects as they are now...
    def _create_action_ds(self, action_imports):
        ret_ds = {}
        for group in action_imports:
            ret_ds[group] = {}
            ret_ds[group]["actions"] = {}
            ret_ds[group]["group_order"] = action_imports[group]["group_order"]
            ret_ds[group]["group_name"] = action_imports[group]["group_name"]
            for ai in action_imports[group]["actions"]:
                sl = ai.lstrip("/").split("/")
                super_type = None if sl[0] == "*" else sl[0]
                btype = None if sl[1] == "*" else sl[1]
                b_sub_type = None if sl[2] == "*" else sl[2]
                version = None if sl[3] == "*" else sl[3]

                res = self.query_template_by_component_v2(
                    super_type, btype, b_sub_type, version
                )
                print(ai)
                if len(res) == 0:
                    raise Exception(f"Action import {ai} not found in database")

                for r in res:
                    action_key = f"{r.super_type}/{r.btype}/{r.b_sub_type}/{r.version}"

                    ret_ds[group]["actions"][action_key] = r.json_addl[
                        "action_template"
                    ]

                    #  I'm allowing overrides to the action properties FROM
                    # The non-action object action definition.  Its mostly shaky b/c the overrides are applied to all actions
                    # in the matched group... so, when all core are imported for example, an override will match all
                    # I think...  for singleton imports should be ok.
                    # this is to be used mostly for the assay links for test requisitions
                    _update_recursive(
                        ret_ds[group]["actions"][action_key],
                        action_imports[group]["actions"][ai],
                    )

        return ret_ds

    def _process_instantiation_layouts(
        self,
        instantiation_layouts,
        parent_instance,
        ret_objs,
    ):
        # Revisit the lineage set creation, this will not behave as expected if the json templates define more than 1 level deep children.
        ## or is this desireable, and the referenced children should reference thier children... crazy town begins at this level...
        for row in instantiation_layouts:
            for ds in row:
                for i in ds:
                    layout_str = i
                    layout_ds = ds[i]
                    child_instance = self._create_child_instance(layout_str, layout_ds)
                    lineage_record = self.Base.classes.generic_instance_lineage(
                        parent_instance_uuid=parent_instance.uuid,
                        child_instance_uuid=child_instance.uuid,
                        name=f"{parent_instance.name} :: {child_instance.name}",
                        btype=parent_instance.btype,
                        b_sub_type=parent_instance.b_sub_type,
                        version=parent_instance.version,
                        json_addl=parent_instance.json_addl,
                        bstatus=parent_instance.bstatus,
                        super_type=parent_instance.super_type,
                        parent_type=parent_instance.polymorphic_discriminator,
                        child_type=child_instance.polymorphic_discriminator,
                        polymorphic_discriminator=f"{parent_instance.super_type}_instance_lineage",
                    )
                    self.session.add(lineage_record)
                    ##self.session.flush()
                    ret_objs[1].append(child_instance)

        return ret_objs

    def create_generic_instance_lineage_by_euids(
        self, parent_instance_euid, child_instance_euid, relationship_type="generic"
    ):
        parent_instance = self.get_by_euid(parent_instance_euid)
        child_instance = self.get_by_euid(child_instance_euid)
        lineage_record = self.Base.classes.generic_instance_lineage(
            parent_instance_uuid=parent_instance.uuid,
            child_instance_uuid=child_instance.uuid,
            name=f"{parent_instance.name} :: {child_instance.name}",
            btype=parent_instance.btype,
            b_sub_type=parent_instance.b_sub_type,
            version=parent_instance.version,
            json_addl=parent_instance.json_addl,
            bstatus=parent_instance.bstatus,
            super_type="generic",
            parent_type=f"{parent_instance.super_type}:{parent_instance.btype}:{parent_instance.b_sub_type}:{parent_instance.version}",
            child_type=f"{child_instance.super_type}:{child_instance.btype}:{child_instance.b_sub_type}:{child_instance.version}",
            polymorphic_discriminator=f"generic_instance_lineage",
            relationship_type=relationship_type,
        )
        self.session.add(lineage_record)
        self.session.flush()
        # self.session.commit()

        return lineage_record

    def create_instance_by_code(self, layout_str, layout_ds):
        ret_obj = self._create_child_instance(layout_str, layout_ds)

        return ret_obj

    def _create_child_instance(self, layout_str, layout_ds):
        (
            super_type,
            btype,
            b_sub_type,
            version,
            defaults,
        ) = self._parse_layout_string(layout_str)

        defaults_ds = {}
        ## is this supposed to be coming from the defaults arg above??? hmmm

        if "json_addl" in layout_ds:
            defaults_ds = layout_ds["json_addl"]

        # Not implementing now, assuming all are 1.0
        ## !!! I THINK * IS A POOR IDEA NOW.... considering * to == 1.0 now
        if version == "*":
            version = "1.0"

        template = self.query_template_by_component_v2(
            super_type, btype, b_sub_type, version
        )[0]

        new_instance = self.create_instance(template.euid)
        _update_recursive(new_instance.json_addl, defaults_ds)
        flag_modified(new_instance, "json_addl")
        ##self.session.flush()
        self.session.commit()

        return new_instance

    def _parse_layout_string(self, layout_str):
        parts = layout_str.split("/")
        table_name = parts[0]  # table name now called 'super_type'
        btype = parts[1] if len(parts) > 1 else "*"
        b_sub_type = parts[2] if len(parts) > 2 else "*"
        version = (
            parts[3] if len(parts) > 3 else "*"
        )  # Assuming the version is always the third part
        defaults = (
            parts[4] if len(parts) > 4 else ""
        )  # Assuming the defaults is always the fourth part
        return table_name, btype, b_sub_type, version, defaults

    # json additional information validators
    def validate_object_vs_pattern(self, obj, pattern):
        """
        Validates if a given object matches the given pattern

        Args:
            obj _type_: _description_
            pattern _type_: _description_

        Returns:
            _type_: bool()
        """

        # Parse the JSON additional information of the object
        classn = (
            str(obj.__class__)
            .split(".")[-1]
            .replace(">", "")
            .replace("_instance", "")
            .replace("'", "")
        )

        obj_type_info = f"{classn}/{obj.btype}/{obj.b_sub_type}/{obj.version}"

        # Check if the object matches the pattern
        compiled_pattern = re.compile(pattern)
        match = compiled_pattern.search(obj_type_info)

        if match:
            return True

        return False

    """
    get methods.  get() assumes a uuid, which is funny as its rarely used. get_by_euid() is the workhorse.
    """

    # It is VERY nice to be able to query all three instance related tables in one go.
    # Admitedly, this is a far scaled back remnant of a far more elaborate and hair rasising situation when there were more tables.
    # There is benefit
    def get(self, uuid):
        """Global query for uuid across all tables in schema with 'uuid' field
            note does not handle is_deleted!
        Args:
            uuid str(): uuid string

        Returns:
            [] : Array of rows
        """
        res = (
            self.session.query(self.Base.classes.generic_instance)
            .filter(
                self.Base.classes.generic_instance.uuid == uuid,
                self.Base.classes.generic_instance.is_deleted == self.is_deleted,
            )
            .all()
        )
        res2 = (
            self.session.query(self.Base.classes.generic_template)
            .filter(
                self.Base.classes.generic_template.uuid == uuid,
                self.Base.classes.generic_template.is_deleted == self.is_deleted,
            )
            .all()
        )
        res3 = (
            self.session.query(self.Base.classes.generic_instance_lineage)
            .filter(
                self.Base.classes.generic_instance_lineage.uuid == uuid,
                self.Base.classes.generic_instance_lineage.is_deleted
                == self.is_deleted,
            )
            .all()
        )

        combined_result = res + res2 + res3

        if len(combined_result) > 1:
            raise Exception(
                f"Multiple {len(combined_results)} templates found for {uuid}"
            )
        elif len(combined_result) == 0:
            self.logger.debug(f"No template found with uuid:", uuid)
            self.logger.debug(
                f"On second thought, if we are using a UUID and there is no match.. exception:",
                uuid,
            )
            raise Exception(f"No template found with uuid:", uuid)
        else:
            return combined_result[0]

    # It is VERY nice to be able to query all three instance related tables in one go.
    # Admitedly, this is a far scaled back remnant of a far more elaborate and hair rasising situation when there were more tables.
    # There is benefit
    def get_by_euid(self, euid):
        """Global query for euid across all tables in schema with 'euid' field
           note: does not handle is_deleted!
        Args:
            euid str(): euid string

        Returns:
            [] : Array of rows
        """
        res = (
            self.session.query(self.Base.classes.generic_instance)
            .filter(
                self.Base.classes.generic_instance.euid == euid,
                self.Base.classes.generic_instance.is_deleted == self.is_deleted,
            )
            .all()
        )
        res2 = (
            self.session.query(self.Base.classes.generic_template)
            .filter(
                self.Base.classes.generic_template.euid == euid,
                self.Base.classes.generic_template.is_deleted == self.is_deleted,
            )
            .all()
        )
        res3 = (
            self.session.query(self.Base.classes.generic_instance_lineage)
            .filter(
                self.Base.classes.generic_instance_lineage.euid == euid,
                self.Base.classes.generic_instance_lineage.is_deleted
                == self.is_deleted,
            )
            .all()
        )

        combined_result = res + res2 + res3

        if len(combined_result) > 1:
            raise Exception(
                f"Multiple {len(combined_result)} templates found for {euid}"
            )
        elif len(combined_result) == 0:
            self.logger.debug(f"No template found with euid: " + euid)
            raise Exception(f"No template found with euid: " + euid)
        else:
            return combined_result[0]

    # This is the mechanism for finding the database object(s) which match the template reference pattern
    # V2... why?
    def query_instance_by_component_v2(
        self, super_type=None, btype=None, b_sub_type=None, version=None
    ):
        query = self.session.query(self.Base.classes.generic_instance)

        # Apply filters conditionally
        if super_type is not None:
            query = query.filter(
                self.Base.classes.generic_instance.super_type == super_type
            )
        if btype is not None:
            query = query.filter(self.Base.classes.generic_instance.btype == btype)
        if b_sub_type is not None:
            query = query.filter(
                self.Base.classes.generic_instance.b_sub_type == b_sub_type
            )
        if version is not None:
            query = query.filter(self.Base.classes.generic_instance.version == version)

        query = query.filter(
            self.Base.classes.generic_instance.is_deleted == self.is_deleted
        )

        # Execute the query
        return query.all()
    
    
    # should abstract to not assume properties key
    def get_unique_property_values(self, property_key, super_type=None, btype=None, b_sub_type=None, version=None):
               
        json_path = property_key.split("->")

        # Start building the query with the base table
        query = self.session.query(
            self.Base.classes.generic_instance
        )

        # Add filters based on the provided arguments
        if super_type:
            query = query.filter(self.Base.classes.generic_instance.super_type == super_type)
        if btype:
            query = query.filter(self.Base.classes.generic_instance.btype == btype)
        if b_sub_type:
            query = query.filter(self.Base.classes.generic_instance.b_sub_type == b_sub_type)
        if version:
            query = query.filter(self.Base.classes.generic_instance.version == version)

        # Add the JSON path extraction and distinct filtering after the base filters
        query = query.with_entities(
            func.distinct(
                func.jsonb_extract_path_text(
                    self.Base.classes.generic_instance.json_addl['properties'], *json_path
                )
            )
        ).filter(
            func.jsonb_extract_path_text(
                self.Base.classes.generic_instance.json_addl['properties'], *json_path
            ).isnot(None)
        )

        # Execute the query and get the results
        results = query.all()

        # Extract unique values from the query results
        unique_values = [value[0] for value in results if value[0] is not None]
        
        return unique_values


    def query_template_by_component_v2(
        self, super_type=None, btype=None, b_sub_type=None, version=None
    ):
        query = self.session.query(self.Base.classes.generic_template)

        # Apply filters conditionally
        if super_type is not None:
            query = query.filter(
                self.Base.classes.generic_template.super_type == super_type
            )
        if btype is not None:
            query = query.filter(self.Base.classes.generic_template.btype == btype)
            
        if b_sub_type is not None:
            query = query.filter(
                self.Base.classes.generic_template.b_sub_type == b_sub_type
            )
        if version is not None:
            query = query.filter(self.Base.classes.generic_template.version == version)

        query = query.filter(
            self.Base.classes.generic_template.is_deleted == self.is_deleted
        )
        # Execute the query
        return query.all()

   
    def query_user_audit_logs(self, username):
        logging.debug(f"Querying audit log for user: {username}")

        q = text(
            """
            SELECT
                al.rel_table_euid_fk AS euid,
                al.changed_by,
                al.operation_type,
                al.changed_at,
                COALESCE(gt.name, gi.name, gil.name) AS name,
                COALESCE(gt.polymorphic_discriminator, gi.polymorphic_discriminator, gil.polymorphic_discriminator) AS polymorphic_discriminator,
                COALESCE(gt.super_type, gi.super_type, gil.super_type) AS super_type,
                COALESCE(gt.btype, gi.btype, gil.btype) AS btype,
                COALESCE(gt.b_sub_type, gi.b_sub_type, gil.b_sub_type) AS b_sub_type,
                COALESCE(gt.bstatus, gi.bstatus, gil.bstatus) AS status,
                al.old_value,
                al.new_value
            FROM
                audit_log al
                LEFT JOIN generic_template gt ON al.rel_table_uuid_fk = gt.uuid
                LEFT JOIN generic_instance gi ON al.rel_table_uuid_fk = gi.uuid
                LEFT JOIN generic_instance_lineage gil ON al.rel_table_uuid_fk = gil.uuid
            WHERE
                al.changed_by = :username
            ORDER BY
                al.changed_at DESC;
            """
        )

        logging.debug(f"Executing query: {q}")

        result = self.session.execute(q, {'username': username})
        rows = result.fetchall()

        logging.debug(f"Query returned {len(rows)} rows")

        return rows
    # Aggregate Report SQL
    def query_generic_template_stats(self):
        q = text(
            """
            SELECT
                'Generic Template Summary' as Report,
                COUNT(*) as Total_Templates,
                COUNT(DISTINCT btype) as Distinct_Base_Types,
                COUNT(DISTINCT b_sub_type) as Distinct_Sub_Types,
                COUNT(DISTINCT super_type) as Distinct_Super_Types,
                MAX(created_dt) as Latest_Creation_Date,
                MIN(created_dt) as Earliest_Creation_Date,
                AVG(AGE(NOW(), created_dt)) as Average_Age,
                COUNT(CASE WHEN is_singleton THEN 1 END) as Singleton_Count
            FROM
                generic_template
            WHERE
                is_deleted = :is_deleted
        """
        )

        result = self.session.execute(q, {"is_deleted": self.is_deleted}).fetchall()

        # Define the column names based on your SELECT statement
        columns = [
            "Report",
            "Total_Templates",
            "Distinct_Base_Types",
            "Distinct_Sub_Types",
            "Distinct_Super_Types",
            "Latest_Creation_Date",
            "Earliest_Creation_Date",
            "Average_Age",
            "Singleton_Count",
        ]

        # Convert each row to a dictionary
        return [dict(zip(columns, row)) for row in result]

    def query_generic_instance_and_lin_stats(self):
        q = text(
            f"""
        SELECT
            -- Summary from generic_instance table
            'Generic Instance Summary' as Report,
            COUNT(*) as Total_Instances,
            COUNT(DISTINCT btype) as Distinct_Types,
            COUNT(DISTINCT polymorphic_discriminator) as Distinct_Polymorphic_Discriminators,
            COUNT(DISTINCT super_type) as Distinct_Super_Types,
            COUNT(DISTINCT b_sub_type) as Distinct_Sub_Types,
            MAX(created_dt) as Latest_Creation_Date,
            MIN(created_dt) as Earliest_Creation_Date,
            AVG(AGE(NOW(), created_dt)) as Average_Age
        FROM
            generic_instance
        WHERE
            is_deleted = {self.is_deleted}
            
        UNION ALL

        SELECT
            -- Summary from generic_instance_lineage table
            'Generic Instance Lineage Summary',
            COUNT(*) as Total_Lineages,
            COUNT(DISTINCT parent_type) as Distinct_Parent_Types,
            COUNT(DISTINCT child_type) as Distinct_Child_Types,
            COUNT(DISTINCT polymorphic_discriminator) as Distinct_Polymorphic_Discriminators,
            COUNT(DISTINCT super_type) as Distinct_Super_Types,
            MAX(created_dt) as Latest_Creation_Date,
            MIN(created_dt) as Earliest_Creation_Date,
            AVG(AGE(NOW(), created_dt)) as Average_Age
        FROM
            generic_instance_lineage
        WHERE
            is_deleted = {self.is_deleted};
        """
        )

        result = self.session.execute(q, {"is_deleted": self.is_deleted}).fetchall()

        # Define the column names based on your SELECT statement
        columns = [
            "Report",
            "Total_Instances",
            "Distinct_Types",
            "Distinct_Polymorphic_Discriminators",
            "Distinct_Super_Types",
            "Distinct_Sub_Types",
            "Latest_Creation_Date",
            "Earliest_Creation_Date",
            "Average_Age",
        ]

        # Convert each row to a dictionary
        return [dict(zip(columns, row)) for row in result]

    def query_cost_of_all_children(self, euid):
        # limited to 10,000 children right now...
        query = text(
            f"""
            WITH RECURSIVE descendants AS (
            -- Initial query to get the root instance
            SELECT gi.uuid, gi.euid, gi.json_addl, gi.created_dt
            FROM generic_instance gi
            WHERE gi.euid = '{euid}' -- Replace with your target euid

            UNION ALL

            -- Recursive part to get all descendants
            SELECT child_gi.uuid, child_gi.euid, child_gi.json_addl, child_gi.created_dt
            FROM generic_instance_lineage gil
            JOIN descendants d ON gil.parent_instance_uuid = d.uuid
            JOIN generic_instance child_gi ON gil.child_instance_uuid = child_gi.uuid
            WHERE NOT child_gi.is_deleted -- Assuming you want to exclude deleted instances
        )
        SELECT d.euid, 
            d.json_addl -> 'cogs' ->> 'cost' AS cost
        FROM descendants d
        WHERE d.json_addl ? 'cogs' AND 
            d.json_addl -> 'cogs' ? 'cost' AND 
            d.json_addl -> 'cogs' ->> 'cost' <> ''
        ORDER BY d.created_dt DESC -- Order the final result set        
        """
        )

        # Execute the query
        result = self.session.execute(query)

        # Extract euids and transit times from the result
        euid_cost_tuples = [(row[0], row[1]) for row in result]

        return euid_cost_tuples

    def query_all_fedex_transit_times_by_ay_euid(self, qx_euid):

        query = text(
            f"""SELECT gi.euid,
        gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0 ->> 'Transit_Time_sec' AS transit_time
        FROM generic_instance AS gi
        JOIN generic_instance_lineage AS gil1 ON gi.uuid = gil1.child_instance_uuid
        JOIN generic_instance AS gi_parent1 ON gil1.parent_instance_uuid = gi_parent1.uuid
        JOIN generic_instance_lineage AS gil2 ON gi_parent1.uuid = gil2.child_instance_uuid
        JOIN generic_instance AS gi_parent2 ON gil2.parent_instance_uuid = gi_parent2.uuid
        WHERE
        gi_parent2.euid = '{qx_euid}' AND
        gi.btype = 'package' AND
        jsonb_typeof(gi.json_addl -> 'properties') = 'object' AND
        jsonb_typeof(gi.json_addl -> 'properties' -> 'fedex_tracking_data') = 'array' AND
        jsonb_typeof((gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0)) = 'object' AND
        COALESCE(NULLIF(gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0 ->> 'Transit_Time_sec', ''), '0') >= '0';
        """
        )

        # Execute the query
        result = self.session.execute(query)

        # Extract euids and transit times from the result
        euid_transit_time_tuples = [(row[0], row[1]) for row in result]

        return euid_transit_time_tuples

    def fetch_graph_data_by_node_depth(self, start_euid, depth):
        # SQL query with placeholders for parameters
        query = text(
            f"""WITH RECURSIVE graph_data AS (
                SELECT 
                    gi.euid, 
                    gi.uuid, 
                    gi.name, 
                    gi.btype, 
                    gi.super_type, 
                    gi.b_sub_type, 
                    gi.version, 
                    0 AS depth,
                    NULL::text AS lineage_euid,
                    NULL::text AS lineage_parent_euid,
                    NULL::text AS lineage_child_euid,
                    NULL::text AS relationship_type
                FROM 
                    generic_instance gi
                WHERE 
                    gi.euid = '{start_euid}' AND gi.is_deleted = FALSE

                UNION

                SELECT 
                    gi.euid, 
                    gi.uuid, 
                    gi.name, 
                    gi.btype, 
                    gi.super_type, 
                    gi.b_sub_type, 
                    gi.version, 
                    gd.depth + 1,
                    gil.euid AS lineage_euid,
                    parent_instance.euid AS lineage_parent_euid,
                    child_instance.euid as lineage_child_euid,
                    gil.relationship_type
                FROM 
                    generic_instance_lineage gil
                JOIN 
                    generic_instance gi ON gi.uuid = gil.child_instance_uuid OR gi.uuid = gil.parent_instance_uuid
                JOIN 
                    generic_instance parent_instance ON gil.parent_instance_uuid = parent_instance.uuid
                JOIN 
                    generic_instance child_instance ON gil.child_instance_uuid = child_instance.uuid
                JOIN 
                    graph_data gd ON (gil.parent_instance_uuid = gd.uuid AND gi.uuid = gil.child_instance_uuid) OR 
                                    (gil.child_instance_uuid = gd.uuid AND gi.uuid = gil.parent_instance_uuid)
                WHERE 
                    gi.is_deleted = FALSE AND gd.depth < {depth}
            )
            SELECT DISTINCT * FROM graph_data;
        """
        )

        # Execute the query
        result = self.session.execute(query)
        return result

    def create_instance_by_template_components(
        self, super_type, btype, b_sub_type, version
    ):
        return self.create_instances(
            self.query_template_by_component_v2(super_type, btype, b_sub_type, version)[
                0
            ].euid
        )

    # Is this too special casey? Belong lower?
    def create_container_with_content(self, cx_quad_tup, mx_quad_tup):
        """ie CX=container, MX=content (material)
        ("content", "control", "giab-HG002", "1.0"),
        ("container", "tube", "tube-generic-10ml", "1.0")
        """
        container = self.create_instance(
            self.query_template_by_component_v2(
                cx_quad_tup[0], cx_quad_tup[1], cx_quad_tup[2], cx_quad_tup[3]
            )[0].euid
        )
        content = self.create_instance(
            self.query_template_by_component_v2(
                mx_quad_tup[0], mx_quad_tup[1], mx_quad_tup[2], mx_quad_tup[3]
            )[0].euid
        )

        container.json_addl["properties"]["name"] = content.json_addl["properties"][
            "name"
        ]
        flag_modified(container, "json_addl")
        ##self.session.flush()
        self.create_generic_instance_lineage_by_euids(container.euid, content.euid)
        self.session.commit()

        return container, content

    # Delete Methods
    # Do not cascade delete!

    def delete(self, uuid=None, euid=None):
        if (euid == None and uuid == None) or (euid != None and uuid != None):
            raise Exception("Must specify one of euid or uuid, not both or neither")
        obj = None
        if hasattr(uuid, "euid"):
            obj = uuid
        elif euid:
            obj = self.get_by_euid(euid).uuid
        else:
            obj = self.get(uuid)

        obj.is_deleted = True
        ##self.session.flush()
        self.session.commit()

    def delete_by_euid(self, euid):
        return self.delete(euid=euid)

    def delete_by_uuid(self, uuid):
        return self.delete(uuid=uuid)

    def delete_obj(self, obj):
        return self.delete(uuid=obj.uuid)

    #
    # Global Object Actions
    #
    def do_action(self, euid, action, action_group, action_ds, now_dt=""):

        r = None
        action_method = action_ds["method_name"]
        now_dt = get_datetime_string()
        if action_method == "do_action_set_object_status":
            r = self.do_action_set_object_status(euid, action_ds, action_group, action)
        elif action_method == "do_action_print_barcode_label":
            r = self.do_action_print_barcode_label(euid, action_ds)

        elif action_method == "do_action_destroy_specimen_containers":
            r = self.do_action_destroy_specimen_containers(euid, action_ds)
        elif action_method == "do_action_create_package_and_first_workflow_step_assay":
            r = self.do_action_create_package_and_first_workflow_step_assay(
                euid, action_ds
            )
        elif action_method == "do_action_move_workset_to_another_queue":
            r = self.do_action_move_workset_to_another_queue(euid, action_ds)
        elif action_method == "do_stamp_plates_into_plate":
            r = self.do_stamp_plates_into_plate(euid, action_ds)
        elif action_method == "do_action_download_file":
            r = self.do_action_download_file(euid, action_ds)
        elif action_method == "do_action_add_file_to_file_set":
            r = self.do_action_add_file_to_file_set(euid, action_ds)
        elif action_method == "do_action_remove_file_from_file_set":
            r = self.do_action_remove_file_from_file_set(euid, action_ds)
        elif action_method == "do_action_add_relationships":
            r = self.do_action_add_relationships(euid, action_ds)
        else:
            raise Exception(f"Unknown do_action method {action_method}")

        self._do_action_base(euid, action, action_group, action_ds, now_dt)
        return r

    def do_action_add_file_to_file_set(self, file_set_euid, action_ds):
        bfs = BloomFileSet(BLOOMdb3())
        bfs.add_files_to_file_set(
            euid=file_set_euid, file_euid=[action_ds["captured_data"]["file_euid"]]
        )

    def do_action_remove_file_from_file_set(self, file_set_euid, action_ds):
        bfs = BloomFileSet(BLOOMdb3())
        bfs.remove_files_from_file_set(
            euid=file_set_euid, file_euid=[action_ds["captured_data"]["file_euid"]]
        )

    def do_action_add_relationships(self, euid, action_ds):

        euid_obj = self.get_by_euid(euid)
        lineage_to_create = action_ds["captured_data"]["lineage_type_to_create"]
        relationship_type = action_ds["captured_data"]["relationship_type"]
        euids = action_ds["captured_data"]["euids"]

        # euids is the text from a textareas, process each and assign lineage
        for a_euid in euids.split("\n"):
            if a_euid != "":
                if lineage_to_create == "parent":
                    self.create_generic_instance_lineage_by_euids(
                        a_euid, euid, relationship_type
                    )
                elif lineage_to_create == "child":
                    self.create_generic_instance_lineage_by_euids(
                        euid, a_euid, relationship_type
                    )
                else:
                    self.logger.exception(
                        f"Unknown lineage type {lineage_to_create}, requires 'parent' or 'child'"
                    )
                    raise Exception(
                        f"Unknown lineage type {lineage_to_create}, requires 'parent' or 'child'"
                    )

        return euid_obj

    def ret_plate_wells_dict(self, plate):
        plate_wells = {}
        for lin in plate.parent_of_lineages:
            if lin.child_instance.btype == "well":

                well = lin.child_instance
                content_arr = []
                for c in well.parent_of_lineages:
                    if c.child_instance.super_type == "content":
                        content_arr.append(c.child_instance)
                content = None
                if len(content_arr) == 0:
                    pass
                elif len(content_arr) == 1:
                    content = content_arr[0]
                else:
                    self.logger.exception(
                        f"More than one content found for well {well.euid}"
                    )
                    raise Exception(f"More than one content found for well {well.euid}")

                plate_wells[lin.child_instance.json_addl["cont_address"]["name"]] = (
                    lin.child_instance,
                    content,
                )

        return plate_wells

    def do_action_download_file(self, euid, action_ds):

        bf = BloomFile(BLOOMdb3())
        dl_file = bf.download_file(
            euid=euid,
            include_metadata=(
                True
                if action_ds["captured_data"]["create_metadata_file"] in ["yes"]
                else False
            ),
            save_path="./tmp/",
            save_pattern=action_ds["captured_data"]["download_type"],
        )
        return dl_file

    def do_stamp_plates_into_plate(self, euid, action_ds):
        # Taking a stab at moving to a non obsessive commit world

        euid_obj = self.get_by_euid(euid)

        dest_plate = self.get_by_euid(
            action_ds["captured_data"]["Destination Plate EUID"]
        )
        source_plates = []
        source_plates_well_digested = []
        for source_plt_euid in action_ds["captured_data"]["source_barcodes"].split(
            "\n"
        ):
            spo = self.get_by_euid(source_plt_euid)
            source_plates.append(spo)
            source_plates_well_digested.append(self.ret_plate_wells_dict(spo))

        wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.create_generic_instance_lineage_by_euids(euid_obj.euid, wfs.euid)

        self.create_generic_instance_lineage_by_euids(wfs.euid, dest_plate.euid)

        for spo in source_plates:
            self.create_generic_instance_lineage_by_euids(wfs.euid, spo.euid)

        # For all plates being stamped into the destination, link all source plate wells to the destination plate wells, and the contensts of source wells to destination wells.
        # Further, if a dest well is empty, create a new content instance for it and link appropriately.
        for dest_well in dest_plate.parent_of_lineages:
            if dest_well.child_instance.btype == "well":
                well_name = dest_well.child_instance.json_addl["cont_address"]["name"]
                for spod in source_plates_well_digested:
                    if well_name in spod:
                        self.create_generic_instance_lineage_by_euids(
                            spod[well_name][0].euid, dest_well.child_instance.euid
                        )
                        if spod[well_name][1] != None:
                            for dwc in dest_well.child_instance.parent_of_lineages:
                                if dwc.child_instance.super_type == "content":
                                    self.create_generic_instance_lineage_by_euids(
                                        spod[well_name][1].euid, dwc.child_instance.euid
                                    )
                        del spod[well_name]
        ## TODO
        ### IF there are any source wells left, create new content instances for them and link to the dest wells
        remaining_wells = 0
        for i in source_plates_well_digested:
            for j in i:
                remaining_wells += 1
        if remaining_wells > 0:
            self.logger.exception(
                f"ERROR: {remaining_wells} wells left over after stamping"
            )
            self.session.rollback()
            raise Exception(f"ERROR: {remaining_wells} wells left over after stamping")

        self.session.commit()

        return wfs

    def do_action_move_workset_to_another_queue(self, euid, action_ds):

        wfset = self.get_by_euid(euid)
        action_ds["captured_data"]["q_selection"]

        # EXTRAORDINARILY SLOPPY.  I AM IN A REAL RUSH FOR FEATURES THO :-/
        destination_q = ""
        (super_type, btype, b_sub_type, version) = (
            action_ds["captured_data"]["q_selection"].lstrip("/").rstrip("/").split("/")
        )
        for q in (
            wfset.child_of_lineages[0]
            .parent_instance.child_of_lineages[0]
            .parent_instance.parent_of_lineages
        ):
            if (
                q.child_instance.btype == btype
                and q.child_instance.b_sub_type == b_sub_type
            ):
                destination_q = q.child_instance
                break

        if len(wfset.child_of_lineages.all()) != 1 or destination_q == "":
            self.logger.exception(f"ERROR: {action_ds['captured_data']['q_selection']}")
            self.logger.exception(f"ERROR: {action_ds['captured_data']['q_selection']}")
            raise Exception(f"ERROR: {action_ds['captured_data']['q_selection']}")

        lineage_link = wfset.child_of_lineages[0]
        self.create_generic_instance_lineage_by_euids(destination_q.euid, wfset.euid)
        self.delete_obj(lineage_link)
        ##self.session.flush()
        self.session.commit()

    # Doing this globally for now
    def do_action_create_package_and_first_workflow_step_assay(
        self, euid, action_ds={}
    ):
        wf = self.get_by_euid(euid)

        #'workflow_step_to_attach_as_child': {'workflow_step/queue/all-purpose/1.0/': {'json_addl': {'properties': {'name': 'hey user, SET THIS NAME ',

        active_workset_q_wfs = ""
        (super_type, btype, b_sub_type, version) = (
            list(action_ds["workflow_step_to_attach_as_child"].keys())[0]
            .lstrip("/")
            .rstrip("/")
            .split("/")
        )
        for pwf_child_lin in wf.parent_of_lineages:
            if (
                pwf_child_lin.child_instance.btype == btype
                and pwf_child_lin.child_instance.b_sub_type == b_sub_type
            ):
                active_workset_q_wfs = pwf_child_lin.child_instance
                break
        if active_workset_q_wfs == "":
            self.logger.exception(
                f"ERROR: {action_ds['workflow_step_to_attach_as_child'].keys()}"
            )
            raise Exception(
                f"ERROR: {action_ds['workflow_step_to_attach_as_child'].keys()}"
            )

        # 1001897582860000245100773464327825
        fx_opsmd = {}

        try:
            fx_opsmd = self.track_fedex.get_fedex_ops_meta_ds(
                action_ds["captured_data"]["Tracking Number"]
            )
            # Check the transit time is calculated
            tt = fx_opsmd[0]["Transit_Time_sec"]
        except Exception as e:
            self.logger.exception(f"ERROR: {e}")

        action_ds["captured_data"]["Fedex Tracking Data"] = fx_opsmd

        wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.create_generic_instance_lineage_by_euids(
                active_workset_q_wfs.euid, wfs.euid
            )
            ##self.session.flush()
            self.session.commit()

        package = ""
        for layout_str in action_ds["new_container_obj"]:
            for cv_k in action_ds["captured_data"]:
                action_ds["new_container_obj"][layout_str]["json_addl"]["properties"][
                    "fedex_tracking_data"
                ] = fx_opsmd
                action_ds["new_container_obj"][layout_str]["json_addl"]["properties"][
                    cv_k
                ] = action_ds["captured_data"][cv_k]

            package = self.create_instance_by_code(
                layout_str, action_ds["new_container_obj"][layout_str]
            )
            ##elf.session.flush()
            self.session.commit()

        ##self.session.flush()
        self.session.commit()

        self.create_generic_instance_lineage_by_euids(wfs.euid, package.euid)
        self.session.commit()
        return wfs

        # There are A LOT of common patterns with these actions, and only a small number of them too. ABSCRACT MOAR

        # Get the euid obj, which is the AY

        # Get the AY child workflow queue object defined by the action

        # Create the new workset object

        # Create the new package object, wiuth the captured data from the action

        # link package to workset
        # link workset to workflow queue object

    def do_action_print_barcode_label(self, euid, action_ds={}):
        """_summary_

        Args:
            euid (str()): bloom obj EUID
            action (str()): action name from object json_addl['actions']
            action_ds (dict): the dictionary keyed by the object json_addl['action'][action]
        """
        bobj = self.get_by_euid(euid)

        lab = action_ds.get("lab", "")
        printer_name = action_ds.get("printer_name", "")
        label_zpl_style = action_ds.get("label_style", "")
        alt_a = (
            action_ds.get("alt_a", "")
            if not PGLOBAL
            else f"{bobj.b_sub_type}-{bobj.version}"
        )
        alt_b = (
            action_ds.get("alt_b", "")
            if not PGLOBAL
            else bobj.json_addl.get("properties", {}).get("name", "__namehere__")
        )
        alt_c = (
            action_ds.get("alt_c", "")
            if not PGLOBAL
            else bobj.json_addl.get("properties", {}).get("lab_code", "N/A")
        )
        alt_d = action_ds.get("alt_d", "")
        alt_e = (
            action_ds.get("alt_e", "")
            if not PGLOBAL
            else str(bobj.created_dt).split(" ")[0]
        )
        alt_f = action_ds.get("alt_f", "")

        self.logger.info(
            f"PRINTING BARCODE LABEL for {euid} at {lab} .. {printer_name} .. {label_zpl_style} \n"
        )

        self.print_label(
            lab=lab,
            printer_name=printer_name,
            label_zpl_style=label_zpl_style,
            euid=euid,
            alt_a=alt_a,
            alt_b=alt_b,
            alt_c=alt_c,
            alt_d=alt_d,
            alt_e=alt_e,
            alt_f=alt_f,
        )

    def do_action_set_object_status(
        self, euid, action_ds={}, action_group=None, action=None
    ):
        bobj = self.get_by_euid(euid)

        now_dt = get_datetime_string()
        un = action_ds.get("curr_user", "bloomdborm")
        status = action_ds["captured_data"]["object_status"]
        try:
            if status == "in_progress":
                if bobj.bstatus in ["complete", "abandoned", "failed", "in_progress"]:
                    raise Exception(
                        f"Workflow step {euid} is already {bobj.bstatus}, cannot set to {status}"
                    )

                if "step_properties" in bobj.json_addl:
                    bobj.json_addl["step_properties"]["start_operator"] = un
                    bobj.json_addl["step_properties"]["start_timestamp"] = now_dt
                bobj.json_addl["properties"]["status_timestamp"] = now_dt
                bobj.json_addl["properties"]["start_operator"] = un

            if status in ["complete", "abandoned", "failed"]:
                if bobj.bstatus in ["complete", "abandoned", "failed"]:
                    raise Exception(
                        f"Workflow step {euid} is already in a terminal {bobj.bstatus}, cannot set to {status}"
                    )

                bobj.json_addl["action_groups"][action_group]["actions"][action][
                    "action_enabled"
                ] = "0"

                if "step_properties" in bobj.json_addl:
                    bobj.json_addl["step_properties"]["end_operator"] = un
                    bobj.json_addl["step_properties"]["end_timestamp"] = now_dt

                bobj.json_addl["properties"]["end_timestamp"] = now_dt
                bobj.json_addl["properties"]["end_operator"] = un

            bobj.bstatus = status

            flag_modified(bobj, "json_addl")
            flag_modified(bobj, "bstatus")
            ##self.session.flush()
            self.session.commit()
        except Exception as e:
            self.logger.exception(f"ERROR: {e}")
            self.session.rollback()
            raise e

        return bobj

    def _do_action_base(
        self, euid, action, action_group, action_ds, now_dt=get_datetime_string()
    ):
        """_summary_

        Args:
            wfs_euid (_type_): _description_
            action (_type_): _description_
            action_ds (_type_): _description_
            now_dt (_type_, optional): _description_. Defaults to get_datetime_string().

        Returns:
            _type_: _description_
        """
        self.logger.debug(
            f"Completing Action: {action} for {euid} at {now_dt}  with {action_ds}"
        )
        bobj = self.get_by_euid(euid)

        #                 #bobj.json_addl["actions"][action]["action_executed"]

        if "action_groups" in bobj.json_addl:

            curr_action_count = int(
                bobj.json_addl["action_groups"][action_group]["actions"][action][
                    "action_executed"
                ]
            )
            new_action_count = curr_action_count + 1

            max_action_count = int(
                bobj.json_addl["action_groups"][action_group]["actions"][action][
                    "max_executions"
                ]
            )
            if max_action_count > 0 and new_action_count >= max_action_count:
                bobj.json_addl["action_groups"][action_group]["actions"][action][
                    "action_enabled"
                ] = "0"
            bobj.json_addl["action_groups"][action_group]["actions"][action][
                "action_executed"
            ] = f"{new_action_count}"

            for deactivate_action in action_ds.get(
                "deactivate_actions_when_executed", []
            ):
                # This is meant to reach into other actions for when this action is executed, but has not been extended for the
                # new action_groups structure yet, so quietly allowing failuers for now.
                # THIS probably no longer should live in the action definition, but be defined in the action group w/the action group
                try:
                    bobj.json_addl["action_groups"][action_group]["actions"][action][
                        deactivate_action
                    ]["action_enabled"] = "0"
                except Exception as e:
                    self.logger.debug(
                        f"Failed to deactivate {deactivate_action} for {euid} at {now_dt}  with {action_ds}"
                    )

            bobj.json_addl["action_groups"][action_group]["actions"][action][
                "executed_datetime"
            ].append(now_dt)
            bobj.json_addl["action_groups"][action_group]["actions"][action][
                "action_user"
            ].append(action_ds.get("curr_user", "bloomdborm"))

        # from sqlalchemy.orm.attributes import flag_modified
        flag_modified(bobj, "json_addl")
        ##self.session.flush()
        self.session.commit()

        return bobj

    def query_audit_log_by_euid(self, euid):
        return (
            self.session.query(self.Base.classes.audit_log)
            .filter(self.Base.classes.audit_log.rel_table_euid_fk == euid)
            .all()
        )

    def check_lineages_for_btype(self, lineages, btype, parent_or_child=None):
        if parent_or_child == "parent":
            for lin in lineages:
                if lin.parent_instance.btype == btype:
                    return True
        elif parent_or_child == "child":
            for lin in lineages:
                if lin.child_instance.btype == btype:
                    return True
        else:
            raise Exception("Must specify parent or child")

        return False

    def get_cost_of_euid_children(self, euid):
        tot_cost = 0
        ctr = 0
        for ec_tups in self.query_cost_of_all_children(euid):
            tot_cost += float(ec_tups[1])
            ctr += 1
        return tot_cost if ctr > 0 else "na"

        # Start with the provided EUID
        initial_instance = (
            self.session.query(self.Base.classes.generic_instance)
            .filter_by(euid=euid)
            .first()
        )
        if initial_instance:
            return traverse_and_calculate_children_cogs(initial_instance)
        else:
            return 0

    def get_cogs_to_produce_euid(self, euid):

        # Function to fetch and calculate the COGS for a given object
        def calculate_cogs(orm_instance):
            if (
                "cogs" not in orm_instance.json_addl
                or "state" not in orm_instance.json_addl["cogs"]
            ):
                raise ValueError(
                    f"COGS or state information missing for EUID: {orm_instance.euid}"
                )

            if orm_instance.json_addl["cogs"]["state"] != "active":
                return 0

            cost = float(orm_instance.json_addl["cogs"]["cost"])
            fractional_cost = float(
                orm_instance.json_addl["cogs"].get("fractional_cost", 1)
            )
            allocation_type = orm_instance.json_addl["cogs"].get(
                "allocation_type", "single"
            )

            active_children = len(
                [
                    child
                    for child in orm_instance.child_of_lineages
                    if "cogs" in child.json_addl
                    and child.json_addl["cogs"].get("state") == "active"
                ]
            )
            if active_children == 0:
                active_children = 1.0
            return cost * float(fractional_cost) / float(active_children)

        # Recursive function to traverse the graph and accumulate COGS
        def traverse_history_and_calculate_cogs(orm_instance):
            total_cogs = calculate_cogs(orm_instance)

            # Traverse child_of_lineages to find parent instances and accumulate their COGS
            for lineage in orm_instance.child_of_lineages:
                parent_instance = lineage.parent_instance
                if parent_instance:
                    total_cogs += traverse_history_and_calculate_cogs(parent_instance)

            return total_cogs

        # Start with the provided EUID
        initial_instance = (
            self.session.query(self.Base.classes.generic_instance)
            .filter_by(euid=euid)
            .first()
        )
        if initial_instance:
            return traverse_history_and_calculate_cogs(initial_instance)
        else:
            return 0


    def search_objs_by_addl_metadata(
        self,
        file_search_criteria,
        search_greedy=True,
        btype=None,
        b_sub_type=None,
        super_type=None,
    ):
        query = self.session.query(self.Base.classes.generic_instance)
        
        def create_datetime_filter(key, value, conditions):
            start_datetime = value.get('start')
            end_datetime = value.get('end', start_datetime)
            if start_datetime > end_datetime:
                self.logger.exception(f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}")
                raise Exception(f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}")
            
            if start_datetime and end_datetime:
                json_path = key.split("->")
                
                non_empty_condition = and_(
                    func.jsonb_extract_path_text(self.Base.classes.generic_instance.json_addl, *json_path) != '',
                    func.jsonb_extract_path_text(self.Base.classes.generic_instance.json_addl, *json_path).isnot(None)
                )
                
                datetime_condition = cast(
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    ), 
                    DateTime
                ).between(start_datetime, end_datetime)
                
                combined_condition = and_(non_empty_condition, datetime_condition)
                
                conditions.append(combined_condition)
        
        def handle_jsonb_filter(key, value, conditions):
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key.endswith('_datetime') and isinstance(sub_value, dict):
                        create_datetime_filter(f"{key}->{sub_key}", sub_value, conditions)
                    else:
                        if isinstance(sub_value, list):
                            for item in sub_value:
                                jsonb_filter = {key: {sub_key: item}}
                                conditions.append(
                                    self.Base.classes.generic_instance.json_addl.op("@>")(
                                        json.dumps(jsonb_filter, default=str)
                                    )
                                )
                        else:
                            jsonb_filter = {key: {sub_key: sub_value}}
                            conditions.append(
                                self.Base.classes.generic_instance.json_addl.op("@>")(
                                    json.dumps(jsonb_filter, default=str)
                                )
                            )
            else:
                if isinstance(value, list):
                    for item in value:
                        jsonb_filter = {key: item}
                        conditions.append(
                            self.Base.classes.generic_instance.json_addl.op("@>")(
                                json.dumps(jsonb_filter, default=str)
                            )
                        )
                else:
                    jsonb_filter = {key: value}
                    conditions.append(
                        self.Base.classes.generic_instance.json_addl.op("@>")(
                            json.dumps(jsonb_filter, default=str)
                        )
                    )

        if search_greedy:
            # Greedy search: matching any of the provided search keys
            or_conditions = []
            for key, value in file_search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )
                handle_jsonb_filter(key, value, or_conditions)
            if or_conditions:
                query = query.filter(or_(*or_conditions))
        else:
            # Non-greedy search: matching all specified search terms
            and_conditions = []
            for key, value in file_search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )
                handle_jsonb_filter(key, value, and_conditions)
            if and_conditions:
                query = query.filter(and_(*and_conditions))

        if btype is not None:
            query = query.filter(self.Base.classes.generic_instance.btype == btype)

        if b_sub_type is not None:
            query = query.filter(
                self.Base.classes.generic_instance.b_sub_type == b_sub_type
            )

        if super_type is not None:
            query = query.filter(
                self.Base.classes.generic_instance.super_type == super_type
            )

        logging.info(f"Generated SQL: {str(query.statement)}")

        results = query.all()
        return [result.euid for result in results]

    def search_objs_by_addl_metadataOG(
        self,
        file_search_criteria,
        search_greedy=True,
        btype=None,
        b_sub_type=None,
        super_type=None,
    ):
        query = self.session.query(self.Base.classes.generic_instance)
        
        def create_datetime_filter(key, value, conditions):
            start_datetime = value.get('start')
            end_datetime = value.get('end', start_datetime )
            if start_datetime > end_datetime:
                self.logger.exception(f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}")
                raise Exception(f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}")
            
            if start_datetime and end_datetime:
                json_path = key.split("->")
                
                non_empty_condition = and_(
                    func.jsonb_extract_path_text(self.Base.classes.generic_instance.json_addl, *json_path) != '',
                    func.jsonb_extract_path_text(self.Base.classes.generic_instance.json_addl, *json_path).isnot(None)
                )
                
                datetime_condition = cast(
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    ), 
                    DateTime
                ).between(start_datetime, end_datetime)
                
                combined_condition = and_(non_empty_condition, datetime_condition)
                
                conditions.append(combined_condition)
            
        def handle_jsonb_filter(key, value, conditions):
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key.endswith('_datetime') and isinstance(sub_value, dict):
                        create_datetime_filter(f"{key}->{sub_key}", sub_value, conditions)
                    else:
                        jsonb_filter = {key: {sub_key: sub_value}}
                        conditions.append(
                            self.Base.classes.generic_instance.json_addl.op("@>")(
                                json.dumps(jsonb_filter, default=str)
                            )
                        )
            else:
                jsonb_filter = {key: value}
                conditions.append(
                    self.Base.classes.generic_instance.json_addl.op("@>")(
                        json.dumps(jsonb_filter, default=str)
                    )
                )

        if search_greedy:
            # Greedy search: matching any of the provided search keys
            or_conditions = []
            for key, value in file_search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )
                handle_jsonb_filter(key, value, or_conditions)
            if or_conditions:
                query = query.filter(or_(*or_conditions))
        else:
            # Non-greedy search: matching all specified search terms
            and_conditions = []
            for key, value in file_search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )
                handle_jsonb_filter(key, value, and_conditions)
            if and_conditions:
                query = query.filter(and_(*and_conditions))

        if btype is not None:
            query = query.filter(self.Base.classes.generic_instance.btype == btype)

        if b_sub_type is not None:
            query = query.filter(
                self.Base.classes.generic_instance.b_sub_type == b_sub_type
            )

        if super_type is not None:
            query = query.filter(
                self.Base.classes.generic_instance.super_type == super_type
            )

        logging.info(f"Generated SQL: {str(query.statement)}")

        results = query.all()
        return [result.euid for result in results]

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


class BloomContent(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_content(self, template_euid):
        """_summary_

        Args:
            template_euid (_type_): _description_

        Returns:
            _type_: _description_
        """

        return self.create_instances(template_euid)


class BloomWorkflow(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    # This can be made more widely useful now that i've detangled the wf-wfs special relationship
    def get_sorted_uuid(self, workflow_id):
        wfobj = self.get(workflow_id)

        def sort_key(child_instance):
            # Fetch the step_number if it exists, otherwise return a high value to sort it at the end
            return int(
                child_instance.json_addl["properties"].get("step_number", float("inf"))
            )

        # Assuming wfobj is your top-level object
        workflow_steps = []

        for lineage in wfobj.parent_of_lineages:
            child_instance = lineage.child_instance
            if child_instance.super_type == "workflow_step":
                workflow_steps.append(child_instance)
        workflow_steps.sort(key=sort_key)
        wfobj.workflow_steps_sorted = workflow_steps

        return wfobj

    # This can be made more widely useful now that i've detangled the wf-wfs special relationship
    def get_sorted_euid(self, workflow_euid):
        wfobj = self.get_by_euid(workflow_euid)

        def sort_key(child_instance):
            # Fetch the step_number if it exists, otherwise return a high value to sort it at the end
            return int(
                child_instance.json_addl["properties"].get("step_number", float("0"))
                if child_instance.json_addl["properties"].get(
                    "step_number", float("inf")
                )
                not in ["", None]
                else float("0")
            )

        # Assuming wfobj is your top-level object
        workflow_steps = []

        for lineage in wfobj.parent_of_lineages:
            child_instance = lineage.child_instance
            if child_instance.super_type == "workflow_step":
                workflow_steps.append(child_instance)
        workflow_steps.sort(key=sort_key)
        wfobj.workflow_steps_sorted = workflow_steps

        return wfobj

    def create_empty_workflow(self, template_euid):
        return self.create_instances(template_euid)

    def do_action(self, wf_euid, action, action_group, action_ds={}):

        action_method = action_ds["method_name"]
        now_dt = get_datetime_string()
        if action_method == "do_action_create_and_link_child":
            self.do_action_create_and_link_child(wf_euid, action_ds, None)
        elif action_method == "do_action_create_package_and_first_workflow_step":
            self.do_action_create_package_and_first_workflow_step(wf_euid, action_ds)
        elif action_method == "do_action_destroy_specimen_containers":
            self.do_action_destroy_specimen_containers(wf_euid, action_ds)
        else:
            return super().do_action(wf_euid, action, action_group, action_ds)

        return self._do_action_base(wf_euid, action, action_group, action_ds, now_dt)

    def do_action_destroy_specimen_containers(self, wf_euid, action_ds):
        wf = self.get_by_euid(wf_euid)
        wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.create_generic_instance_lineage_by_euids(wf.uuid, wfs.euid)
            # wfs.workflow_instance_uuid = wf.uuid
            ##self.session.flush()
            self.session.commit()

        wf.bstatus = "in_progress"
        flag_modified(wf, "bstatus")
        ##self.session.flush()
        self.session.commit()

        for euid in action_ds["captured_data"]["discard_barcodes"].split("\n"):
            try:
                a_container = self.get_by_euid(euid)
                a_container.bstatus = "destroyed"
                flag_modified(a_container, "bstatus")
                ##self.session.flush()
                self.session.commit()

                self.create_generic_instance_lineage_by_euids(
                    wfs.euid, a_container.euid
                )
                self.session.commit()

            except Exception as e:
                self.logger.exception(f"ERROR: {e}")
                self.logger.exception(f"ERROR: {e}")
                self.logger.exception(f"ERROR: {e}")
                # self.session.rollback()

    def do_action_create_package_and_first_workflow_step(self, wf_euid, action_ds={}):
        raise Exception("This is GARBAGE?")
        # DELETED A BUNCH OF STUFF... if needed, revert to previous commit


class BloomWorkflowStep(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_workflow_step(self, template_euid):
        return self.create_instances(template_euid)

    # NOTE!  This action business seems to be evolving around from a workflow step centered thing and
    #        feels like it would be better more generalized. For now, most actions being jammed through this approach, even if the parent is now a WFS
    # .      Though... also.... is there benefit to restricting actions to be required to be associated with a WFS?  Ask Adam his thoughts.
    def do_action(self, wfs_euid, action, action_group, action_ds={}):
        now_dt = get_datetime_string()

        action_method = action_ds["method_name"]
        if action_method == "do_action_create_and_link_child":
            self.do_action_create_and_link_child(wfs_euid, action_ds)
        elif action_method == "do_action_create_input":
            self.do_action_create_input(wfs_euid, action_ds)
        elif (
            action_method
            == "do_action_create_child_container_and_link_child_workflow_step"
        ):
            self.do_action_create_child_container_and_link_child_workflow_step(
                wfs_euid, action_ds
            )
        elif action_method == "do_action_create_test_req_and_link_child_workflow_step":
            self.do_action_create_test_req_and_link_child_workflow_step(
                wfs_euid, action_ds
            )
        elif action_method == "do_action_xcreate_test_req_and_link_child_workflow_step":
            self.do_action_xcreate_test_req_and_link_child_workflow_step(
                wfs_euid, action_ds
            )
        elif action_method == "do_action_ycreate_test_req_and_link_child_workflow_step":
            self.do_action_ycreate_test_req_and_link_child_workflow_step(
                wfs_euid, action_ds
            )
        elif action_method == "do_action_add_container_to_assay_q":
            self.do_action_add_container_to_assay_q(wfs_euid, action_ds)
        elif action_method == "do_action_fill_plate_undirected":
            self.do_action_fill_plate_undirected(wfs_euid, action_ds)
        elif action_method == "do_action_fill_plate_directed":
            self.do_action_fill_plate_directed(wfs_euid, action_ds)
        elif action_method == "do_action_link_tubes_auto":
            self.do_action_link_tubes_auto(wfs_euid, action_ds)
        elif action_method == "do_action_cfdna_quant":
            self.do_action_cfdna_quant(wfs_euid, action_ds)
        elif action_method == "do_action_stamp_copy_plate":
            self.do_action_stamp_copy_plate(wfs_euid, action_ds)
        elif action_method == "do_action_log_temperature":
            self.do_action_log_temperature(wfs_euid, action_ds)
        else:
            return super().do_action(wfs_euid, action, action_group, action_ds)

        return self._do_action_base(wfs_euid, action, action_group, action_ds, now_dt)

    def _add_random_values_to_plate(self, plate):
        for i in plate.parent_of_lineages:
            import random

            i.child_instance.json_addl["properties"]["quant_value"] = (
                float(random.randint(1, 20)) / 20
                if (
                    "cont_address" in i.child_instance.json_addl
                    and i.child_instance.json_addl["cont_address"]["name"] != "A1"
                )
                else 0
            )
            flag_modified(i.child_instance, "json_addl")
            self.session.commit()

    def do_action_log_temperature(self, wfs_euid, action_ds):
        now_dt = get_datetime_string()
        un = action_ds.get("curr_user", "bloomdborm")

        temp_c = action_ds["captured_data"]["Temperature (celcius)"]
        child_data = ""
        for dlayout_str in action_ds["child_container_obj"]:
            child_data = self.create_instance_by_code(
                dlayout_str, action_ds["child_container_obj"][dlayout_str]
            )
            child_data.json_addl["properties"]["temperature_c"] = temp_c
            child_data.json_addl["properties"]["temperature_timestamp"] = now_dt
            child_data.json_addl["properties"]["temperature_log_user"] = un
            flag_modified(child_data, "json_addl")
            self.create_generic_instance_lineage_by_euids(wfs_euid, child_data.euid)
            self.session.commit()

    def do_action_ycreate_test_req_and_link_child_workflow_step(
        self, wfs_euid, action_ds
    ):
        tri_euid = action_ds["captured_data"]["Test Requisition EUID"]
        container_euid = action_ds["captured_data"]["Tube EUID"]

        # In this case, deactivate any active actions to create or link this container available in other workflow steps
        deactivate_arr = [
            "create_test_req_and_link_child_workflow_step",
            "ycreate_test_req_and_link_child_workflow_step",
        ]
        ciobj = self.get_by_euid(container_euid)

        for i in ciobj.child_of_lineages:
            if i.polymorphic_discriminator == "generic_instance_lineage":
                for da in deactivate_arr:
                    if da in i.parent_instance.json_addl["actions"]:
                        i.parent_instance.json_addl["actions"][da][
                            "action_enabled"
                        ] = "0"
        flag_modified(i.parent_instance, "json_addl")
        ##self.session.flush()
        self.create_generic_instance_lineage_by_euids(tri_euid, container_euid)
        self.session.commit()

    def do_action_stamp_copy_plate(self, wfs_euid, action_ds):

        wfs = self.get_by_euid(wfs_euid)
        in_plt = self.get_by_euid(action_ds["captured_data"]["plate_euid"])
        wells_ds = {}
        for w in in_plt.parent_of_lineages:
            if w.child_instance.btype == "well":
                wells_ds[w.child_instance.json_addl["cont_address"]["name"]] = [
                    w.child_instance
                ]
                for wsl in w.child_instance.parent_of_lineages:
                    if wsl.child_instance.super_type in [
                        "content",
                        "sample",
                        "control",
                    ]:  ### AND ADD CHECK THEY SHARE SAME PARENT CONTAINER?
                        wells_ds[
                            w.child_instance.json_addl["cont_address"]["name"]
                        ].append(wsl.child_instance)
        child_wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            child_wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.session.commit()
        self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)

        new_plt_parts = self.create_instances_from_uuid(str(in_plt.template_uuid))
        new_plt = new_plt_parts[0][0]
        new_wells = new_plt_parts[1]
        self.create_generic_instance_lineage_by_euids(child_wfs.euid, new_plt.euid)
        self.create_generic_instance_lineage_by_euids(in_plt.euid, new_plt.euid)
        self.session.commit()

        for new_w in new_wells:
            nwn = new_w.json_addl["cont_address"]["name"]
            in_well = wells_ds[nwn][0]
            self.create_generic_instance_lineage_by_euids(in_well.euid, new_w.euid)
            if len(wells_ds[nwn]) > 1:
                in_samp = wells_ds[nwn][1]
                new_samp = self.create_instances_from_uuid(str(in_samp.template_uuid))[
                    0
                ][0]
                self.create_generic_instance_lineage_by_euids(
                    in_samp.euid, new_samp.euid
                )
                self.create_generic_instance_lineage_by_euids(new_w.euid, new_samp.euid)

        self.session.commit()

        return child_wfs

    def do_action_cfdna_quant(self, wfs_euid, action_ds):
        wfs = self.get_by_euid(wfs_euid)
        # hardcoding this, but can pass in with the same mechanism as below

        child_wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            child_wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.session.commit()
        self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)
        self.session.commit()

        child_data = ""
        for dlayout_str in action_ds["child_container_obj"]:
            child_data = self.create_instance_by_code(
                dlayout_str, action_ds["child_container_obj"][dlayout_str]
            )
            self.session.commit()

        # Think this through more... I should move to more explicit inheritance from checks?
        self.create_generic_instance_lineage_by_euids(child_wfs.euid, child_data.euid)
        for ch in wfs.parent_of_lineages:
            if ch.child_instance.btype == "plate":
                self.create_generic_instance_lineage_by_euids(
                    ch.child_instance.euid, child_data.euid
                )
                self._add_random_values_to_plate(ch.child_instance)

        self.session.commit()

        return child_wfs

    def do_action_link_tubes_auto(self, wfs_euid, action_ds):
        containers = action_ds["captured_data"]["discard_barcodes"].rstrip().split("\n")

        wfs = self.get_by_euid(wfs_euid)
        # hardcoding this, but can pa   ss in with the same mechanism as below
        cx_ds = {}
        for cx in containers:
            if len(cx) == 0:
                self.logger.exception(f"ERROR: {cx}")
                continue
            cxo = self.get_by_euid(cx)
            child_specimens = []
            for mx in cxo.parent_of_lineages:
                if mx.child_instance.btype == "specimen":
                    cx_ds[cx] = mx.child_instance

        super_type = "content"
        btype = "sample"
        b_sub_type = "blood-plasma"
        version = "1.0"
        results = self.query_template_by_component_v2(
            super_type, btype, b_sub_type, version
        )

        gdna_template = results[0]

        cx_super_type = "container"
        cx_btype = "tube"
        cx_b_sub_type = "tube-generic-10ml"
        cx_version = "1.0"
        cx_results = self.query_template_by_component_v2(
            cx_super_type, cx_btype, cx_b_sub_type, cx_version
        )

        cx_tube_template = cx_results[0]

        parent_wf = wfs.child_of_lineages[0].parent_instance

        active_workset_q_wfs = ""
        (super_type, btype, b_sub_type, version) = (
            list(action_ds["attach_under_root_workflow_queue"].keys())[0]
            .lstrip("/")
            .rstrip("/")
            .split("/")
        )
        for pwf_child_lin in parent_wf.parent_of_lineages:
            if (
                pwf_child_lin.child_instance.btype == btype
                and pwf_child_lin.child_instance.b_sub_type == b_sub_type
            ):
                active_workset_q_wfs = pwf_child_lin.child_instance
                break
        if active_workset_q_wfs == "":
            self.logger.exception(
                f"ERROR: {action_ds['attach_under_root_workflow_queue'].keys()}"
            )
            raise Exception(
                f"ERROR: {action_ds['attach_under_root_workflow_queue'].keys()}"
            )

        new_wf = ""
        for wlayout_str in action_ds["workflow_step_to_attach_as_child"]:
            new_wf = self.create_instance_by_code(
                wlayout_str, action_ds["workflow_step_to_attach_as_child"][wlayout_str]
            )
            self.session.commit()
        self.create_generic_instance_lineage_by_euids(
            active_workset_q_wfs.euid, new_wf.euid
        )

        child_wfs = ""
        for layout_strc in action_ds["child_workflow_step_obj"]:
            child_wfs = self.create_instance_by_code(
                layout_strc, action_ds["child_workflow_step_obj"][layout_strc]
            )
            self.session.commit()

        # self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)
        self.create_generic_instance_lineage_by_euids(new_wf.euid, child_wfs.euid)

        for cxeuid in cx_ds:
            parent_specimen = cx_ds[cxeuid]
            parent_cx = self.get_by_euid(cxeuid)
            child_gdna_obji = self.create_instances(gdna_template.euid)
            child_gdna_obj = child_gdna_obji[0][0]
            child_tube_obji = self.create_instances(cx_tube_template.euid)
            child_tube_obj = child_tube_obji[0][0]
            for aa in parent_cx.child_of_lineages:
                pass

            # soft delete the edge w the queue
            for aa in parent_cx.child_of_lineages:
                if aa.parent_instance.euid == wfs.euid:
                    self.create_generic_instance_lineage_by_euids(
                        new_wf.euid, aa.child_instance.euid
                    )
                    self.delete_obj(aa)

            self.create_generic_instance_lineage_by_euids(
                parent_specimen.euid, child_gdna_obj.euid
            )
            self.create_generic_instance_lineage_by_euids(cxeuid, child_tube_obj.euid)
            self.create_generic_instance_lineage_by_euids(
                child_tube_obj.euid, child_gdna_obj.euid
            )
            self.create_generic_instance_lineage_by_euids(
                child_wfs.euid, child_tube_obj.euid
            )
        self.session.commit()
        return child_wfs

    def do_action_fill_plate_undirected(self, wfs_euid, action_ds):
        containers = action_ds["captured_data"]["discard_barcodes"].rstrip().split("\n")
        wfs = self.get_by_euid(wfs_euid)
        # hardcoding this, but can pass in with the same mechanism as below

        self.logger.info(
            "THIS IS TERRIBLE.  MAKE FLEXIBLE FOR ANY CONTENT TYPE AS LINEAGE"
        )
        cx_ds = {}
        for cx in containers:
            if len(cx) == 0:
                continue
            cxo = self.get_by_euid(cx)
            for mx in cxo.parent_of_lineages:
                if mx.child_instance.btype == "sample":
                    cx_ds[cx] = mx.child_instance

        super_type = "container"
        btype = "plate"
        b_sub_type = "fixed-plate-24"
        version = "1.0"
        results = self.query_template_by_component_v2(
            super_type, btype, b_sub_type, version
        )

        plt_template = results[0]
        plate_wells = self.create_instances(plt_template.euid)
        wells = plate_wells[1]
        plate = plate_wells[0][0]

        c_ctr = 0
        for c in containers:
            if len(c) == 0:
                continue
            super_type = "content"
            btype = "sample"
            b_sub_type = "gdna"
            version = "1.0"

            results = self.query_template_by_component_v2(
                super_type, btype, b_sub_type, version
            )

            sample_template = results[0]
            gdna = self.create_instances(sample_template.euid)

            self.create_generic_instance_lineage_by_euids(c, wells[c_ctr].euid)
            self.create_generic_instance_lineage_by_euids(
                cx_ds[c].euid, gdna[0][0].euid
            )
            self.create_generic_instance_lineage_by_euids(
                wells[c_ctr].euid, gdna[0][0].euid
            )
            c_ctr += 1

        child_wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            child_wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.session.commit()

        self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)
        self.create_generic_instance_lineage_by_euids(child_wfs.euid, plate.euid)
        self.session.commit()
        return child_wfs

    def do_action_fill_plate_directed(self, wfs_euid, action, action_ds):
        pass

    def do_action_add_container_to_assay_q(self, obj_euid, action_ds):
        # This action should be coming to us from a TRI ... kind of breaking my model... how to deal with this?

        super_type = action_ds["captured_data"]["assay_selection"].split("/")[0]
        btype = action_ds["captured_data"]["assay_selection"].split("/")[1]
        b_sub_type = action_ds["captured_data"]["assay_selection"].split("/")[2]
        version = action_ds["captured_data"]["assay_selection"].split("/")[3]

        cont_euid = action_ds["captured_data"]["Container EUID"]

        try:
            cx = self.get_by_euid(cont_euid)
            if not self.check_lineages_for_btype(
                cx.child_of_lineages, "clinical", parent_or_child="parent"
            ):
                raise Exception(
                    f"Container {cont_euid} does not have a test request as a parent"
                )

        except Exception as e:
            self.logger.exception(f"ERROR: {e}")
            self.session.rollback()
            raise e

        results = self.query_instance_by_component_v2(
            super_type, btype, b_sub_type, version
        )

        if len(results) != 1:
            self.logger.exception(
                f"Could not find SINGLE assay instance for {super_type}/{btype}/{b_sub_type}/{version}"
            )
            self.logger.exception(
                f"Could not find SINGLE assay instance for {super_type}/{btype}/{b_sub_type}/{version}"
            )
            self.logger.exception(
                f"Could not find SINGLE assay instance for {super_type}/{btype}/{b_sub_type}/{version}"
            )

        # Weak. using step number as a proxy for the ready step.
        wf = results[0]
        wfs = ""

        try:
            for wwfi in wf.parent_of_lineages:
                if wwfi.child_instance.json_addl["properties"]["step_number"] in [
                    1,
                    "1",
                ]:
                    wfs = wwfi.child_instance
            if wfs == "":
                raise Exception(f"Could not find workflow step for {wf.euid}")
        except Exception as e:
            self.logger.exception(f"ERROR: {e}")
            self.session.rollback()
            raise e

        # Prevent adding duplicate to queue
        for cur_ci in wfs.parent_of_lineages:
            if cont_euid == cur_ci.child_instance.euid:
                self.logger.exception(
                    f"Container {cont_euid} already in assay queue {wf.euid}"
                )
                raise Exception(
                    f"Container {cont_euid} already in assay queue {wf.euid}"
                )

        # if here, add to the queue!
        self.create_generic_instance_lineage_by_euids(wfs.euid, cont_euid)
        self.session.commit()
        return wfs

    def do_action_create_child_container_and_link_child_workflow_step(
        self, wfs_euid, action_ds={}
    ):
        wfs = self.get_by_euid(wfs_euid)
        ## TODO: pull out common lineage and child creation more cleanly

        child_wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            child_wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.session.commit()

        # AND THIS LOGIC NEEDS TIGHTENING UP too
        parent_cont = ""
        parent_conts_n = 0
        for i in wfs.parent_of_lineages:
            if i.child_instance.super_type == "container":
                parent_cont = i.child_instance
                parent_conts_n += 1
        if parent_conts_n != 1:
            self.logger.exception(
                f"Parent container count is {parent_conts_n} for {wfs.euid}, and should be ==1... this logic needs tightening up"
            )
            raise Exception(
                f"Parent container count is {parent_conts_n} for {wfs.euid}, and should be ==1... this logic needs tightening up"
            )

        child_cont = ""
        for layout_str in action_ds["child_container_obj"]:
            child_cont = self.create_instance_by_code(
                layout_str, action_ds["child_container_obj"][layout_str]
            )
            self.session.commit()

            for content_layouts in (
                []
                if "instantiation_layouts"
                not in action_ds["child_container_obj"][layout_str]
                else action_ds["child_container_obj"][layout_str][
                    "instantiation_layouts"
                ]
            ):
                for cli in content_layouts:
                    new_ctnt = ""
                    for cli_k in cli:
                        new_ctnt = self.create_instance_by_code(cli_k, cli[cli_k])
                        ##self.session.flush()
                        self.session.commit()
                        self.create_generic_instance_lineage_by_euids(
                            child_cont.euid, new_ctnt.euid
                        )

        try:
            self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)
            self.create_generic_instance_lineage_by_euids(
                parent_cont.euid, child_cont.euid
            )

        except Exception as e:
            self.logger.exception(f"ERROR: {e}")
            self.session.rollback()
            raise e

        self.create_generic_instance_lineage_by_euids(child_wfs.euid, child_cont.euid)
        self.session.commit()
        return child_wfs

    def do_action_create_test_req_and_link_child_workflow_step(
        self, wfs_euid, action_ds
    ):
        wfs = self.get_by_euid(wfs_euid)
        child_wfs = ""

        for layout_str in action_ds["child_workflow_step_obj"]:
            child_wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.session.commit()

        self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)

        new_test_req = ""
        for layout_str in action_ds["test_requisition_obj"]:
            new_test_req = self.create_instance_by_code(
                layout_str, action_ds["test_requisition_obj"][layout_str]
            )
            self.session.commit()

        prior_cont_euid = ""
        prior_cont_euid_n = 0
        for i in wfs.parent_of_lineages:
            if i.child_instance.btype == "tube":
                prior_cont_euid = i.child_instance.euid
                prior_cont_euid_n += 1
        if prior_cont_euid_n != 1:
            self.logger.exception(
                f"Prior container count is {prior_cont_euid_n} for {wf.euid}, and should be ==1... this logic needs tightening up w/r/t finding the desired plate"
            )
            raise Exception(
                f"Prior container count is {prior_cont_euid_n} for {wf.euid}, and should be ==1... this logic needs tightening up"
            )

        self.create_generic_instance_lineage_by_euids(
            new_test_req.euid, prior_cont_euid
        )
        self.create_generic_instance_lineage_by_euids(child_wfs.euid, new_test_req.euid)
        self.session.commit()
        return (child_wfs, new_test_req, prior_cont_euid)


class BloomReagent(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_rgnt_24w_plate_TEST(self, rg_code="idt-probes-rare-mendelian"):
        # I am taking a short cut and not taking time to think about making this generic.

        containers = self.create_instances(
            self.query_template_by_component_v2(
                "container", "plate", "fixed-plate-24", "1.0"
            )[0].euid
        )

        plate = containers[0][0]
        wells = containers[1]
        probe_ctr = 1

        for i in wells:
            probe_name = f"id_probe_{probe_ctr}"
            seq_1 = "".join(random.choices("ATCG", k=18))
            seq_2 = "".join(random.choices("ATCG", k=18))

            new_reagent = self.create_instance(
                self.query_template_by_component_v2(
                    "content", "reagent", rg_code, "1.0"
                )[0].euid,
                {
                    "properties": {
                        "probe_name": probe_name,
                        "probe_seq_1": seq_1,
                        "probe_seq_2": seq_2,
                    }
                },
            )
            self.create_generic_instance_lineage_by_euids(i.euid, new_reagent.euid)
            probe_ctr += 1
        self.session.commit()
        return plate.euid


class BloomEquipment(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_empty_equipment(self, template_euid):
        return self.create_instances(template_euid)


class BloomObjectSet(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

# TODO -- is this used at all, and if so, is it used correctly?
class AuditLog(BloomObj):
    def __init__(self, session, base):
        super().__init__(session, base)


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


class BloomFile(BloomObj):
    
    def __init__(self, bdb, bucket_prefix=None, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)
    
        if bucket_prefix is None:
            bucket_prefix = os.environ.get(
                "BLOOM_DEWEY_S3_BUCKET_PREFIX", "set-a-bucket-prefix-in-the-dotenv-file"
            )

        self.bucket_prefix = bucket_prefix
        self.s3_client = boto3.client("s3")

    def _derive_bucket_name(self, euid):
        euid_int = int(re.sub("[^0-9]", "", euid))
        response = self.s3_client.list_buckets()
        buckets = response["Buckets"]
        matching_buckets = [
            bucket["Name"]
            for bucket in buckets
            if bucket["Name"].startswith(self.bucket_prefix)
        ]
        bucket_suffixes = sorted(
            [
                int(re.sub("[^0-9]", "", name.replace(self.bucket_prefix, "")))
                for name in matching_buckets
            ]
        )

        for i in range(len(bucket_suffixes) - 1):
            if bucket_suffixes[i] <= euid_int < bucket_suffixes[i + 1]:
                return f"{self.bucket_prefix}{bucket_suffixes[i]}"

        if euid_int >= bucket_suffixes[-1]:
            return f"{self.bucket_prefix}{bucket_suffixes[-1]}"

        raise Exception("No matching bucket found for the provided EUID.")

    def _determine_s3_key(self, euid, data_file_name):
        bucket_name = self._derive_bucket_name(euid)
        euid_numeric_part = int(re.sub("[^0-9]", "", euid))
        response = self.s3_client.list_objects_v2(
            Bucket=bucket_name, Prefix="", Delimiter="/"
        )

        logging.debug(f"ListObjectsV2 Response: {response}")
        folders = sorted(
            [
                int(content["Prefix"].rstrip("/"))
                for content in response.get("CommonPrefixes", [])
            ]
        )

        if not folders:
            # If no folders are found, create a '0' folder
            self.s3_client.put_object(Bucket=bucket_name, Key="0/")
            folders = [0]

        for i in range(len(folders) - 1):
            if folders[i] <= euid_numeric_part < folders[i + 1]:
                folder_prefix = folders[i]
                break
        else:
            folder_prefix = folders[-1] if euid_numeric_part >= folders[-1] else 0

        logging.debug(f"Determined folder_prefix: {folder_prefix}")
        return f"{folder_prefix}/{euid}.{data_file_name.split('.')[-1]}"

    def DELME_check_s3_key_exists(self, bucket_name, s3_key):
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except self.s3_client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            else:
                raise e

    def link_file_to_parent(self, child_euid, parent_euid):
        self.create_generic_instance_lineage_by_euids(child_euid, parent_euid)
        self.session.commit()
        
    def create_file(
        self,
        file_metadata={},
        file_data=None,
        file_name=None,
        url=None,
        full_path_to_file=None,
        s3_uri=None,
        create_locked=False,
        addl_tags={},
    ):
        """
        Create a file or import files from an S3 directory.

        :param file_metadata: Metadata to associate with the file(s).
        :param file_data: File data to upload (binary data).
        :param file_name: Name of the file.
        :param url: URL to fetch the file data.
        :param full_path_to_file: Local path to the file.
        :param s3_uri: S3 URI of the file or directory.
        :param create_locked: Whether to lock the file(s) after creation. Defaults to True.
        :param addl_tags: Additional tags for the file(s).
        :return: Created file object or list of file objects.
        """
        if s3_uri:
            # Detect if S3 URI is a directory
            s3_parsed_uri = re.match(r"s3://([^/]+)/(.+)", s3_uri)
            if not s3_parsed_uri:
                raise ValueError("Invalid s3_uri format. Expected format: s3://bucket_name/prefix")
            
            bucket_name, prefix = s3_parsed_uri.groups()

            try:
                response = self.s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix, Delimiter='/')
                files = response.get('Contents', [])
                
                # If more than one object or the URI ends with '/', treat it as a directory
                if len(files) > 1 or s3_uri.endswith('/'):
                    created_files = []
                    for file in files:
                        file_key = file['Key']
                        
                        # Skip directories
                        if file_key.endswith('/'):
                            continue
                        
                        file_name = file_key.split('/')[-1]
                        current_s3_uri = f"s3://{bucket_name}/{file_key}"
                        
                        # Create individual files for each item in the directory
                        created_file = self.create_file(
                            file_metadata=file_metadata,
                            s3_uri=current_s3_uri,
                            create_locked=create_locked,
                            addl_tags=addl_tags,
                        )
                        created_files.append(created_file)
                    
                    return created_files
                
                # Otherwise, process as a single file
                s3_uri = f"s3://{bucket_name}/{files[0]['Key']}" if files else s3_uri
            
            except Exception as e:
                raise Exception(f"Error detecting file or directory for S3 URI {s3_uri}: {e}")

        # Existing logic for processing a single file
        file_properties = {"properties": file_metadata}
        import_or_remote = file_metadata.get('import_or_remote', 'import')

        new_file = self.create_instance(
            self.query_template_by_component_v2("file", "file", "generic", "1.0")[0].euid,
            file_properties,
        )
        self.session.commit()

        new_file.json_addl["properties"]["current_s3_bucket_name"] = (
            self._derive_bucket_name(new_file.euid)
        )
        flag_modified(new_file, "json_addl")
        self.session.commit()

        if file_data or url or full_path_to_file or s3_uri:
            try:
                new_file = self.add_file_data(
                    new_file.euid,
                    file_data,
                    file_name,
                    url,
                    full_path_to_file,
                    s3_uri,
                    addl_tags=addl_tags,
                    import_or_remote=import_or_remote,
                )
            except Exception as e:
                logging.exception(f"Error adding file data: {e}")
                new_file.bstatus = "error adding file data"
                flag_modified(new_file, "json_addl")
                self.session.commit()
                raise Exception(e)
        else:
            logging.warning(f"No data provided for file creation or import skipped: {file_data, url}")
            new_file.bstatus = f"no file data provided or {import_or_remote} is not 'import'"
            self.session.commit()

        if create_locked:
            self.lock_file(new_file.euid)

        return new_file


    def create_file_old(
        self,
        file_metadata={},
        file_data=None,
        file_name=None,
        url=None,
        full_path_to_file=None,
        s3_uri=None,
        create_locked=True,
        addl_tags={},
    ):
        file_properties = {"properties": file_metadata}

        import_or_remote = file_metadata['import_or_remote']

        new_file = self.create_instance(
            self.query_template_by_component_v2("file", "file", "generic", "1.0")[
                0
            ].euid,
            file_properties,
        )
        self.session.commit()

        # Special handling for patient_id
        if (
            "patient_id" in file_metadata
        ):
            patient_id = file_metadata["patient_id"]
            search_criteria = {"properties": {"patient_id": patient_id}}
            existing_euids = self.search_objs_by_addl_metadata(
                search_criteria,
                True,
                super_type="actor",
                btype="generic",
                b_sub_type="patient"
            )

            if existing_euids:
                # Create child relationships to existing objects
                for euid in existing_euids:
                    self.create_generic_instance_lineage_by_euids(euid, new_file.euid)
            else:
                # Create a new actor/generic/patient object
                new_patient = self.create_instance(
                    self.query_template_by_component_v2(
                        "actor", "generic", "patient", "1.0"
                    )[0].euid,
                    {"properties": {"patient_id": patient_id}},
                )
                self.session.commit()
                self.create_generic_instance_lineage_by_euids(
                    new_patient.euid, new_file.euid
                )

        new_file.json_addl["properties"]["current_s3_bucket_name"] = (
            self._derive_bucket_name(new_file.euid)
        )
        flag_modified(new_file, "json_addl")
        self.session.commit()

        if file_data or url or full_path_to_file or s3_uri:
            try:
                new_file = self.add_file_data(
                    new_file.euid, file_data, file_name, url, full_path_to_file, s3_uri, addl_tags=addl_tags, import_or_remote=import_or_remote
                )
            except Exception as e:
                logging.exception(f"Error adding file data: {e}")
                new_file.bstatus = "error adding file data"
                flag_modified(new_file, "json_addl")
                self.session.commit()
                raise Exception(e)
        else:
            logging.warning(f"No data provided for file creation, or import skipped ({import_or_remote}): {file_data, url}")
            new_file.bstatus = f"no file data provided or {import_or_remote} is not 'import'"
            self.session.commit() 

        if create_locked:
            self.lock_file(new_file.euid)

        return new_file


    def sanitize_tag(self, value, is_key=False):
        """
        Sanitize the tag key or value to conform to AWS tag requirements by replacing disallowed characters.

        Parameters:
        - value (str): The tag key or value to sanitize.
        - is_key (bool): If True, sanitize as a tag key (128-character limit). 
                        If False, sanitize as a tag value (256-character limit).

        Returns:
        - str: Sanitized tag key or value.
        """
        # AWS tag key or value allowed characters
        allowed_characters_regex = r'[^a-zA-Z0-9 _\.:/=+\-@]'
        
        # Replace disallowed characters with '_'
        sanitized_value = re.sub(allowed_characters_regex, '_', value)
        
        # Trim leading and trailing spaces (not allowed by AWS)
        sanitized_value = sanitized_value.strip()
        
        # Enforce maximum length
        max_length = 128 if is_key else 256
        sanitized_value = sanitized_value[:max_length]
        
        return sanitized_value

    def format_addl_tags(self, add_tags):
        if not isinstance(add_tags, dict):
            raise ValueError("Input must be a dictionary.")

        formatted_tags = []
        for key, value in add_tags.items():
            if not isinstance(value, str):
                raise ValueError(f"Value for key '{key}' must be a string.")
            formatted_tags.append(
                f"{self.sanitize_tag(key)}={self.sanitize_tag(value)}"
            )

        return "&".join(formatted_tags)
    
    def add_file_data(
        self,
        euid,
        file_data=None,
        file_name=None,
        url=None,
        full_path_to_file=None,
        s3_uri=None,
        addl_tags={},
        import_or_remote=None
    ):
        file_instance = self.get_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        file_properties = {}

        if import_or_remote in ["Remote", "remote"] and (file_data is not None or url is not None or full_path_to_file is not None):
            raise ValueError("Remote file management is only supported with internal S3 URI.")

        addl_tag_string = self.format_addl_tags(addl_tags)
        if len(addl_tag_string) > 0:
            addl_tag_string = f"&{addl_tag_string}"
        
        if file_name is None:
            if url:
                file_name = url.split("/")[-1]
            elif s3_uri:
                file_name = s3_uri.split("/")[-1]
            elif full_path_to_file:
                file_name = Path(full_path_to_file).name
            else:
                raise ValueError(
                    "file_name must be provided if file_data or url is passed without a filename."
                )

        file_suffix = file_name.split(".")[-1]
        s3_key = self._determine_s3_key(euid, file_name)

        # Check if a file with the same EUID already exists in the bucket
        s3_key_path = "/".join(s3_key.split("/")[:-1])
        s3_key_path = s3_key_path + "/" if len(s3_key_path) > 0 else ""


        existing_files = self.s3_client.list_objects_v2(
            Bucket=s3_bucket_name, Prefix=f"{s3_key_path}{euid}."
        )
        if "Contents" in existing_files:
            self.logger.exception(
                f"A file with PREFIX EUID {euid} already exists in bucket {s3_bucket_name} {s3_key_path}."
            )
            raise Exception(
                f"A file with EUID {euid} already exists in bucket {s3_bucket_name} {s3_key_path}."
            )

        if s3_uri:
            # Was just doing this for only remote s3 uris, but am going to leave them be for now
            # Check if a remote file with the same metadata already exists

            search_criteria = {"properties": {"current_s3_uri": s3_uri}}
            existing_euids = self.search_objs_by_addl_metadata(search_criteria,True,super_type="file", btype="file",b_sub_type="generic")
            
            if len(existing_euids) > 0:
                raise Exception(f"Remote file with URI {s3_uri} already exists in the database as {existing_euids}.")

            s3uri_bucket=s3_uri.split("/")[2]
            s3uri_key="/".join(s3_uri.split("/")[3:])
            # Store metadata for the remote file
            file_properties = {
                "remote_s3_uri": s3_uri,
                "original_file_name": file_name,
                "name": file_name,
                "original_file_size_bytes": None,  # Size is unknown for remote files
                "original_file_suffix": file_suffix,
                "original_file_data_type": "s3uri",
                "file_type": file_suffix,
                "current_s3_uri": s3_uri,
                "original_s3_uri": s3_uri,  
                "current_s3_key": s3uri_key,
                "current_s3_bucket_name": s3uri_bucket,
                "import_or_remote": 'remote',
            }
                        # Check if the object has the 'dewey_euid' tag
            try:
                existing_tags = self.s3_client.get_object_tagging(
                    Bucket=s3uri_bucket,
                    Key=s3uri_key
                )

                # Check if 'dewey_euid' is already present in the tags
                for tag in existing_tags.get("TagSet", []):
                    if tag["Key"] == "dewey_euid":
                        raise Exception(f"Object {s3_uri} already has a 'dewey_euid' tag with value {tag['Value']}.")
            except self.s3_client.exceptions.NoSuchKey:
                raise Exception(f"S3 object {s3_uri} does not exist.")
            except Exception as e:
                self.logger.exception(f"Error checking tags for S3 object {s3_uri}: {e}")
                raise Exception(f"Failed to check tags for S3 object: {e}")
            
                    
            # Construct the tags
            tagging = {
                'TagSet': [
                    {'Key': 'dewey_original_file_name', 'Value': self.sanitize_tag(file_name)},
                    {'Key': 'dewey_original_file_path', 'Value': 'N/A'},
                    {'Key': 'dewey_original_file_suffix', 'Value': self.sanitize_tag(file_suffix)},
                    {'Key': 'dewey_euid', 'Value': self.sanitize_tag(euid)},
                ]
            }
                    
            # Apply the tags to the existing object
            try:
                self.s3_client.put_object_tagging(
                    Bucket=s3uri_bucket,
                    Key=s3uri_key,
                    Tagging=tagging
                )
                self.logger.info(f"Tags successfully applied to S3 object {s3_uri}")
            except Exception as e:
                self.logger.exception(f"Error tagging existing S3 object {s3_uri}: {e}\n\n{tagging}")
                raise Exception(f"Failed to tag S3 object: {e}\n{tagging}")

            _update_recursive(file_instance.json_addl["properties"], file_properties)
            flag_modified(file_instance, "json_addl")
            self.session.commit()
            return file_instance

        try:
            if file_data:
                file_data.seek(0)  # Ensure the file pointer is at the beginning
                file_size = len(file_data.read())
                file_data.seek(0)  # Reset the file pointer after reading
                
                try:
                    self.s3_client.put_object(
                        Bucket=s3_bucket_name,
                        Key=s3_key,
                        Body=file_data,
                        Tagging=f"dewey_original_file_name={self.sanitize_tag(file_name)}&dewey_original_file_path=N/A&&dewey_original_file_suffix={self.sanitize_tag(file_suffix)}&dewey_euid={self.sanitize_tag(euid)}{addl_tag_string}"
                    )

                except Exception as e:
                    self.logger.exception(f"Error uploading file data: {e}. Possibly tag related: {self.sanitize_tag(file_name)}, {self.sanitize_tag(str(file_size))}, {self.sanitize_tag(file_suffix)}, {self.sanitize_tag(euid)} ") 
                    raise Exception(e)
                odirectory, ofilename = os.path.split(file_name)

                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": ofilename,
                    "name": file_name,
                    "original_file_path": odirectory,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "raw data",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

            elif url:
                response = requests.get(url)
                file_size = len(response.content)
                url_info = url.split("/")[-1]
                file_suffix = url_info.split(".")[-1]
                self.s3_client.put_object(
                    Bucket=s3_bucket_name,
                    Key=s3_key,
                    Body=response.content,
                    Tagging=f"dewey_original_file_name={self.sanitize_tag(url_info)}&dewey_original_url={self.sanitize_tag(url)}&dewey_original_file_suffix={self.sanitize_tag(file_suffix)}&dewey_euid={self.sanitize_tag(euid)}{addl_tag_string}",
                )
                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": url_info,
                    "name": url_info,
                    "original_url": url,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "url",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

            elif full_path_to_file:
                with open(full_path_to_file, "rb") as file:
                    file_data = file.read()
                file_size = os.path.getsize(full_path_to_file)
                local_path_info = Path(full_path_to_file)
                local_ip = None
                try:
                    local_ip = socket.gethostbyname(socket.gethostname())
                except socket.gaierror:
                    local_ip = "127.0.0.1"  # Fallback to localhost

                self.s3_client.put_object(
                    Bucket=s3_bucket_name,
                    Key=s3_key,
                    Body=file_data,
                    Tagging=f"dewey_original_file_name={self.sanitize_tag(local_path_info.name)}&dewey_original_file_path={self.sanitize_tag(full_path_to_file)}&dewey_original_file_suffix={self.sanitize_tag(file_suffix)}&dewey_euid={self.sanitize_tag(euid)}{addl_tag_string}",
                )
                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": local_path_info.name,
                    "name": local_path_info.name,
                    "original_file_path": full_path_to_file,
                    "original_local_server_name": socket.gethostname(),
                    "original_server_ip": local_ip,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "local file",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

            elif s3_uri in ["deprecate this"]:
                # I do not want to be in the business of moving files around here
                #elif s3_uri:
                # Validate and move the file from the provided s3_uri
                s3_parsed_uri = re.match(r"s3://([^/]+)/(.+)", s3_uri)
                if not s3_parsed_uri:
                    raise ValueError(
                        "Invalid s3_uri format. Expected format: s3://bucket_name/key"
                    )

                source_bucket, source_key = s3_parsed_uri.groups()
                try:
                    self.s3_client.head_object(Bucket=source_bucket, Key=source_key)
                except self.s3_client.exceptions.NoSuchKey:
                    raise ValueError(
                        f"The s3_uri {s3_uri} does not exist or is not accessible with the provided credentials."
                    )

                copy_source = {"Bucket": source_bucket, "Key": source_key}
                self.s3_client.copy(copy_source, s3_bucket_name, s3_key)
                file_size = self.s3_client.head_object(
                    Bucket=s3_bucket_name, Key=s3_key
                )["ContentLength"]

                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": file_name,
                    "name": file_name,
                    "original_s3_uri": s3_uri,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "s3_uri",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

                # Delete the old file and create a marker file
                marker_key = f"{source_key}.dewey.{euid}.moved"
                if len(marker_key)  >= 1024:
                    raise Exception(f"Marker key length is too long, >1024chrar : {len(marker_key)},not deleting original file: {source_key}")
                self.s3_client.put_object(
                    Bucket=source_bucket,
                    Key=marker_key,
                    Body=b"",
                    Tagging=f"dewey_import_or_remote={import_or_remote}&dewey_euid={euid}&dewey_original_s3_uri={self.sanitize_tag(s3_uri)}{addl_tag_string}",
                )
                #self.s3_client.delete_object(Bucket=source_bucket, Key=source_key)


            else:
                self.logger.exception("No file data provided.")
                raise ValueError("No file data provided.")

        except Exception as e:
            logging.exception(f"An error occurred while uploading the file: {e}")
            file_instance.bstatus = "error"
            file_instance.json_addl["properties"]["comments"] = (
                str(e) + f" FILENAM == {file_name}"
            )
            flag_modified(file_instance, "json_addl")
            flag_modified(file_instance, "bstatus")
            self.session.flush()
            self.session.commit()
            raise (e)

        _update_recursive(file_instance.json_addl["properties"], file_properties)
        flag_modified(file_instance, "json_addl")
        self.session.commit()

        return file_instance

    def update_file_metadata(self, euid, file_metadata={}):
        file_instance = self.get_by_euid(euid)
        _update_recursive(file_instance.json_addl["properties"], file_metadata)
        flag_modified(file_instance, "json_addl")
        self.session.commit()
        return file_instance

    def get_file_by_euid(self, euid):
        return self.get_by_euid(euid)

    def download_file(
        self,
        euid,
        save_pattern="dewey",
        include_metadata=False,
        save_path="./tmp/",
        delete_if_exists=False,
    ):
        """
        Downloads the S3 file locally with different naming patterns and optionally includes metadata in a YAML file.

        :param euid: EUID of the file to download.
        :param save_pattern: Naming pattern for the saved file. Options: 'dewey', 'orig', 'hybrid'.
        :param include_metadata: Whether to save metadata in a YAML file. Defaults to False.
        :param save_path: Directory where the file will be saved. Defaults to ./tmp/, which will be created if not present.
        :return: Path of the saved file.
        """
        import random
        random.randint(1,99999999)
        save_path = os.path.join(save_path, str(random.randint(1,99999999)))
        os.system(f"mkdir -p {save_path}")
        
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        else:
            self.logger.warn(f"Directory already exists: {save_path}")

        file_instance = self.get_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]
        original_file_name = file_instance.json_addl["properties"]["original_file_name"]
        file_suffix = file_instance.json_addl["properties"]["original_file_suffix"]

        if save_pattern == "dewey":
            local_file_name = f"{euid}.{file_suffix}"
        elif save_pattern == "orig":
            local_file_name = original_file_name
            print("WARNING: Using 'orig' pattern may overwrite existing files!")
        elif save_pattern == "hybrid":
            local_file_name = f"{euid}.{original_file_name}"
        else:
            raise ValueError(
                "Invalid save_pattern. Options are: 'dewey', 'orig', 'hybrid'."
            )

        local_file_path = os.path.join(save_path, local_file_name)

        if os.path.exists(local_file_path):
            self.logger.exception(f"File already exists: {local_file_path}")
            if delete_if_exists:
                os.remove(local_file_path)  # Delete the existing file
            else:
                raise Exception(f"File already exists: {local_file_path}")

        # Save metadata as a YAML file if requested
        if include_metadata:
            metadata_file_path = f"{local_file_path}.{euid}.dewey.yaml"
            if os.path.exists(metadata_file_path):
                self.logger.exception(
                    f"Metadata file already exists: {metadata_file_path}"
                )

                if delete_if_exists:
                    os.remove(metadata_file_path)
                else:
                    raise Exception(
                        f"Metadata file already exists: {metadata_file_path}"
                    )

            with open(metadata_file_path, "w") as metadata_file:
                yaml.dump(file_instance.json_addl["properties"], metadata_file)
            print(f"Metadata saved successfully: {metadata_file_path}")

        # Download the file from S3
        try:
            with open(local_file_path, "wb") as file:
                self.s3_client.download_fileobj(s3_bucket_name, s3_key, file)
            print(f"File downloaded successfully: {local_file_path}")
        except Exception as e:
            raise Exception(f"An error occurred while downloading the file: {e}")

        os.system(f"(sleep 2000 && rm -rf {save_path}) &")
        return local_file_path

    def get_s3_uris(self, euids, include_metadata=False):
        """
        Returns a dictionary of EUIDs to arrays containing their corresponding S3 URIs and optionally their metadata.

        :param euids: List of EUIDs to retrieve S3 URIs for.
        :param include_metadata: Boolean indicating whether to include metadata in the result.
        :return: Dictionary with EUID as key and array [S3 URI, metadata] as value.
        """
        euid_to_s3_data = {}

        for euid in euids:
            try:
                file_instance = self.get_by_euid(euid)
                s3_bucket_name = file_instance.json_addl["properties"][
                    "current_s3_bucket_name"
                ]
                s3_key = file_instance.json_addl["properties"]["current_s3_key"]
                s3_uri = f"s3://{s3_bucket_name}/{s3_key}"
                metadata = (
                    file_instance.json_addl["properties"] if include_metadata else None
                )
                euid_to_s3_data[euid] = [s3_uri, metadata]
            except Exception as e:
                self.logger.error(f"Error retrieving S3 URI for EUID {euid}: {e}")
                euid_to_s3_data[euid] = [None, None]  # or handle error as needed

        return euid_to_s3_data

    def delete_file(self, euid):
        # SOFT delete (S3 record is not deleted)

        file_instance = self.get_by_euid(euid)
        # s3_bucket_name = file_instance.json_addl['properties']['current_s3_bucket_name']
        # s3_key = file_instance.json_addl['properties']['current_s3_key']

        try:
            # self.s3_client.delete_object(Bucket=s3_bucket_name, Key=s3_key)
            self.delete_obj(file_instance)
            self.session.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting file {euid}: {e}")
            self.session.rollback()
            return False

    def get_s3_object_stream(self, euid):
        file_instance = self.get_file_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]

        try:
            response = self.s3_client.get_object(Bucket=s3_bucket_name, Key=s3_key)
            content_type = response["ContentType"]
            return response["Body"], content_type
        except self.s3_client.exceptions.NoSuchKey:
            raise Exception("File not found")
        except NoCredentialsError:
            raise Exception("Credentials not available")
        except Exception as e:
            raise Exception(e)

    def lock_file(self, euid, lock=True):
        """
        Locks or unlocks the specified S3 file.

        :param euid: EUID of the file to lock/unlock.
        :param lock: Boolean indicating whether to lock (True) or unlock (False) the file. Defaults to True.
        """
        file_instance = self.get_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]

        try:
            if lock:                
                self.s3_client.put_object_retention(
                    Bucket=s3_bucket_name,
                    Key=s3_key,
                    Retention={
                        'Mode': 'GOVERNANCE',
                        'RetainUntilDate': (datetime.now() + timedelta(days=36500)).isoformat()
                    }
                )

            return True
        except Exception as e:
            logging.exception(f"An error occurred while {'locking' if lock else 'unlocking'} the file: {e}")
            return False
        
    
    def create_presigned_url(self, 
                             file_euid,  
                             valid_duration=3600, 
                             comments="", status="active", 
                             file_set_euid=None):
        """
        Create a presigned url and create a shared reference to track this.

        :param file_euid: EUID of the file to create a shared reference for.
        :param valid_duration: Duration in seconds for which the reference is valid.
        :param comments: Additional comments for the reference.
        :param status: Status of the reference. Defaults to 'active'.
        :return: Created file reference instance.
        """
        
        # change to allow setting the start_datetime in the future.
        start_datetime = datetime.now(UTC)
        end_datetime = start_datetime + timedelta(seconds=valid_duration)
        
        file_instance = self.get_by_euid(file_euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]

        presigned_url = self.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': s3_bucket_name, 'Key': s3_key},
            ExpiresIn=valid_duration
        )

        file_ref_obj = BloomFileReference(self._bdb)
        file_reference = file_ref_obj.create_file_reference(
            file_euid=file_euid,
            reference_type="presigned",
            valid_duration=valid_duration,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            comments=comments,
            status=status,
            presigned_url=presigned_url,
            file_set_euid=file_set_euid, 
            visibility=None
        )

        return {"file_reference": file_reference, "presigned_url": presigned_url}


    def import_files_from_s3_directory(self, s3_uri, file_metadata={}, create_locked=True):
        """
        Import all files from a specified S3 directory (not recursively).
        
        :param s3_uri: The S3 URI of the directory (e.g., s3://bucket_name/folder/).
        :param file_metadata: Metadata to associate with each imported file.
        :param create_locked: Whether to lock the files upon creation. Defaults to True.
        :return: List of created file objects.
        """
        # Parse S3 URI
        s3_parsed_uri = re.match(r"s3://([^/]+)/(.+)", s3_uri)
        if not s3_parsed_uri:
            raise ValueError("Invalid s3_uri format. Expected format: s3://bucket_name/folder/")
        
        bucket_name, prefix = s3_parsed_uri.groups()
        
        # List objects in the directory
        try:
            response = self.s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix, Delimiter='/')
            files = response.get('Contents', [])
        except Exception as e:
            raise Exception(f"Error listing S3 directory {s3_uri}: {e}")
        
        created_files = []
        for file in files:
            file_key = file['Key']
            
            # Skip directories
            if file_key.endswith('/'):
                continue
            
            file_name = file_key.split('/')[-1]
            current_s3_uri = f"s3://{bucket_name}/{file_key}"
            
            # Add metadata specific to the file
            individual_file_metadata = file_metadata.copy()
            individual_file_metadata['file_name'] = file_name
            
            try:
                # Create and add the file
                created_file = self.create_file(
                    file_metadata=individual_file_metadata,
                    s3_uri=current_s3_uri,
                    create_locked=create_locked
                )
                created_files.append(created_file)
            except Exception as e:
                logging.error(f"Error importing file {current_s3_uri}: {e}")
        
        return created_files




# As in expiring s3 links and so on. Potentially allow sharing of files with hosting protocols like SFTP, etc...
class BloomFileReference(BloomObj):
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)


    def create_file_reference(self, file_euid=None, reference_type='presigned', visibility='public', valid_duration=0, start_datetime=None, end_datetime=None, comments="", status="active", presigned_url="", file_set_euid=None, rclone_config={}):
        """
        Create a shared file reference.

        :param file_euid: EUID of the file.
        :param reference_type: Type of reference. 'presigned' or 'rclone http'.
        :param visibility: 'public' or 'controlled'.
        :param valid_duration: Duration in seconds for which the reference is valid.
        :param start_datetime: (Optional) Start datetime for the reference. Defaults to now.
        :param end_datetime: (Optional) End datetime for the reference. Calculated from valid_duration if not provided.
        :param comments: Additional comments for the reference.
        :param status: Status of the reference. Defaults to 'active'.
        :param rclone_config: Configuration for rclone http serve {'port': 8080, 'host': '0.0.0.0', 'user': 'user', 'passwd': 'passwd', 'bucket':'xxx-dewey-0'}.
        :return: Created file reference instance.
        """
        
        start_datetime = start_datetime or datetime.now(UTC)
        end_datetime = end_datetime or (start_datetime + timedelta(seconds=valid_duration))
        
        file_reference_metadata = {
            "status": status,
            "comments": comments,
            "visibility": visibility,
            "reference_type": reference_type,
            "valid_duration": valid_duration,
            "start_datetime": start_datetime.isoformat(),
            "end_datetime": end_datetime.isoformat(),
            "presigned_url": presigned_url,
            "rclone_config": rclone_config
        }
        
        file_reference = self.create_instance(
            self.query_template_by_component_v2(
                "file", "shared_ref", "generic", "1.0"
            )[0].euid,
            {"properties": file_reference_metadata},
        )
        
        if reference_type.startswith('rclone'):
            # Start the rclone http serve

            filter_fn = f"logs/{file_reference.euid}_filter.txt"
            fh = open(filter_fn, "w")

            fs = self.get_by_euid(file_set_euid)
            for x in fs.parent_of_lineages:
                print(x.child_instance.euid)
                fh.write(f"+ {x.child_instance.json_addl['properties']['current_s3_key']}\n")
            fh.write('- *\n')
            fh.close()


            cmd = f"timeout {valid_duration} {reference_type} blms3:{rclone_config['bucket']} --filter-from logs/{file_reference.euid}_filter.txt --addr {rclone_config['host']}:{rclone_config['port']} --user {rclone_config['user']} --pass {rclone_config['passwd']} 2>&1 > logs/{file_reference.euid}_rclone.log &"
            logging.info(f"Starting rclone http serve with command: {cmd}")
            
            file_reference.json_addl['properties']['rclone_cmd'] = cmd
            flag_modified(file_reference, "json_addl")
            
            try:
                # Start the command in the background
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                # Log that the process has started
                logging.info(f"rclone command started with PID: {process.pid}")

                # Optionally, you can wait a moment and then check if the process is still running
                process.communicate(timeout=5)
                if process.poll() is None:
                    logging.info(f"rclone is running successfully in the background.")
                    file_reference.json_addl['properties']['rclone_pid'] = process.pid
                    file_reference.json_addl['properties']['rclone_status'] = 'running'
                    flag_modified(file_reference, "json_addl")
                else:
                    file_reference.json_addl['properties']['rclone_status'] = 'error'
                    flag_modified(file_reference, "json_addl")
                    logging.error(f"rclone command failed to start properly. Error: {process.stderr.read().decode().strip()}")

            except subprocess.TimeoutExpired:
                logging.info(f"rclone command started and is running in the background.")
                file_reference.json_addl['properties']['rclone_pid'] = process.pid
                file_reference.json_addl['properties']['rclone_status'] = 'running bkgrnd'
                flag_modified(file_reference, "json_addl")
            except Exception as e:
                logging.error(f"An error occurred while starting rclone: {str(e)}")
                file_reference.json_addl['properties']['rclone_status'] = 'error'
                flag_modified(file_reference, "json_addl")

            self.session.commit()
            logging.info(f"{cmd} was executed... see logs")

            

            
        if file_euid not in [None]:
            self.create_generic_instance_lineage_by_euids(
                file_euid, file_reference.euid, reference_type
            )
            
        if file_set_euid not in [None]:
            self.create_generic_instance_lineage_by_euids(
                file_set_euid, file_reference.euid, "from_set"
            )



        self.session.commit()
        return file_reference
    
class BloomFileSet(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_file_set(self, file_uids=[], file_set_metadata={}):
        file_set = self.create_instance(
            self.query_template_by_component_v2("file", "file_set", "generic", "1.0")[
                0
            ].euid,
            {"properties": file_set_metadata},
        )
        self.session.commit()

        return file_set

    def add_files_to_file_set(self, file_set_euid, file_euids=[]):
        file_set = self.get_by_euid(file_set_euid)
        for file_euid in file_euids:
            self.create_generic_instance_lineage_by_euids(file_set_euid, file_euid)
        self.session.commit()
        return file_set

    def get_file_set_by_euid(self, euid):
        return self.get_by_euid(euid)

    def remove_files_from_file_set(self, file_set_euid, file_euids=[]):
        file_set = self.get_by_euid(file_set_euid)

        # delete the lineage for each file to this file set
        for file_euid in file_euids:
            for i in file_set.child_of_lineages:
                if i.child_instance.euid == file_euid:
                    self.delete_obj(i)

        self.session.commit()
        return file_set

    def search_file_sets_by_metadata(self, search_criteria, greedy=True):
        """
        Search for file sets based on additional metadata.

        :param search_criteria: Dictionary containing the metadata to search for.
        :param greedy: Boolean indicating whether to perform a greedy search (matching any criteria) or not (matching all criteria).
        :return: List of EUIDs of matching file sets.
        """

        query = self.session.query(self.Base.classes.file_instance)

        if greedy:
            # Greedy search: matching any of the provided search keys
            or_conditions = []
            for key, value in search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )

                # Create conditions for JSONB key-value pairs
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        jsonb_filter = {key: {sub_key: sub_value}}
                        or_conditions.append(
                            self.Base.classes.file_set_instance.json_addl.op("@>")(
                                jsonb_filter
                            )
                        )
                else:
                    jsonb_filter = {key: value}
                    or_conditions.append(
                        self.Base.classes.file_set_instance.json_addl.op("@>")(
                            jsonb_filter
                        )
                    )

            if or_conditions:
                query = query.filter(or_(*or_conditions))
        else:
            # Non-greedy search: matching all specified search terms
            and_conditions = []
            for key, value in search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )

                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        jsonb_filter = {key: {sub_key: sub_value}}
                        and_conditions.append(
                            self.Base.classes.file_set_instance.json_addl.op("@>")(
                                jsonb_filter
                            )
                        )
                else:
                    jsonb_filter = {key: value}
                    and_conditions.append(
                        self.Base.classes.file_set_instance.json_addl.op("@>")(
                            jsonb_filter
                        )
                    )

            if and_conditions:
                query = query.filter(and_(*and_conditions))

        logging.info(f"Generated SQL: {str(query.statement)}")

        results = query.all()
        return [result.euid for result in results]
 
