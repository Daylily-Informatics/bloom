import os
import ast
import json
import sys
import re

import random

import logging
from .logging_config import setup_logging

setup_logging()

from datetime import datetime
import pytz

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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm.attributes import flag_modified
import sqlalchemy.orm as sqla_orm

import zebra_day.print_mgr as zdpm

try:
    import fedex_tracking_day.fedex_track as FTD
except Exception as e:
    pass  # not running in github action for some reason

# Universal printer behavior on
PGLOBAL = False if os.environ.get("PGLOBAL", False) else True

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

    child_instances = relationship(
        "generic_instance",
        primaryjoin="and_(generic_template.uuid == foreign(generic_instance.template_uuid),generic_instance.is_deleted == False)",
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
    parent_of_lineages = relationship(
        "generic_instance_lineage",
        primaryjoin="and_(generic_instance.uuid == foreign(generic_instance_lineage.parent_instance_uuid),generic_instance_lineage.is_deleted == False)",
        backref="parent_instance", lazy='dynamic'
    )
    child_of_lineages = relationship(
        "generic_instance_lineage",
        primaryjoin="and_(generic_instance.uuid == foreign(generic_instance_lineage.child_instance_uuid),generic_instance_lineage.is_deleted == False)",
        backref="child_instance", lazy='dynamic'
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


class BLOOMdb3:
    def __init__(
        self,
        db_url_prefix="postgresql://",
        db_hostname="localhost:"+os.environ.get("PGPORT", "5445"), # 5432
        db_pass=None if 'PGPASSWORD' not in os.environ else os.environ.get("PGPASSWORD"),
        db_user=os.environ.get("USER", "bloom"),
        db_name="bloom",
        app_username=os.environ.get("USER", "bloomdborm"),
        echo_sql=os.environ.get("ECHO_SQL", False)
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
        ]
        for cls in classes_to_register:
            class_name = cls.__name__
            setattr(self.Base.classes, class_name, cls)


    def close(self):
        self.session.close()
        self.engine.dispose()


class BloomObj:
    def __init__(self, bdb, is_deleted=False):
        self.logger = logging.getLogger(__name__ + ".BloomObj")
        self.logger.debug("Instantiating BloomObj")

        # Zebra Day Print Manager
        self.zpld = zdpm.zpl()
        self._config_printers()
        
        try:
            self.track_fedex = FTD.FedexTrack()
        except Exception as e:
            self.track_fedex = None

        self.is_deleted = is_deleted
        self.session = bdb.session
        self.Base = bdb.Base


    def _rebuild_printer_json(self, lab='BLOOM'):
        self.zpld.probe_zebra_printers_add_to_printers_json(lab=lab)
        self.zpld.save_printer_json(self.zpld.printers_filename.split('zebra_day')[-1])
        self._config_printers()

    def _config_printers(self):
        if len(self.zpld.printers['labs'].keys()) == 0:
            self.logger.warning('No printers found, attempting to rebuild printer json\n\n')
            self.logger.warning('This may take a few minutes, lab code will be set to "BLOOM" ... please sit tight...\n\n')
            self._rebuild_printer_json()
            
        self.printer_labs = self.zpld.printers['labs'].keys()
        self.selected_lab = sorted(self.printer_labs)[0]
        self.site_printers = self.zpld.printers['labs'][self.selected_lab].keys()
        _zpl_label_styles = []
        for zpl_f in os.listdir(os.path.dirname(self.zpld.printers_filename) + '/label_styles/'):
            if zpl_f.endswith('.zpl'):
                _zpl_label_styles.append(zpl_f.removesuffix('.zpl'))
        self.zpl_label_styles = sorted(_zpl_label_styles)
        self.selected_label_style = "tube_2inX1in"
        
        
    def set_printers_lab(self, lab):
        self.selected_lab = lab
        
    def get_lab_printers(self, lab):
        self.selected_lab = lab
        try:
            self.site_printers = self.zpld.printers['labs'][self.selected_lab].keys()
        except Exception as e:
            self.logger.error(f'Error getting printers for lab {lab}')
            self.logger.error(e)
            self.logger.error('\n\n\nAttempting to rebuild printer json !!! THIS WILL TAKE TIME !!!\n\n\n')
            self._rebuild_printer_json()
            

    def print_label(self, lab=None, printer_name=None, label_zpl_style="tube_2inX1in", euid="", alt_a="", alt_b="", alt_c="", alt_d="", alt_e="", alt_f="", print_n=1):

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
                    client_ip='pkg',
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
            self.logger.debug(f"No template found with euid:", template_euid)
            return
                
        is_singleton = False if template.json_addl.get("singleton", "0") in [0,"0"] else True
        
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
            raise Exception(f"Error creating instance from template {template_euid} ... {e} .. Likely Singleton Violation")


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
                    _update_recursive(ret_ds[group]["actions"][action_key], action_imports[group]["actions"][ai])

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
        self, parent_instance_euid, child_instance_euid
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
        )
        self.session.add(lineage_record)
        self.session.flush()

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
        self.session.flush()
        #### MAYBE KEEP >>> self.session.commit()

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
        res = self.session.query(self.Base.classes.generic_instance).filter(
                self.Base.classes.generic_instance.uuid == uuid, self.Base.classes.generic_instance.is_deleted==self.is_deleted
            ).all()
        res2 = self.session.query(self.Base.classes.generic_template).filter(
            self.Base.classes.generic_template.uuid == uuid, self.Base.classes.generic_template.is_deleted==self.is_deleted
        ).all()
        res3 = self.session.query(self.Base.classes.generic_instance_lineage).filter(
            self.Base.classes.generic_instance_lineage.uuid == uuid, self.Base.classes.generic_instance_lineage.is_deleted==self.is_deleted
        ).all()
        
        combined_result = res + res2 + res3

        if len(combined_result) > 1:
            raise Exception(f"Multiple {len(combined_results)} templates found for {uuid}") 
        elif len(combined_result) == 0:
            self.logger.debug(f"No template found with uuid:", uuid)
            self.logger.debug(f"On second thought, if we are using a UUID and there is no match.. exception:", uuid)
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
        res = self.session.query(self.Base.classes.generic_instance).filter(
                self.Base.classes.generic_instance.euid == euid, self.Base.classes.generic_instance.is_deleted==self.is_deleted
            ).all()
        res2 = self.session.query(self.Base.classes.generic_template).filter(
            self.Base.classes.generic_template.euid == euid, self.Base.classes.generic_template.is_deleted==self.is_deleted
        ).all()
        res3 = self.session.query(self.Base.classes.generic_instance_lineage).filter(
            self.Base.classes.generic_instance_lineage.euid == euid, self.Base.classes.generic_instance_lineage.is_deleted==self.is_deleted
        ).all()
        
        combined_result = res + res2 + res3

        if len(combined_result) > 1:
            raise Exception(f"Multiple {len(combined_result)} templates found for {euid}") 
        elif len(combined_result) == 0:
            self.logger.debug(f"No template found with euid:", euid)
            raise Exception(f"No template found with euid:", euid)
        else:
            return combined_result[0]

    # This is the mechanism for finding the database object(s) which math the template reference pattern
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

        query = query.filter(self.Base.classes.generic_instance.is_deleted == self.is_deleted)
        
        # Execute the query
        return query.all()

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

        query = query.filter(self.Base.classes.generic_template.is_deleted == self.is_deleted)
        # Execute the query
        return query.all()

    # Aggregate Report SQL
    def query_generic_template_stats(self):
        q = text("""
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
        """)

        result = self.session.execute(q, {'is_deleted': self.is_deleted}).fetchall()

        # Define the column names based on your SELECT statement
        columns = [
            "Report", "Total_Templates", "Distinct_Base_Types", "Distinct_Sub_Types",
            "Distinct_Super_Types", "Latest_Creation_Date", "Earliest_Creation_Date",
            "Average_Age", "Singleton_Count"
        ]

        # Convert each row to a dictionary
        return [dict(zip(columns, row)) for row in result]
    
     
    
    def query_generic_instance_and_lin_stats(self):
        q = text(f"""
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
        """)

        result = self.session.execute(q, {'is_deleted': self.is_deleted}).fetchall()

        # Define the column names based on your SELECT statement
        columns = [
        "Report", "Total_Instances", "Distinct_Types", "Distinct_Polymorphic_Discriminators",
        "Distinct_Super_Types", "Distinct_Sub_Types", "Latest_Creation_Date",
        "Earliest_Creation_Date", "Average_Age"
        ]

        # Convert each row to a dictionary
        return [dict(zip(columns, row)) for row in result]


    def query_cost_of_all_children(self,euid):
        # limited to 10,000 children right now... 
        query = text(f"""
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
        """)
                     
        
        # Execute the query
        result = self.session.execute(query)

        # Extract euids and transit times from the result
        euid_cost_tuples = [(row[0], row[1]) for row in result]

        return euid_cost_tuples

        
    def query_all_fedex_transit_times_by_ay_euid(self, qx_euid):

        query = text(f"""SELECT gi.euid,
       (gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0 ->> 'Transit_Time_sec')::double precision AS transit_time
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
    (gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0 ->> 'Transit_Time_sec')::double precision >= 0;
        """)


        # Execute the query
        result = self.session.execute(query)

        # Extract euids and transit times from the result
        euid_transit_time_tuples = [(row[0], row[1]) for row in result]

        return euid_transit_time_tuples


    def fetch_graph_data_by_node_depth(self, start_euid, depth):
            # SQL query with placeholders for parameters
        query = text(f"""WITH RECURSIVE graph_data AS (
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
                    NULL::text AS lineage_child_euid
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
                    child_instance.euid as lineage_child_euid
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
        """)
        
        # Execute the query
        result = self.session.execute(query)
        return result
        

    def create_instance_by_template_components(
        self, super_type, btype, b_sub_type, version
    ):
        return self.create_instances(
            self.query_template_by_component_v2(
                super_type, btype, b_sub_type, version
            )[0].euid
        )
        
        
    # Is this too special casey? Belong lower?
    def create_container_with_content(self,cx_quad_tup, mx_quad_tup):
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

        container.json_addl['properties']['name'] = content.json_addl['properties']["name"]
        flag_modified(container, "json_addl")
        
        self.create_generic_instance_lineage_by_euids(container.euid, content.euid)
        self.session.flush()
        ### <<< MAYBE KEEP self.session.commit() 

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
    def do_action(self,euid, action, action_group, action_ds, now_dt="" ):

        r=None
        action_method = action_ds["method_name"]
        now_dt = get_datetime_string()
        if action_method == "do_action_set_object_status":
            r=self.do_action_set_object_status(euid, action_ds, action_group, action)
        elif action_method == "do_action_print_barcode_label":
            r=self.do_action_print_barcode_label(euid, action_ds)
            
        elif action_method == "do_action_destroy_specimen_containers":
            r= self.do_action_destroy_specimen_containers(euid, action_ds)
        elif action_method == "do_action_create_package_and_first_workflow_step_assay":
            r = self.do_action_create_package_and_first_workflow_step_assay(euid, action_ds)
        elif action_method == "do_action_move_workset_to_another_queue":
            r= self.do_action_move_workset_to_another_queue(euid, action_ds)
        elif action_method == "do_stamp_plates_into_plate":
            r=self.do_stamp_plates_into_plate(euid, action_ds)
        else:
            raise Exception(f"Unknown do_action method {action_method}")

        self._do_action_base(euid, action, action_group, action_ds, now_dt)
        return r

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
                    self.logger.exception(f"More than one content found for well {well.euid}")
                    raise Exception(f"More than one content found for well {well.euid}")
                
                plate_wells[lin.child_instance.json_addl["cont_address"]["name"]] = (lin.child_instance,content)

        return plate_wells
    
        
    def do_stamp_plates_into_plate(self, euid, action_ds):
        # Taking a stab at moving to a non obsessive commit world
        from IPython import embed; embed(); 
        #pass CX301 CX302
        euid_obj = self.get_by_euid(euid)

        dest_plate = self.get_by_euid(action_ds['captured_data']['Destination Plate EUID'])
        source_plates = []
        source_plates_well_digested = []
        for source_plt_euid in action_ds['captured_data']['source_barcodes'].split('\n'):
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
        #CX292 CX293
        # For all plates being stamped into the destination, link all source plate wells to the destination plate wells, and the contensts of source wells to destination wells.
        # Further, if a dest well is empty, create a new content instance for it and link appropriately.
        for dest_well in dest_plate.parent_of_lineages:
            if dest_well.child_instance.btype == "well":
                well_name = dest_well.child_instance.json_addl['cont_address']['name']
                for spod in source_plates_well_digested:
                    if well_name in spod:
                        self.create_generic_instance_lineage_by_euids(spod[well_name][0].euid,dest_well.child_instance.euid)
                        if spod[well_name][1] != None:
                            for dwc in dest_well.child_instance.parent_of_lineages:
                                if dwc.child_instance.super_type == "content":
                                    self.create_generic_instance_lineage_by_euids(spod[well_name][1].euid, dwc.child_instance.euid)
                        del spod[well_name]
        ## TODO
        ### IF there are any source wells left, create new content instances for them and link to the dest wells
        remaining_wells = 0
        for i in source_plates_well_digested:
            for j in i:
                remaining_wells += 1
        if remaining_wells > 0:
            self.logger.exception(f"ERROR: {remaining_wells} wells left over after stamping")
            self.session.rollback()
            raise Exception(f"ERROR: {remaining_wells} wells left over after stamping")

        self.session.commit()

        return wfs
    
    def do_action_move_workset_to_another_queue(self, euid, action_ds):

        wfset = self.get_by_euid(euid)
        action_ds['captured_data']['q_selection']

        # EXTRAORDINARILY SLOPPY.  I AM IN A REAL RUSH FOR FEATURES THO :-/
        destination_q = ""
        (super_type, btype, b_sub_type, version) = action_ds['captured_data']['q_selection'].lstrip('/').rstrip('/').split('/')
        for q in wfset.child_of_lineages[0].parent_instance.child_of_lineages[0].parent_instance.parent_of_lineages:
            if q.child_instance.btype == btype and q.child_instance.b_sub_type == b_sub_type:
                destination_q = q.child_instance
                break
            
        if len(wfset.child_of_lineages.all()) != 1 or destination_q == "":
            self.logger.exception(f"ERROR: {action_ds['captured_data']['q_selection']}")
            self.logger.exception(f"ERROR: {action_ds['captured_data']['q_selection']}")
            raise Exception(f"ERROR: {action_ds['captured_data']['q_selection']}")

        lineage_link = wfset.child_of_lineages[0]
        self.create_generic_instance_lineage_by_euids(destination_q.euid, wfset.euid)
        self.delete_obj(lineage_link)

        self.session.commit()
                                                  

    # Doing this globally for now
    def do_action_create_package_and_first_workflow_step_assay(self, euid, action_ds={}):   
        wf = self.get_by_euid(euid)
                    
        active_workset_q_wfs = ""
        (super_type, btype, b_sub_type, version) = list(action_ds["workflow_step_to_attach_as_child"].keys())[0].lstrip('/').rstrip('/').split('/')
        for pwf_child_lin in wf.parent_of_lineages:
            if pwf_child_lin.child_instance.btype == btype and pwf_child_lin.child_instance.b_sub_type == b_sub_type:
                active_workset_q_wfs = pwf_child_lin.child_instance
                break
        if active_workset_q_wfs == "":
            self.logger.exception(f"ERROR: {action_ds['workflow_step_to_attach_as_child'].keys()}")
            raise Exception(f"ERROR: {action_ds['workflow_step_to_attach_as_child'].keys()}")
                                                                                                                   
        # 1001897582860000245100773464327825
        fx_opsmd = {}

        try:
            fx_opsmd = self.track_fedex.get_fedex_ops_meta_ds(
                action_ds["captured_data"]["Tracking Number"]
            )
        except Exception as e:
            self.logger.exception(f"ERROR: {e}")

        action_ds["captured_data"]["Fedex Tracking Data"] = fx_opsmd

        wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            self.create_generic_instance_lineage_by_euids(active_workset_q_wfs.euid, wfs.euid)
            ###self.session.commit()
    
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
            
            ###self.session.commit()

        ### self.session.commit()

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

        lab = action_ds.get("lab","")
        printer_name = action_ds.get("printer_name","")
        label_zpl_style = action_ds.get("label_style","")
        alt_a = action_ds.get("alt_a","") if not PGLOBAL else f"{bobj.b_sub_type}-{bobj.version}" 
        alt_b = action_ds.get("alt_b","") if not PGLOBAL else bobj.json_addl.get("properties",{}).get("name","__namehere__")
        alt_c = action_ds.get("alt_c","") if not PGLOBAL else bobj.json_addl.get("properties",{}).get("lab_code","N/A")
        alt_d = action_ds.get("alt_d","") 
        alt_e = action_ds.get("alt_e","")  if not PGLOBAL else str(bobj.created_dt).split(' ')[0]  
        alt_f = action_ds.get("alt_f","")
        
        self.logger.info(            
                         f"PRINTING BARCODE LABEL for {euid} at {lab} .. {printer_name} .. {label_zpl_style} \n"
                         )
        
        self.print_label(lab=lab,
                         printer_name=printer_name,
                         label_zpl_style=label_zpl_style,
                         euid=euid, 
                         alt_a=alt_a,
                         alt_b=alt_b,
                         alt_c=alt_c,
                         alt_d=alt_d,
                         alt_e=alt_e,
                         alt_f=alt_f
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


    
    def get_cost_of_euid_children(self,euid):
        tot_cost = 0
        ctr = 0
        for ec_tups in self.query_cost_of_all_children(euid):
            tot_cost += float(ec_tups[1])
            ctr += 1
        return tot_cost if ctr > 0 else 'na'
    
        # Start with the provided EUID
        initial_instance = self.session.query(self.Base.classes.generic_instance).filter_by(euid=euid).first()
        if initial_instance:
            return traverse_and_calculate_children_cogs(initial_instance)
        else:
            return 0

    def get_cogs_to_produce_euid(self, euid):

        # Function to fetch and calculate the COGS for a given object
        def calculate_cogs(orm_instance):
            if 'cogs' not in orm_instance.json_addl or 'state' not in orm_instance.json_addl['cogs']:
                raise ValueError(f"COGS or state information missing for EUID: {orm_instance.euid}")
            
            if orm_instance.json_addl['cogs']['state'] != 'active':
                return 0

            cost = float(orm_instance.json_addl['cogs']['cost'])
            fractional_cost = float(orm_instance.json_addl['cogs'].get('fractional_cost', 1))
            allocation_type = orm_instance.json_addl['cogs'].get('allocation_type', 'single')


            active_children = len([child for child in orm_instance.child_of_lineages if 'cogs' in child.json_addl and child.json_addl['cogs'].get('state') == 'active'])
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
        initial_instance = self.session.query(self.Base.classes.generic_instance).filter_by(euid=euid).first()
        if initial_instance:
            return traverse_history_and_calculate_cogs(initial_instance)
        else:
            return 0

class BloomContainer(BloomObj):
    def __init__(self, bdb):
        super().__init__(bdb)

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
    def __init__(self, bdb):
        super().__init__(bdb)

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
    def __init__(self, bdb):
        super().__init__(bdb)

    def create_empty_content(self, template_euid):
        """_summary_

        Args:
            template_euid (_type_): _description_

        Returns:
            _type_: _description_
        """

        return self.create_instances(template_euid)


class BloomWorkflow(BloomObj):
    def __init__(self, bdb):
        super().__init__(bdb)

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
                child_instance.json_addl["properties"].get("step_number", float("0")) if child_instance.json_addl["properties"].get("step_number", float("inf")) not in ["", None] else float("0")
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
            
            ###self.session.commit()

        wf.bstatus = "in_progress"
        flag_modified(wf, "bstatus")
        
        ### self.session.commit()

        for euid in action_ds["captured_data"]["discard_barcodes"].split("\n"):
            try:
                a_container = self.get_by_euid(euid)
                a_container.bstatus = "destroyed"
                flag_modified(a_container, "bstatus")
                ##self.session.flush()
                ###self.session.commit()

                self.create_generic_instance_lineage_by_euids(
                    wfs.euid, a_container.euid
                )
                ###self.session.commit()

            except Exception as e:
                self.logger.exception(f"ERROR: {e}")
                self.logger.exception(f"ERROR: {e}")
                self.logger.exception(f"ERROR: {e}")
                self.session.rollback()

        self.session.commit()
        
        return wfs

    def do_action_create_package_and_first_workflow_step(self, wf_euid, action_ds={}):
        wf = self.get_by_euid(wf_euid)
        # 1001897582860000245100773464327825
        fx_opsmd = {}

        try:
            fx_opsmd = self.track_fedex.get_fedex_ops_meta_ds(
                action_ds["captured_data"]["Tracking Number"]
            )
        except Exception as e:
            self.logger.exception(f"ERROR: {e}")

        action_ds["captured_data"]["Fedex Tracking Data"] = fx_opsmd

        wfs = ""
        for layout_str in action_ds["child_workflow_step_obj"]:
            wfs = self.create_instance_by_code(
                layout_str, action_ds["child_workflow_step_obj"][layout_str]
            )
            # wfs.workflow_instance_uuid = wf.uuid
            self.create_generic_instance_lineage_by_euids(wf.euid, wfs.euid)

            ##self.session.flush()
            ### self.session.commit()

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
            ##self.session.flush()
            ### self.session.commit()
            # wfs.json_addl["properties"]["actual_output_euid"].append(package.euid)
        wf.bstatus = "in_progress"
        flag_modified(wf, "bstatus")
        ##self.session.flush()
        ###self.session.commit()

        self.create_generic_instance_lineage_by_euids(wfs.euid, package.euid)
        
        self.session.commit()
        
        return wfs


class BloomWorkflowStep(BloomObj):
    def __init__(self, bdb):
        super().__init__(bdb)

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
            ### self.session.commit()
        self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)

        new_plt_parts = self.create_instances_from_uuid(str(in_plt.template_uuid))
        new_plt = new_plt_parts[0][0]
        new_wells = new_plt_parts[1]
        self.create_generic_instance_lineage_by_euids(child_wfs.euid, new_plt.euid)
        self.create_generic_instance_lineage_by_euids(in_plt.euid, new_plt.euid)
        ### self.session.commit()
        
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
            ### self.session.commit()
        self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)
        ### self.session.commit()
        
        child_data = ""
        for dlayout_str in action_ds["child_container_obj"]:
            child_data = self.create_instance_by_code(
                dlayout_str, action_ds["child_container_obj"][dlayout_str]
            )
            ### self.session.commit()

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
        (super_type, btype, b_sub_type, version) = list(action_ds["attach_under_root_workflow_queue"].keys())[0].lstrip('/').rstrip('/').split('/')
        for pwf_child_lin in parent_wf.parent_of_lineages:
            if pwf_child_lin.child_instance.btype == btype and pwf_child_lin.child_instance.b_sub_type == b_sub_type:
                active_workset_q_wfs = pwf_child_lin.child_instance
                break
        if active_workset_q_wfs == "":
            self.logger.exception(f"ERROR: {action_ds['attach_under_root_workflow_queue'].keys()}")
            raise Exception(f"ERROR: {action_ds['attach_under_root_workflow_queue'].keys()}")
        
        new_wf = ""
        for wlayout_str in action_ds["workflow_step_to_attach_as_child"]:
            new_wf = self.create_instance_by_code(
                wlayout_str, action_ds["workflow_step_to_attach_as_child"][wlayout_str]
            )
            #### self.session.commit()
        self.create_generic_instance_lineage_by_euids(active_workset_q_wfs.euid, new_wf.euid)

        child_wfs = ""
        for layout_strc in action_ds["child_workflow_step_obj"]:
            child_wfs = self.create_instance_by_code(
                layout_strc, action_ds["child_workflow_step_obj"][layout_strc]
            )
            ### self.session.commit()

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
                    self.create_generic_instance_lineage_by_euids(new_wf.euid, aa.child_instance.euid)
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
            ### self.session.commit()

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

        results = self.query_instance_by_component_v2( super_type, btype, b_sub_type, version)

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
            ### self.session.commit()


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
            ### self.session.commit()

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
                        ###self.session.commit()
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
            ### self.session.commit()

        self.create_generic_instance_lineage_by_euids(wfs.euid, child_wfs.euid)

        new_test_req = ""
        for layout_str in action_ds["test_requisition_obj"]:
            new_test_req = self.create_instance_by_code(
                layout_str, action_ds["test_requisition_obj"][layout_str]
            )
            ### self.session.commit()

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
    def __init__(self, bdb):
        super().__init__(bdb)

    def create_rgnt_24w_plate_TEST(self, rg_code='idt-probes-rare-mendelian'):
        # I am taking a short cut and not taking time to think about making this generic.

        containers = self.create_instances(
            self.query_template_by_component_v2(
                "container", "plate", "fixed-plate-24", "1.0"
            )[0].euid
        )
        #CX397 8
        
        plate = containers[0][0]
        wells = containers[1]   
        probe_ctr = 1
        plate.json_addl["properties"]["name"] = rg_code
        for i in wells:
            probe_name = f"id_probe_{probe_ctr}"
            seq_1 = ''.join(random.choices('ATCG', k=18))
            seq_2 = ''.join(random.choices('ATCG', k=18))
        
            new_reagent = self.create_instance(
                self.query_template_by_component_v2(
                    "content", "reagent", rg_code, "1.0"
                )[0].euid, {"properties": {"name": f"idt probe set {probe_name}", "probe_name": probe_name, "probe_seq_1": seq_1, "probe_seq_2": seq_2}}
            )
            self.create_generic_instance_lineage_by_euids(i.euid, new_reagent.euid)
            probe_ctr += 1
        self.session.commit()   
        return plate.euid
        
class BloomEquipment(BloomObj):
    def __init__(self, bdb):
        super().__init__(bdb)

    def create_empty_equipment(self, template_euid):
        return self.create_instances(template_euid)


class BloomObjectSet(BloomObj):
    def __init__(self, bdb):
        super().__init__(bdb)


class AuditLog(BloomObj):
    def __init__(self, session, base):
        super().__init__(session, base)
 
