"""
BLOOM LIMS Domain - Base Classes

This module contains the BloomObj base class which provides core functionality
for all BLOOM domain objects.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import json
import logging
import os
import re

from daylily_tapdb import MissingSeededTemplateError
from sqlalchemy import (
    DateTime,
    and_,
    cast,
    desc,
    func,
    or_,
    text,
)
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.domain.utils import (
    get_datetime_string,
)
from bloom_lims.domain.utils import (
    update_recursive as _update_recursive,
)

# Try to import carrier tracking module (replaced fedex_tracking_day with daylily_carrier_tracking)
try:
    import daylily_carrier_tracking as FTD
except Exception:
    FTD = None

# Universal printer behavior
PGLOBAL = False if os.environ.get("PGLOBAL", False) else True

logger = logging.getLogger(__name__)


class BloomObj:
    def __init__(
        self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False
    ):  # ERROR -- the is_deleted flag should be set, I think, at the db level...
        self.logger = logging.getLogger(__name__ + ".BloomObj")
        self.logger.debug("Instantiating BloomObj")

        self.printer_labs = []
        self.selected_lab = ""
        self.site_printers = []
        self.printer_options = []
        self.zpl_label_styles = []
        self.selected_label_style = "tube_2inX1in"
        if cfg_printers:
            self._config_printers()

        # Move the  fedex and zebra stuff outside these objs
        self.track_fedex = None
        if cfg_fedex:
            fedex_key = os.environ.get("FEDEX_API_KEY")
            fedex_secret = os.environ.get("FEDEX_SECRET")
            if fedex_key and fedex_secret and FTD is not None:
                try:
                    self.track_fedex = FTD.FedexTracker()
                except Exception as e:
                    self.logger.warning(
                        "FedEx tracking disabled; failed to initialize client: %s", e
                    )
            else:
                self.logger.info(
                    "FedEx tracking disabled; missing FEDEX_API_KEY/FEDEX_SECRET"
                )

        self._bdb = bdb
        self.is_deleted = is_deleted
        self.session = bdb.session
        self.Base = bdb.Base
        app_username = str(getattr(bdb, "app_username", "") or "").strip()
        self._actor_user_id = None
        self._actor_email = app_username if "@" in app_username else None

    def set_actor_context(self, *, user_id=None, email=None):
        """Set optional actor identity context used for interaction lineage tracking."""
        user_id_str = str(user_id or "").strip()
        email_str = str(email or "").strip()
        self._actor_user_id = user_id_str or None
        self._actor_email = email_str or self._actor_email
        return self

    def _extract_actor_from_curr_user(self, curr_user):
        actor_user_id = None
        actor_email = None
        if isinstance(curr_user, dict):
            actor_user_id = (
                curr_user.get("cognito_sub")
                or curr_user.get("sub")
                or curr_user.get("user_id")
            )
            actor_email = curr_user.get("email")
        elif isinstance(curr_user, str):
            curr = curr_user.strip()
            if "@" in curr:
                actor_email = curr
            elif curr:
                actor_user_id = curr
        return (str(actor_user_id).strip() or None, str(actor_email).strip() or None)

    def _instance_properties(self, instance):
        payload = instance.json_addl or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        props = payload.get("properties")
        if not isinstance(props, dict):
            props = {}
            payload["properties"] = props
            instance.json_addl = payload
        return payload, props

    def _ensure_user_actor_template(self):
        templates = self.query_template_by_component_v2(
            "actor", "user", "bloom-user", "1.0"
        )
        if templates:
            return templates[0]
        raise MissingSeededTemplateError(
            "Missing seeded TapDB template 'actor/user/bloom-user/1.0/'. "
            "Seed the Bloom TapDB JSON template pack through TapDB before "
            "creating user actor instances."
        )

    def _upsert_user_actor(self, *, user_id=None, email=None):
        resolved_user_id = str(user_id or "").strip() or None
        resolved_email = str(email or "").strip() or None
        if not resolved_user_id and not resolved_email:
            return None

        actors = (
            self.session.query(self.Base.classes.generic_instance)
            .filter(
                self.Base.classes.generic_instance.category == "actor",
                self.Base.classes.generic_instance.type == "user",
                self.Base.classes.generic_instance.subtype == "bloom-user",
                self.Base.classes.generic_instance.version == "1.0",
                self.Base.classes.generic_instance.is_deleted == False,  # noqa: E712
            )
            .all()
        )

        actor = None
        for candidate in actors:
            _, props = self._instance_properties(candidate)
            candidate_sub = str(props.get("cognito_sub") or "").strip()
            candidate_email = str(props.get("email") or "").strip().lower()
            if resolved_user_id and candidate_sub == resolved_user_id:
                actor = candidate
                break
            if resolved_email and candidate_email == resolved_email.lower():
                actor = candidate
                break

        if actor is None:
            template = self._ensure_user_actor_template()
            actor_name = resolved_email or resolved_user_id or "Bloom User"
            actor = self.create_instance(
                template.euid,
                json_addl_overrides={
                    "properties": {
                        "name": actor_name,
                        "email": resolved_email or "",
                        "cognito_sub": resolved_user_id or "",
                        "comments": "",
                    }
                },
            )
            return actor

        payload, props = self._instance_properties(actor)
        changed = False
        if resolved_email and props.get("email") != resolved_email:
            props["email"] = resolved_email
            changed = True
        if resolved_user_id and props.get("cognito_sub") != resolved_user_id:
            props["cognito_sub"] = resolved_user_id
            changed = True
        if resolved_email and actor.name != resolved_email:
            actor.name = resolved_email
            changed = True
        if changed:
            payload["properties"] = props
            actor.json_addl = payload
            flag_modified(actor, "json_addl")
            self.session.commit()

        return actor

    def track_user_interaction(
        self,
        target_euid,
        *,
        relationship_type="user_interacted",
        action_ds=None,
        user_id=None,
        email=None,
    ):
        """Create lineage from a user actor node to a target object."""
        try:
            target_euid = str(target_euid or "").strip()
            if not target_euid:
                return None

            action_user_id = None
            action_email = None
            if isinstance(action_ds, dict):
                action_user_id, action_email = self._extract_actor_from_curr_user(
                    action_ds.get("curr_user")
                )
                if not action_user_id:
                    action_user_id = (
                        str(action_ds.get("curr_user_id") or "").strip() or None
                    )

            actor = self._upsert_user_actor(
                user_id=user_id or action_user_id or self._actor_user_id,
                email=email or action_email or self._actor_email,
            )
            if actor is None or actor.euid == target_euid:
                return None

            target_obj = self.get_by_euid(target_euid)
            if not target_obj or getattr(target_obj, "is_deleted", False):
                return None

            self.create_generic_instance_lineage_by_euids(
                actor.euid,
                target_euid,
                relationship_type=str(relationship_type or "user_interacted"),
            )
            self.session.commit()
            return actor.euid
        except Exception as exc:
            self.logger.warning(
                "Failed to track user interaction (%s -> %s): %s",
                relationship_type,
                target_euid,
                exc,
            )
            try:
                self.session.rollback()
            except Exception:
                pass
            return None

    def _do_action_base(
        self,
        euid,
        action,
        action_group,
        action_ds,
        now_dt=None,
    ):
        """Update generic action bookkeeping and record the acting user lineage."""
        resolved_now_dt = now_dt or get_datetime_string()
        self.logger.debug(
            "Completing Action: %s for %s at %s with %s",
            action,
            euid,
            resolved_now_dt,
            action_ds,
        )
        bobj = self.get_by_euid(euid)
        if "action_groups" not in bobj.json_addl:
            return bobj

        action_state = bobj.json_addl["action_groups"][action_group]["actions"][action]
        curr_action_count = int(action_state["action_executed"])
        new_action_count = curr_action_count + 1

        max_action_count = int(action_state["max_executions"])
        if max_action_count > 0 and new_action_count >= max_action_count:
            action_state["action_enabled"] = "0"
        action_state["action_executed"] = f"{new_action_count}"

        for deactivate_action in action_ds.get("deactivate_actions_when_executed", []):
            try:
                bobj.json_addl["action_groups"][action_group]["actions"][
                    deactivate_action
                ]["action_enabled"] = "0"
            except Exception:
                self.logger.debug(
                    "Failed to deactivate %s for %s at %s with %s",
                    deactivate_action,
                    euid,
                    resolved_now_dt,
                    action_ds,
                )

        action_state["executed_datetime"].append(resolved_now_dt)
        action_state["action_user"].append(action_ds.get("curr_user", "bloomdborm"))

        flag_modified(bobj, "json_addl")
        self.session.commit()
        self.track_user_interaction(
            euid,
            relationship_type=f"user_action:{action}",
            action_ds=action_ds,
        )
        return bobj

    def _fetch_fedex_tracking_ops_meta(self, tracking_number):
        """Fetch FedEx metadata across carrier-tracking API versions."""
        if not self.track_fedex:
            return []

        if hasattr(self.track_fedex, "track_ops_meta"):
            data = self.track_fedex.track_ops_meta(tracking_number)
        elif hasattr(self.track_fedex, "get_fedex_ops_meta_ds"):
            data = self.track_fedex.get_fedex_ops_meta_ds(tracking_number)
        elif hasattr(self.track_fedex, "track"):
            data = self.track_fedex.track(tracking_number)
        else:
            raise AttributeError(
                "FedEx tracker supports neither 'track_ops_meta', "
                "'get_fedex_ops_meta_ds', nor 'track'"
            )

        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return [dict(data)]

    def _config_printers(self):
        from bloom_lims.integrations.zebra_day import ZebraDayService

        printer_info = ZebraDayService().build_printer_preferences()
        self.printer_labs = list(printer_info.get("print_lab", []))
        self.selected_lab = str(printer_info.get("selected_lab", "") or "")
        self.printer_options = list(printer_info.get("printer_options", []))
        self.site_printers = [item["value"] for item in self.printer_options]
        self.zpl_label_styles = list(printer_info.get("label_zpl_style", []))
        self.selected_label_style = (
            self.zpl_label_styles[0] if self.zpl_label_styles else "tube_2inX1in"
        )

    def set_printers_lab(self, lab):
        self.selected_lab = lab

    def get_lab_printers(self, lab):
        from bloom_lims.integrations.zebra_day import ZebraDayService

        printer_info = ZebraDayService().build_printer_preferences(lab)
        self.selected_lab = str(printer_info.get("selected_lab", "") or "")
        self.printer_labs = list(printer_info.get("print_lab", []))
        self.printer_options = list(printer_info.get("printer_options", []))
        self.site_printers = [item["value"] for item in self.printer_options]
        self.zpl_label_styles = list(printer_info.get("label_zpl_style", []))

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
        from bloom_lims.integrations.zebra_day import ZebraDayService

        ZebraDayService().submit_print_job(
            lab=lab,
            printer_id=printer_name,
            euid=euid,
            alt_a=alt_a,
            alt_b=alt_b,
            alt_c=alt_c,
            alt_d=alt_d,
            alt_e=alt_e,
            alt_f=alt_f,
            label_zpl_style=label_zpl_style,
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
            self.logger.debug("No template found with euid: " + template_euid)
            return

        is_singleton = (
            False if template.json_addl.get("singleton", "0") in [0, "0"] else True
        )

        # TapDB ships a built-in system user actor template that must be singleton in practice.
        # The underlying DB enforces a uniqueness constraint on `json_addl.login_identifier`
        # for these instances; attempting to create multiple will raise an IntegrityError.
        is_system_user_actor = (
            template.type == "actor"
            and template.subtype == "system_user"
            and str(template.version or "") == "1.0"
        )

        if is_singleton or is_system_user_actor:
            existing = (
                self.session.query(self.Base.classes.generic_instance)
                .filter(
                    self.Base.classes.generic_instance.template_uid == template.uid,
                    self.Base.classes.generic_instance.is_deleted == False,  # noqa: E712
                )
                .first()
            )
            if existing is not None:
                return existing

        cname = template.polymorphic_discriminator.replace("_template", "_instance")
        parent_instance = getattr(self.Base.classes, f"{cname}")(
            name=template.name,
            type=template.type,
            subtype=template.subtype,
            version=template.version,
            json_addl=template.json_addl,
            template_uid=template.uid,
            bstatus=template.bstatus,
            category=template.category,
            is_singleton=is_singleton,
            polymorphic_discriminator=template.polymorphic_discriminator.replace(
                "_template", "_instance"
            ),
        )

        # Normalize TapDB system-user actor instances to satisfy DB uniqueness constraint.
        if is_system_user_actor:
            # Promote properties.login_identifier to top-level json_addl.login_identifier.
            try:
                payload = parent_instance.json_addl or {}
                props = payload.get("properties") or {}
                login_identifier = str(payload.get("login_identifier") or "").strip()
                if not login_identifier:
                    login_identifier = str(props.get("login_identifier") or "").strip()
                if not login_identifier:
                    login_identifier = "system"
                payload["login_identifier"] = login_identifier
                parent_instance.json_addl = payload
            except Exception:
                # Best-effort: if anything goes wrong, let the DB enforce constraints.
                pass

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

            ~ TABLE_template/{type}/{subtype}/{version} is the pattern used to for the template table name
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
        if template.json_addl.get("instantiation_layouts"):
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

        if not isinstance(action_imports, dict):
            return ret_ds

        normalized_groups = action_imports

        # TapDB action imports can be a flat map: {name: "category/type/subtype/version"}.
        # Normalize to Bloom's grouped format for downstream processing.
        if all(isinstance(v, str) for v in action_imports.values()):
            flat_actions = {}
            for template_code in action_imports.values():
                code = (
                    template_code
                    if str(template_code).endswith("/")
                    else f"{template_code}/"
                )
                flat_actions[code] = {}
            normalized_groups = {
                "core": {
                    "group_order": "1",
                    "group_name": "Core Actions",
                    "actions": flat_actions,
                }
            }

        for group in normalized_groups:
            group_cfg = normalized_groups.get(group, {})
            if not isinstance(group_cfg, dict):
                continue

            actions_cfg = group_cfg.get("actions", {})
            if not isinstance(actions_cfg, dict):
                continue

            ret_ds[group] = {}
            ret_ds[group]["actions"] = {}
            ret_ds[group]["group_order"] = str(group_cfg.get("group_order", "1"))
            ret_ds[group]["group_name"] = str(group_cfg.get("group_name", group))
            for ai in actions_cfg:
                sl = ai.lstrip("/").split("/")
                category = None if sl[0] == "*" else sl[0]
                type_name = None if sl[1] == "*" else sl[1]
                subtype = None if sl[2] == "*" else sl[2]
                version = None if sl[3] == "*" else sl[3]

                res = self.query_template_by_component_v2(
                    category, type_name, subtype, version
                )
                if len(res) == 0:
                    raise Exception(f"Action import {ai} not found in database")

                for r in res:
                    action_key = f"{r.category}/{r.type}/{r.subtype}/{r.version}"
                    action_payload = None
                    if isinstance(r.json_addl, dict):
                        action_payload = r.json_addl.get("action_definition")
                    if action_payload is None:
                        self.logger.debug(
                            "Ignoring retired action import without action_definition: %s",
                            action_key,
                        )
                        continue

                    ret_ds[group]["actions"][action_key] = {
                        **action_payload,
                        "action_template_uid": str(r.uid),
                        "action_template_euid": r.euid,
                        "action_template_code": action_key,
                    }

                    #  I'm allowing overrides to the action properties FROM
                    # The non-action object action definition.  Its mostly shaky b/c the overrides are applied to all actions
                    # in the matched group... so, when all core are imported for example, an override will match all
                    # I think...  for singleton imports should be ok.
                    # this is to be used mostly for the assay links for test requisitions
                    _update_recursive(
                        ret_ds[group]["actions"][action_key],
                        actions_cfg.get(ai, {}),
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
            if isinstance(row, dict) and isinstance(row.get("child_templates"), list):
                relationship_type = str(row.get("relationship_type") or "generic")
                for child_cfg in row["child_templates"]:
                    if not isinstance(child_cfg, dict):
                        continue
                    layout_str = str(child_cfg.get("template_code") or "").strip()
                    if not layout_str:
                        continue
                    layout_ds = {"json_addl": child_cfg.get("json_addl") or {}}
                    child_instance = self._create_child_instance(layout_str, layout_ds)
                    lineage_record = self.Base.classes.generic_instance_lineage(
                        parent_instance_uid=parent_instance.uid,
                        child_instance_uid=child_instance.uid,
                        name=f"{parent_instance.name} :: {child_instance.name}",
                        type=parent_instance.type,
                        subtype=parent_instance.subtype,
                        version=parent_instance.version,
                        json_addl=parent_instance.json_addl,
                        bstatus=parent_instance.bstatus,
                        category=parent_instance.category,
                        parent_type=parent_instance.polymorphic_discriminator,
                        child_type=child_instance.polymorphic_discriminator,
                        polymorphic_discriminator=f"{parent_instance.category}_instance_lineage",
                        relationship_type=relationship_type,
                    )
                    self.session.add(lineage_record)
                    ret_objs[1].append(child_instance)
                continue

            row_entries = row if isinstance(row, list) else [row]
            for ds in row_entries:
                if not isinstance(ds, dict):
                    continue
                for i in ds:
                    layout_str = i
                    layout_ds = ds[i]
                    child_instance = self._create_child_instance(layout_str, layout_ds)
                    lineage_record = self.Base.classes.generic_instance_lineage(
                        parent_instance_uid=parent_instance.uid,
                        child_instance_uid=child_instance.uid,
                        name=f"{parent_instance.name} :: {child_instance.name}",
                        type=parent_instance.type,
                        subtype=parent_instance.subtype,
                        version=parent_instance.version,
                        json_addl=parent_instance.json_addl,
                        bstatus=parent_instance.bstatus,
                        category=parent_instance.category,
                        parent_type=parent_instance.polymorphic_discriminator,
                        child_type=child_instance.polymorphic_discriminator,
                        polymorphic_discriminator=f"{parent_instance.category}_instance_lineage",
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
            parent_instance_uid=parent_instance.uid,
            child_instance_uid=child_instance.uid,
            name=f"{parent_instance.name} :: {child_instance.name}",
            type=parent_instance.type,
            subtype=parent_instance.subtype,
            version=parent_instance.version,
            json_addl=parent_instance.json_addl,
            bstatus=parent_instance.bstatus,
            category="generic",
            parent_type=f"{parent_instance.category}:{parent_instance.type}:{parent_instance.subtype}:{parent_instance.version}",
            child_type=f"{child_instance.category}:{child_instance.type}:{child_instance.subtype}:{child_instance.version}",
            polymorphic_discriminator="generic_instance_lineage",
            relationship_type=relationship_type,
        )
        self.session.add(lineage_record)
        self.session.flush()
        # self.session.commit()

        return lineage_record

    def create_lineage(
        self, parent_instance, child_instance, relationship_type: str = "generic"
    ):
        """
        Backwards-compatible lineage creator.

        Many API routes and legacy code paths refer to `create_lineage(parent, child)`.
        TapDB/Bloom core implementation is `create_generic_instance_lineage_by_euids`.
        """
        parent_euid = getattr(parent_instance, "euid", parent_instance)
        child_euid = getattr(child_instance, "euid", child_instance)
        if not parent_euid or not child_euid:
            raise Exception("parent_instance and child_instance must be provided")
        return self.create_generic_instance_lineage_by_euids(
            parent_instance_euid=parent_euid,
            child_instance_euid=child_euid,
            relationship_type=relationship_type,
        )

    def create_instance_by_code(self, layout_str, layout_ds):
        ret_obj = self._create_child_instance(layout_str, layout_ds)

        return ret_obj

    def _create_child_instance(self, layout_str, layout_ds):
        (
            category,
            type_name,
            subtype,
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

        templates = self.query_template_by_component_v2(
            category, type_name, subtype, version
        )
        if not templates:
            raise Exception(
                f"Template not found: {category}/{type_name}/{subtype}/{version}. "
                "Please ensure the database is seeded with templates."
            )
        template = templates[0]

        new_instance = self.create_instance(template.euid)
        _update_recursive(new_instance.json_addl, defaults_ds)
        flag_modified(new_instance, "json_addl")
        ##self.session.flush()
        self.session.commit()

        return new_instance

    def _parse_layout_string(self, layout_str):
        parts = layout_str.split("/")
        category = parts[0]  # table name now called 'category'
        type_name = parts[1] if len(parts) > 1 else "*"
        subtype = parts[2] if len(parts) > 2 else "*"
        version = (
            parts[3] if len(parts) > 3 else "*"
        )  # Assuming the version is always the third part
        defaults = (
            parts[4] if len(parts) > 4 else ""
        )  # Assuming the defaults is always the fourth part
        return category, type_name, subtype, version, defaults

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

        obj_type_info = f"{classn}/{obj.type}/{obj.subtype}/{obj.version}"

        # Check if the object matches the pattern
        compiled_pattern = re.compile(pattern)
        match = compiled_pattern.search(obj_type_info)

        if match:
            return True

        return False

    """Lookup methods. EUID is the canonical Bloom object identifier."""

    def get_by_euid(self, euid):
        """Global query for euid across all tables in schema with 'euid' field
           note: does not handle is_deleted!
        Args:
            euid str(): euid string

        Returns:
            [] : Array of rows
        """
        if euid is None:
            raise Exception("euid cannot be None")
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
            self.logger.debug("No template found with euid: " + euid)
            raise Exception("No template found with euid: " + euid)
        else:
            return combined_result[0]

    # This is the mechanism for finding the database object(s) which match the template reference pattern
    # V2... why?
    def query_instance_by_component_v2(
        self, category=None, type=None, subtype=None, version=None
    ):
        query = self.session.query(self.Base.classes.generic_instance)

        # Apply filters conditionally
        if category is not None:
            query = query.filter(
                self.Base.classes.generic_instance.category == category
            )
        if type is not None:
            query = query.filter(self.Base.classes.generic_instance.type == type)
        if subtype is not None:
            query = query.filter(self.Base.classes.generic_instance.subtype == subtype)
        if version is not None:
            query = query.filter(self.Base.classes.generic_instance.version == version)

        query = query.filter(
            self.Base.classes.generic_instance.is_deleted == self.is_deleted
        )

        # Execute the query
        return query.all()

    # should abstract to not assume properties key
    def get_unique_property_values(
        self, property_key, category=None, type=None, subtype=None, version=None
    ):
        json_path = property_key.split("->")

        # Start building the query with the base table
        query = self.session.query(self.Base.classes.generic_instance)

        # Add filters based on the provided arguments
        if category:
            query = query.filter(
                self.Base.classes.generic_instance.category == category
            )
        if type:
            query = query.filter(self.Base.classes.generic_instance.type == type)
        if subtype:
            query = query.filter(self.Base.classes.generic_instance.subtype == subtype)
        if version:
            query = query.filter(self.Base.classes.generic_instance.version == version)

        # Add the JSON path extraction and distinct filtering after the base filters
        query = query.with_entities(
            func.distinct(
                func.jsonb_extract_path_text(
                    self.Base.classes.generic_instance.json_addl["properties"],
                    *json_path,
                )
            )
        ).filter(
            func.jsonb_extract_path_text(
                self.Base.classes.generic_instance.json_addl["properties"], *json_path
            ).isnot(None)
        )

        # Execute the query and get the results
        results = query.all()

        # Extract unique values from the query results
        unique_values = [value[0] for value in results if value[0] is not None]

        return unique_values

    def query_template_by_component_v2(
        self, category=None, type=None, subtype=None, version=None
    ):
        query = self.session.query(self.Base.classes.generic_template)

        # Apply filters conditionally
        if category is not None:
            query = query.filter(
                self.Base.classes.generic_template.category == category
            )
        if type is not None:
            query = query.filter(self.Base.classes.generic_template.type == type)

        if subtype is not None:
            query = query.filter(self.Base.classes.generic_template.subtype == subtype)
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
                COALESCE(gt.category, gi.category, gil.category) AS category,
                COALESCE(gt.type, gi.type, gil.type) AS type,
                COALESCE(gt.subtype, gi.subtype, gil.subtype) AS subtype,
                COALESCE(gt.bstatus, gi.bstatus, gil.bstatus) AS status,
                al.old_value,
                al.new_value
            FROM
                audit_log al
                LEFT JOIN generic_template gt ON al.rel_table_uid_fk = gt.uid
                LEFT JOIN generic_instance gi ON al.rel_table_uid_fk = gi.uid
                LEFT JOIN generic_instance_lineage gil ON al.rel_table_uid_fk = gil.uid
            WHERE
                al.changed_by = :username
            ORDER BY
                al.changed_at DESC;
            """
        )

        logging.debug(f"Executing query: {q}")

        result = self.session.execute(q, {"username": username})
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
                COUNT(DISTINCT type) as Distinct_Base_Types,
                COUNT(DISTINCT subtype) as Distinct_Sub_Types,
                COUNT(DISTINCT category) as Distinct_Super_Types,
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
            COUNT(DISTINCT type) as Distinct_Types,
            COUNT(DISTINCT polymorphic_discriminator) as Distinct_Polymorphic_Discriminators,
            COUNT(DISTINCT category) as Distinct_Super_Types,
            COUNT(DISTINCT subtype) as Distinct_Sub_Types,
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
            COUNT(DISTINCT category) as Distinct_Super_Types,
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
            """
            WITH RECURSIVE descendants AS (
            -- Initial query to get the root instance
            SELECT gi.uid, gi.euid, gi.json_addl, gi.created_dt
            FROM generic_instance gi
            WHERE gi.euid = :euid

            UNION ALL

            -- Recursive part to get all descendants
            SELECT child_gi.uid, child_gi.euid, child_gi.json_addl, child_gi.created_dt
            FROM generic_instance_lineage gil
            JOIN descendants d ON gil.parent_instance_uid = d.uid
            JOIN generic_instance child_gi ON gil.child_instance_uid = child_gi.uid
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
        result = self.session.execute(query, {"euid": str(euid)})

        # Extract euids and transit times from the result
        euid_cost_tuples = [(row[0], row[1]) for row in result]

        return euid_cost_tuples

    def query_all_fedex_transit_times_by_ay_euid(self, qx_euid):
        query = text(
            """SELECT gi.euid,
        gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0 ->> 'Transit_Time_sec' AS transit_time
        FROM generic_instance AS gi
        JOIN generic_instance_lineage AS gil1 ON gi.uid = gil1.child_instance_uid
        JOIN generic_instance AS gi_parent1 ON gil1.parent_instance_uid = gi_parent1.uid
        JOIN generic_instance_lineage AS gil2 ON gi_parent1.uid = gil2.child_instance_uid
        JOIN generic_instance AS gi_parent2 ON gil2.parent_instance_uid = gi_parent2.uid
        WHERE
        gi_parent2.euid = :qx_euid AND
        gi.type = 'package' AND
        jsonb_typeof(gi.json_addl -> 'properties') = 'object' AND
        jsonb_typeof(gi.json_addl -> 'properties' -> 'fedex_tracking_data') = 'array' AND
        jsonb_typeof((gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0)) = 'object' AND
        COALESCE(NULLIF(gi.json_addl -> 'properties' -> 'fedex_tracking_data' -> 0 ->> 'Transit_Time_sec', ''), '0') >= '0';
        """
        )

        # Execute the query
        result = self.session.execute(query, {"qx_euid": qx_euid})

        # Extract euids and transit times from the result
        euid_transit_time_tuples = [(row[0], row[1]) for row in result]

        return euid_transit_time_tuples

    def fetch_graph_data_by_node_depth(self, start_euid, depth):
        """
        Fetch graph data for a node and its neighbors up to a specified depth.

        Uses parameterized queries to prevent SQL injection attacks.

        Args:
            start_euid: The EUID of the starting node
            depth: Maximum depth to traverse from the starting node

        Returns:
            Query result containing node and edge data
        """
        # SQL query with parameterized placeholders for security
        # Note: Uses TapDB column names (type, category, subtype) directly
        query = text(
            """WITH RECURSIVE graph_data AS (
                SELECT
                    gi.euid,
                    gi.uid,
                    gi.name,
                    gi.type,
                    gi.category,
                    gi.subtype,
                    gi.version,
                    0 AS depth,
                    NULL::text AS lineage_euid,
                    NULL::text AS lineage_parent_euid,
                    NULL::text AS lineage_child_euid,
                    NULL::text AS relationship_type
                FROM
                    generic_instance gi
                WHERE
                    gi.euid = :start_euid AND gi.is_deleted = FALSE

                UNION

                SELECT
                    gi.euid,
                    gi.uid,
                    gi.name,
                    gi.type,
                    gi.category,
                    gi.subtype,
                    gi.version,
                    gd.depth + 1,
                    gil.euid AS lineage_euid,
                    parent_instance.euid AS lineage_parent_euid,
                    child_instance.euid as lineage_child_euid,
                    gil.relationship_type
                FROM
                    generic_instance_lineage gil
                JOIN
                    generic_instance gi ON gi.uid = gil.child_instance_uid OR gi.uid = gil.parent_instance_uid
                JOIN
                    generic_instance parent_instance ON gil.parent_instance_uid = parent_instance.uid
                JOIN
                    generic_instance child_instance ON gil.child_instance_uid = child_instance.uid
                JOIN
                    graph_data gd ON (gil.parent_instance_uid = gd.uid AND gi.uid = gil.child_instance_uid) OR
                                    (gil.child_instance_uid = gd.uid AND gi.uid = gil.parent_instance_uid)
                WHERE
                    gi.is_deleted = FALSE AND gil.is_deleted = FALSE AND gd.depth < :depth
            )
            SELECT DISTINCT * FROM graph_data;
        """
        )

        # Execute the query with bound parameters (prevents SQL injection)
        result = self.session.execute(
            query, {"start_euid": str(start_euid), "depth": int(depth)}
        )
        return result

    def create_instance_by_template_components(self, category, type, subtype, version):
        templates = self.query_template_by_component_v2(
            category, type, subtype, version
        )
        if not templates:
            raise Exception(
                f"Template not found: {category}/{type}/{subtype}/{version}. "
                "Please ensure the database is seeded with templates (run: bloom init)."
            )
        return self.create_instances(templates[0].euid)

    # Is this too special casey? Belong lower?
    def create_container_with_content(self, cx_quad_tup, mx_quad_tup):
        """ie CX=container, MX=content (material)
        ("content", "control", "giab-HG002", "1.0"),
        ("container", "tube", "tube-generic-10ml", "1.0")
        """
        cx_templates = self.query_template_by_component_v2(
            cx_quad_tup[0], cx_quad_tup[1], cx_quad_tup[2], cx_quad_tup[3]
        )
        if not cx_templates:
            raise Exception(
                f"Container template not found: {'/'.join(cx_quad_tup)}. "
                "Please ensure the database is seeded with templates."
            )
        container = self.create_instance(cx_templates[0].euid)

        mx_templates = self.query_template_by_component_v2(
            mx_quad_tup[0], mx_quad_tup[1], mx_quad_tup[2], mx_quad_tup[3]
        )
        if not mx_templates:
            raise Exception(
                f"Content template not found: {'/'.join(mx_quad_tup)}. "
                "Please ensure the database is seeded with templates."
            )
        content = self.create_instance(mx_templates[0].euid)

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

    def delete(self, euid):
        if euid is None:
            raise Exception("euid cannot be None")
        obj = self.get_by_euid(euid)
        obj.is_deleted = True
        ##self.session.flush()
        self.session.commit()

    def delete_by_euid(self, euid):
        return self.delete(euid)

    def delete_obj(self, obj):
        if obj is None:
            raise Exception("obj cannot be None")
        obj.is_deleted = True
        ##self.session.flush()
        self.session.commit()

    def do_action_add_file_to_file_set(self, file_set_euid, action_ds):
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.domain.files import BloomFileSet

        bfs = BloomFileSet(
            BLOOMdb3(app_username=getattr(self._bdb, "app_username", ""))
        )
        bfs.add_files_to_file_set(
            euid=file_set_euid, file_euid=[action_ds["captured_data"]["file_euid"]]
        )

    def do_action_remove_file_from_file_set(self, file_set_euid, action_ds):
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.domain.files import BloomFileSet

        bfs = BloomFileSet(
            BLOOMdb3(app_username=getattr(self._bdb, "app_username", ""))
        )
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

    def do_action_create_subject_and_anchor(self, euid, action_ds):
        """
        Create a Subject (decision scope) with the given object as the anchor.

        Args:
            euid: EUID of the object to use as anchor
            action_ds: Action data structure with captured_data containing:
                - subject_kind: Type of subject (accession, analysis_bundle, report, generic)
                - subject_name: Optional name for the subject
                - comments: Optional comments

        Returns:
            The created subject EUID, or None if creation failed
        """
        from bloom_lims.subjecting import create_subject

        captured = action_ds.get("captured_data", {})
        subject_kind = captured.get("subject_kind", "generic")
        subject_name = captured.get("subject_name", "")
        comments = captured.get("comments", "")

        extra_props = {}
        if subject_name:
            extra_props["name"] = subject_name
        if comments:
            extra_props["comments"] = comments

        subject_euid = create_subject(
            bob=self,
            anchor_euid=euid,
            subject_kind=subject_kind,
            extra_props=extra_props,
        )

        if subject_euid:
            self.logger.info(f"Created subject {subject_euid} for anchor {euid}")
        else:
            self.logger.error(f"Failed to create subject for anchor {euid}")

        return subject_euid

    def ret_plate_wells_dict(self, plate):
        plate_wells = {}
        for lin in plate.parent_of_lineages:
            if lin.child_instance.type == "well":
                well = lin.child_instance
                content_arr = []
                for c in well.parent_of_lineages:
                    if c.child_instance.category == "content":
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
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.domain.files import BloomFile

        bf = BloomFile(BLOOMdb3(app_username=getattr(self._bdb, "app_username", "")))
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
            if dest_well.child_instance.type == "well":
                well_name = dest_well.child_instance.json_addl["cont_address"]["name"]
                for spod in source_plates_well_digested:
                    if well_name in spod:
                        self.create_generic_instance_lineage_by_euids(
                            spod[well_name][0].euid, dest_well.child_instance.euid
                        )
                        if spod[well_name][1] is not None:
                            for dwc in dest_well.child_instance.parent_of_lineages:
                                if dwc.child_instance.category == "content":
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

        # Filter to only get active (non-deleted) lineages
        active_child_of_lineages = [
            lin for lin in wfset.child_of_lineages if not lin.is_deleted
        ]

        # EXTRAORDINARILY SLOPPY.  I AM IN A REAL RUSH FOR FEATURES THO :-/
        destination_q = ""
        (category, type_name, subtype, version) = (
            action_ds["captured_data"]["q_selection"].lstrip("/").rstrip("/").split("/")
        )

        if len(active_child_of_lineages) == 0:
            self.logger.exception(f"ERROR: No active child_of_lineages for {euid}")
            raise Exception(f"ERROR: No active child_of_lineages for workset {euid}")

        # Get active lineages for traversal (filter out deleted ones)
        current_lineage = active_child_of_lineages[0]
        parent_active_lineages = [
            lin
            for lin in current_lineage.parent_instance.child_of_lineages
            if not lin.is_deleted
        ]

        if len(parent_active_lineages) == 0:
            self.logger.exception("ERROR: No active parent lineages found")
            raise Exception(
                "ERROR: No active parent lineages found for queue traversal"
            )

        parent_of_parent = parent_active_lineages[0].parent_instance
        for q in parent_of_parent.parent_of_lineages:
            if q.is_deleted:
                continue
            if (
                q.child_instance.type == type_name
                and q.child_instance.subtype == subtype
            ):
                destination_q = q.child_instance
                break

        if len(active_child_of_lineages) != 1 or destination_q == "":
            self.logger.exception(
                f"ERROR: {action_ds['captured_data']['q_selection']} - active lineages: {len(active_child_of_lineages)}, destination_q found: {destination_q != ''}"
            )
            raise Exception(f"ERROR: {action_ds['captured_data']['q_selection']}")

        lineage_link = active_child_of_lineages[0]
        self.create_generic_instance_lineage_by_euids(destination_q.euid, wfset.euid)
        self.delete_obj(lineage_link)
        ##self.session.flush()
        self.session.commit()

    # Doing this globally for now
    def do_action_create_package_and_first_workflow_step_assay(
        self, euid, action_ds={}
    ):
        raise RuntimeError(
            "Package/kit accessioning actions have been retired from Bloom. "
            "Accessioning ownership is Atlas-only."
        )

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
        label_zpl_style = action_ds.get("label_zpl_style", "") or action_ds.get(
            "label_style", ""
        )
        alt_a = (
            action_ds.get("alt_a", "")
            if not PGLOBAL
            else f"{bobj.subtype}-{bobj.version}"
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

    def query_audit_log_by_euid(self, euid):
        return (
            self.session.query(self.Base.classes.audit_log)
            .filter(self.Base.classes.audit_log.rel_table_euid_fk == euid)
            .all()
        )

    def check_lineages_for_type(self, lineages, type_name, parent_or_child=None):
        if parent_or_child == "parent":
            for lin in lineages:
                if lin.parent_instance.type == type_name:
                    return True
        elif parent_or_child == "child":
            for lin in lineages:
                if lin.child_instance.type == type_name:
                    return True
        else:
            raise Exception("Must specify parent or child")

        return False

    # Backward compatibility alias
    check_lineages_for_btype = check_lineages_for_type

    def get_cost_of_euid_children(self, euid):
        tot_cost = 0
        ctr = 0
        for ec_tups in self.query_cost_of_all_children(euid):
            tot_cost += float(ec_tups[1])
            ctr += 1
        return tot_cost if ctr > 0 else "na"

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
        type=None,
        subtype=None,
        category=None,
    ):
        query = self.session.query(self.Base.classes.generic_instance)

        def create_datetime_filter(key, value, conditions):
            start_datetime = value.get("start")
            end_datetime = value.get("end", start_datetime)
            if start_datetime > end_datetime:
                self.logger.exception(
                    f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}"
                )
                raise Exception(
                    f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}"
                )

            if start_datetime and end_datetime:
                json_path = key.split("->")

                non_empty_condition = and_(
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    )
                    != "",
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    ).isnot(None),
                )

                datetime_condition = cast(
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    ),
                    DateTime,
                ).between(start_datetime, end_datetime)

                combined_condition = and_(non_empty_condition, datetime_condition)

                conditions.append(combined_condition)

        def handle_jsonb_filter(key, value, conditions):
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key.endswith("_datetime") and isinstance(sub_value, dict):
                        create_datetime_filter(
                            f"{key}->{sub_key}", sub_value, conditions
                        )
                    else:
                        if isinstance(sub_value, list):
                            for item in sub_value:
                                jsonb_filter = {key: {sub_key: item}}
                                conditions.append(
                                    self.Base.classes.generic_instance.json_addl.op(
                                        "@>"
                                    )(json.dumps(jsonb_filter, default=str))
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

        if type is not None:
            query = query.filter(self.Base.classes.generic_instance.type == type)

        if subtype is not None:
            query = query.filter(self.Base.classes.generic_instance.subtype == subtype)

        if category is not None:
            query = query.filter(
                self.Base.classes.generic_instance.category == category
            )

        logging.info(f"Generated SQL: {str(query.statement)}")

        results = query.all()
        return [result.euid for result in results]

    def search_objs_by_addl_metadataOG(
        self,
        file_search_criteria,
        search_greedy=True,
        type=None,
        subtype=None,
        category=None,
    ):
        query = self.session.query(self.Base.classes.generic_instance)

        def create_datetime_filter(key, value, conditions):
            start_datetime = value.get("start")
            end_datetime = value.get("end", start_datetime)
            if start_datetime > end_datetime:
                self.logger.exception(
                    f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}"
                )
                raise Exception(
                    f"ERROR: start_datetime {start_datetime} is greater than end_datetime {end_datetime}"
                )

            if start_datetime and end_datetime:
                json_path = key.split("->")

                non_empty_condition = and_(
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    )
                    != "",
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    ).isnot(None),
                )

                datetime_condition = cast(
                    func.jsonb_extract_path_text(
                        self.Base.classes.generic_instance.json_addl, *json_path
                    ),
                    DateTime,
                ).between(start_datetime, end_datetime)

                combined_condition = and_(non_empty_condition, datetime_condition)

                conditions.append(combined_condition)

        def handle_jsonb_filter(key, value, conditions):
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key.endswith("_datetime") and isinstance(sub_value, dict):
                        create_datetime_filter(
                            f"{key}->{sub_key}", sub_value, conditions
                        )
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

        if type is not None:
            query = query.filter(self.Base.classes.generic_instance.type == type)

        if subtype is not None:
            query = query.filter(self.Base.classes.generic_instance.subtype == subtype)

        if category is not None:
            query = query.filter(
                self.Base.classes.generic_instance.category == category
            )

        logging.info(f"Generated SQL: {str(query.statement)}")

        results = query.all()
        return [result.euid for result in results]


__all__ = [
    "BloomObj",
    "PGLOBAL",
    "logger",
]
