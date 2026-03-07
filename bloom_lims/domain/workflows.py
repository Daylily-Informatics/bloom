"""
BLOOM LIMS Domain - Workflow Classes

This module contains workflow-related classes for workflow definitions,
steps, and instances.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import csv
import logging
import re

from sqlalchemy import desc
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.utils import get_datetime_string, generate_random_string
logger = logging.getLogger(__name__)


class BloomWorkflow(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

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
            if child_instance.category == "workflow_step":
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
            self.create_generic_instance_lineage_by_euids(wf.euid, wfs.euid)
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
        elif action_method == "do_action_move_instances_to_queue":
            self.do_action_move_instances_to_queue(wfs_euid, action_ds)
        elif action_method == "do_action_plate_create_fill_auto":
            self.do_action_plate_create_fill_auto(wfs_euid, action_ds)
        elif action_method == "do_action_plate_create_fill_directed":
            self.do_action_plate_create_fill_directed(wfs_euid, action_ds)
        elif action_method == "do_action_existing_plate_fill_auto":
            self.do_action_existing_plate_fill_auto(wfs_euid, action_ds)
        elif action_method == "do_action_existing_plate_fill_directed":
            self.do_action_existing_plate_fill_directed(wfs_euid, action_ds)
        elif action_method == "do_action_save_quant_data":
            self.do_action_save_quant_data(wfs_euid, action_ds)
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

    def _step_number(self, step_obj):
        json_addl = step_obj.json_addl if isinstance(step_obj.json_addl, dict) else {}
        props = json_addl.get("properties", {})
        return props.get("step_number")

    def _step_sort_key(self, step_obj):
        step_number = self._step_number(step_obj)
        try:
            return (int(step_number), step_obj.euid)
        except (TypeError, ValueError):
            return (10**9, step_obj.euid)

    def _iter_active_child_instances(
        self, parent_obj, category=None, type_name=None, subtype=None
    ):
        for lineage in parent_obj.parent_of_lineages:
            child = lineage.child_instance
            if lineage.is_deleted or child is None:
                continue
            if getattr(child, "is_deleted", False):
                continue
            if category and child.category != category:
                continue
            if type_name and child.type != type_name:
                continue
            if subtype and child.subtype != subtype:
                continue
            yield lineage, child

    def _get_parent_workflow_for_step(self, step_obj):
        for lineage in step_obj.child_of_lineages:
            parent = lineage.parent_instance
            if lineage.is_deleted or parent is None:
                continue
            if getattr(parent, "is_deleted", False):
                continue
            if parent.category == "workflow":
                return parent
        raise Exception(f"Could not determine parent workflow for step {step_obj.euid}")

    def _get_workflow_steps(self, workflow_obj, subtype=None):
        steps = [
            child
            for _, child in self._iter_active_child_instances(
                workflow_obj, category="workflow_step", type_name="queue", subtype=subtype
            )
        ]
        steps.sort(key=self._step_sort_key)
        return steps

    def _default_queue_name(self, subtype):
        tokens = []
        for token in str(subtype).split("-"):
            if token.lower() == "gdna":
                tokens.append("gDNA")
            elif token.lower() == "ont":
                tokens.append("ONT")
            elif token.lower() == "novaseq":
                tokens.append("Novaseq")
            elif token.lower() == "libprep":
                tokens.append("LibPrep")
            else:
                tokens.append(token.capitalize())
        return " ".join(tokens).strip()

    def _get_or_create_queue_step(self, workflow_obj, queue_subtype):
        existing_steps = self._get_workflow_steps(workflow_obj, subtype=queue_subtype)
        if existing_steps:
            return existing_steps[0]

        current_steps = self._get_workflow_steps(workflow_obj)
        next_step_number = "1"
        if current_steps:
            highest = current_steps[-1]
            try:
                next_step_number = str(int(self._step_number(highest)) + 1)
            except Exception:
                next_step_number = str(len(current_steps) + 1)

        queue_name = self._default_queue_name(queue_subtype)
        layout = f"workflow_step/queue/{queue_subtype}/1.0"
        new_step = self.create_instance_by_code(
            layout,
            {
                "json_addl": {
                    "description": queue_name,
                    "properties": {
                        "name": queue_name,
                        "comments": "",
                        "step_number": next_step_number,
                        "lab_code": "",
                    },
                }
            },
        )
        self.create_generic_instance_lineage_by_euids(workflow_obj.euid, new_step.euid)
        self.session.commit()
        return new_step

    def _merge_captured_text(self, captured_data, key_names):
        if not isinstance(captured_data, dict):
            return ""
        parts = []
        for key in key_names:
            if key not in captured_data:
                continue
            value = captured_data[key]
            if isinstance(value, list):
                for entry in value:
                    entry_text = str(entry).strip()
                    if entry_text:
                        parts.append(entry_text)
            else:
                value_text = str(value).strip()
                if value_text:
                    parts.append(value_text)
        return "\n".join(parts)

    def _parse_reference_tokens(self, raw_text):
        tokens = []
        seen = set()
        for piece in re.split(r"[\n,;]+", raw_text or ""):
            token = piece.strip()
            if not token or token in seen:
                continue
            tokens.append(token)
            seen.add(token)
        return tokens

    def _parse_instance_refs(self, action_ds):
        captured = action_ds.get("captured_data", {}) if isinstance(action_ds, dict) else {}
        merged_text = self._merge_captured_text(
            captured,
            ("instance_refs", "instance_refs_file_text", "instance_refs_file"),
        )
        refs = self._parse_reference_tokens(merged_text)
        if not refs:
            raise Exception("No instance refs were provided")
        return refs

    def _resolve_well_by_plate_and_address(self, plate_euid, well_address):
        plate = self.get_by_euid(plate_euid)
        if (
            plate is None
            or plate.category != "container"
            or plate.type != "plate"
            or plate.is_deleted
        ):
            raise Exception(f"Invalid plate EUID in reference: {plate_euid}")

        target_address = str(well_address).strip().upper()
        for _, child in self._iter_active_child_instances(
            plate, category="container", type_name="well"
        ):
            address = (
                child.json_addl.get("cont_address", {}).get("name", "")
                if isinstance(child.json_addl, dict)
                else ""
            )
            if str(address).strip().upper() == target_address:
                return child
        raise Exception(f"Could not resolve well {well_address} on plate {plate_euid}")

    def _resolve_instance_reference(self, ref_token):
        token = str(ref_token).strip()
        if "." in token:
            plate_euid, well_address = token.split(".", 1)
            return self._resolve_well_by_plate_and_address(plate_euid.strip(), well_address.strip())

        instance = self.get_by_euid(token)
        if instance is None or getattr(instance, "is_deleted", False):
            raise Exception(f"Could not resolve instance ref '{token}'")
        return instance

    def _get_first_active_child_content(self, instance_obj):
        for _, child in self._iter_active_child_instances(instance_obj, category="content"):
            return child
        return None

    def _ensure_lineage(self, parent_euid, child_euid):
        parent_obj = self.get_by_euid(parent_euid)
        for _, child in self._iter_active_child_instances(parent_obj):
            if child.euid == child_euid:
                return
        self.create_generic_instance_lineage_by_euids(parent_euid, child_euid)

    def _is_well_occupied(self, well_obj):
        for _, child in self._iter_active_child_instances(well_obj, category="content"):
            if child is not None:
                return True
        return False

    def _get_plate_wells_in_address_order(self, plate_obj):
        wells = [
            child
            for _, child in self._iter_active_child_instances(
                plate_obj, category="container", type_name="well"
            )
        ]

        def _addr_sort_key(well_obj):
            cont_address = (
                well_obj.json_addl.get("cont_address", {})
                if isinstance(well_obj.json_addl, dict)
                else {}
            )
            row_idx = cont_address.get("row_idx", 0)
            col_idx = cont_address.get("col_idx", 0)
            try:
                row_idx = int(row_idx)
            except Exception:
                row_idx = 0
            try:
                col_idx = int(col_idx)
            except Exception:
                col_idx = 0
            return (row_idx, col_idx, well_obj.euid)

        wells.sort(key=_addr_sort_key)
        return wells

    def _create_plate_instance(self, plate_subtype="fixed-plate-96"):
        templates = self.query_template_by_component_v2(
            "container", "plate", plate_subtype, "1.0"
        )
        if not templates:
            raise Exception(
                f"Template not found: container/plate/{plate_subtype}/1.0"
            )
        plate_parts = self.create_instances(templates[0].euid)
        return plate_parts[0][0]

    def _create_output_gdna_content(self, normalized=False):
        templates = self.query_template_by_component_v2("content", "sample", "gdna", "1.0")
        if not templates:
            raise Exception("Template not found: content/sample/gdna/1.0")
        content_obj = self.create_instances(templates[0].euid)[0][0]
        if normalized:
            props = content_obj.json_addl.setdefault("properties", {})
            props["normalized"] = "true"
            props["normalization_state"] = "normalized"
            flag_modified(content_obj, "json_addl")
        return content_obj

    def _resolve_destination_well_ref(self, plate_obj, dest_ref):
        token = str(dest_ref).strip()
        plate_euid = plate_obj.euid
        well_address = token
        if "." in token:
            plate_part, well_part = token.split(".", 1)
            if plate_part.strip() and plate_part.strip() != plate_obj.euid:
                raise Exception(
                    f"Destination mapping '{dest_ref}' does not target destination plate {plate_obj.euid}"
                )
            well_address = well_part.strip()
        return self._resolve_well_by_plate_and_address(plate_euid, well_address)

    def _parse_mapping_rows(self, action_ds):
        captured = action_ds.get("captured_data", {}) if isinstance(action_ds, dict) else {}
        merged = self._merge_captured_text(
            captured,
            ("mapping_csv_text", "mapping_csv_file_text", "mapping_csv_file"),
        )
        if not merged.strip():
            raise Exception("Missing directed mapping CSV")

        rows = []
        for row in csv.reader(merged.splitlines()):
            if not row:
                continue
            source_ref = str(row[0]).strip()
            dest_ref = str(row[1]).strip() if len(row) > 1 else ""
            if not source_ref and not dest_ref:
                continue
            if source_ref.lower() in ("source_ref", "source", "instance_ref"):
                continue
            if not source_ref or not dest_ref:
                raise Exception(f"Invalid mapping row: {row}")
            rows.append((source_ref, dest_ref))

        if not rows:
            raise Exception("No valid mapping rows found")
        return rows

    def _parse_quant_rows(self, action_ds):
        captured = action_ds.get("captured_data", {}) if isinstance(action_ds, dict) else {}
        merged = self._merge_captured_text(
            captured,
            ("quant_csv_text", "quant_csv_file_text", "quant_csv_file"),
        )
        if not merged.strip():
            raise Exception("Missing quant CSV data")

        quant_rows = []
        for row in csv.reader(merged.splitlines()):
            if not row:
                continue
            first = str(row[0]).strip().lower() if len(row) > 0 else ""
            if first in ("plate_euid", "plate"):
                continue
            if len(row) < 3:
                raise Exception(f"Invalid quant row: {row}")
            plate_euid = str(row[0]).strip()
            well_address = str(row[1]).strip()
            quant_raw = str(row[2]).strip()
            if not plate_euid or not well_address or not quant_raw:
                raise Exception(f"Invalid quant row: {row}")
            try:
                quant_value = float(quant_raw)
            except ValueError as exc:
                raise Exception(f"Quant value must be float for row: {row}") from exc
            quant_rows.append((plate_euid, well_address, quant_value))

        if not quant_rows:
            raise Exception("No valid quant rows found")
        return quant_rows

    def _fill_plate_from_sources(
        self,
        queue_step_obj,
        plate_obj,
        source_refs,
        directed_mapping=None,
    ):
        if not source_refs:
            raise Exception("No source refs were provided")

        normalized = queue_step_obj.subtype == "input-gdna-normalization-eligible"
        destinations = {}

        if directed_mapping:
            for source_ref, dest_ref in directed_mapping:
                source_instance = self._resolve_instance_reference(source_ref)
                destination_well = self._resolve_destination_well_ref(plate_obj, dest_ref)
                if self._is_well_occupied(destination_well):
                    raise Exception(
                        f"Destination well already occupied: {plate_obj.euid}.{destination_well.json_addl.get('cont_address', {}).get('name', '')}"
                    )
                destinations[source_instance.euid] = destination_well
        else:
            resolved_sources = [self._resolve_instance_reference(ref) for ref in source_refs]
            available_wells = [
                w for w in self._get_plate_wells_in_address_order(plate_obj) if not self._is_well_occupied(w)
            ]
            if len(available_wells) < len(resolved_sources):
                raise Exception(
                    f"Not enough available wells on destination plate {plate_obj.euid} (needed {len(resolved_sources)}, available {len(available_wells)})"
                )
            for idx, source_instance in enumerate(resolved_sources):
                destinations[source_instance.euid] = available_wells[idx]

        self._ensure_lineage(queue_step_obj.euid, plate_obj.euid)

        for source_ref in source_refs:
            source_instance = self._resolve_instance_reference(source_ref)
            source_content = self._get_first_active_child_content(source_instance)
            destination_well = destinations.get(source_instance.euid)
            if destination_well is None:
                raise Exception(f"No destination mapping found for source {source_ref}")

            output_content = self._create_output_gdna_content(normalized=normalized)

            self._ensure_lineage(source_instance.euid, destination_well.euid)
            if source_content:
                self._ensure_lineage(source_content.euid, output_content.euid)
            self._ensure_lineage(destination_well.euid, output_content.euid)

    def _get_library_prep_targets(self, workflow_obj):
        props = workflow_obj.json_addl.get("properties", {}) if isinstance(workflow_obj.json_addl, dict) else {}
        targets = props.get("library_prep_queue_subtypes", [])
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list):
            targets = []
        cleaned = [str(t).strip() for t in targets if str(t).strip()]
        if cleaned:
            return cleaned
        return ["illumina-novaseq-libprep-eligible", "ont-libprep-eligible"]

    def _route_instances_to_library_prep_queues(self, queue_step_obj, instances):
        workflow_obj = self._get_parent_workflow_for_step(queue_step_obj)
        targets = self._get_library_prep_targets(workflow_obj)
        for queue_subtype in targets:
            destination_queue = self._get_or_create_queue_step(workflow_obj, queue_subtype)
            for instance in instances:
                self._ensure_lineage(destination_queue.euid, instance.euid)

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
            if w.child_instance.type == "well":
                wells_ds[w.child_instance.json_addl["cont_address"]["name"]] = [
                    w.child_instance
                ]
                for wsl in w.child_instance.parent_of_lineages:
                    if wsl.child_instance.category in [
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

        new_plt_parts = self.create_instances(self.get_by_euid(in_plt.euid).template.euid)
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
                new_samp = self.create_instances(self.get_by_euid(in_samp.euid).template.euid)[0][0]
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
            if ch.child_instance.type == "plate":
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
                if mx.child_instance.type == "specimen":
                    cx_ds[cx] = mx.child_instance

        category = "content"
        type_name = "sample"
        subtype = "blood-plasma"
        version = "1.0"
        results = self.query_template_by_component_v2(
            category, type_name, subtype, version
        )
        if not results:
            raise Exception(
                f"Template not found: {category}/{type_name}/{subtype}/{version}. "
                "Please ensure the database is seeded with templates."
            )
        gdna_template = results[0]

        cx_category = "container"
        cx_type = "tube"
        cx_subtype = "tube-generic-10ml"
        cx_version = "1.0"
        cx_results = self.query_template_by_component_v2(
            cx_category, cx_type, cx_subtype, cx_version
        )
        if not cx_results:
            raise Exception(
                f"Template not found: {cx_category}/{cx_type}/{cx_subtype}/{cx_version}. "
                "Please ensure the database is seeded with templates."
            )
        cx_tube_template = cx_results[0]

        parent_wf = wfs.child_of_lineages[0].parent_instance

        active_workset_q_wfs = ""
        (category, type_name, subtype, version) = (
            list(action_ds["attach_under_root_workflow_queue"].keys())[0]
            .lstrip("/")
            .rstrip("/")
            .split("/")
        )
        for pwf_child_lin in parent_wf.parent_of_lineages:
            if (
                pwf_child_lin.child_instance.type == type_name
                and pwf_child_lin.child_instance.subtype == subtype
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
                if mx.child_instance.type == "sample":
                    cx_ds[cx] = mx.child_instance

        category = "container"
        type_name = "plate"
        subtype = "fixed-plate-24"
        version = "1.0"
        results = self.query_template_by_component_v2(
            category, type_name, subtype, version
        )

        plt_template = results[0]
        plate_wells = self.create_instances(plt_template.euid)
        wells = plate_wells[1]
        plate = plate_wells[0][0]

        c_ctr = 0
        for c in containers:
            if len(c) == 0:
                continue
            category = "content"
            type_name = "sample"
            subtype = "gdna"
            version = "1.0"

            results = self.query_template_by_component_v2(
                category, type_name, subtype, version
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

    def do_action_fill_plate_directed(self, wfs_euid, action_ds):
        return self.do_action_plate_create_fill_directed(wfs_euid, action_ds)

    def do_action_move_instances_to_queue(self, wfs_euid, action_ds):
        queue_step = self.get_by_euid(wfs_euid)
        workflow_obj = self._get_parent_workflow_for_step(queue_step)
        target_queue_subtype = (
            str(action_ds.get("target_queue_subtype", "")).strip()
            or str(
                action_ds.get("captured_data", {}).get("target_queue_subtype", "")
            ).strip()
        )
        if not target_queue_subtype:
            raise Exception("Missing target queue subtype for queue move action")

        destination_queue = self._get_or_create_queue_step(
            workflow_obj, target_queue_subtype
        )
        source_refs = self._parse_instance_refs(action_ds)

        for source_ref in source_refs:
            instance_obj = self._resolve_instance_reference(source_ref)
            source_lineage = None
            for lineage in instance_obj.child_of_lineages:
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or getattr(parent, "is_deleted", False):
                    continue
                if parent.euid == queue_step.euid:
                    source_lineage = lineage
                    break
            if source_lineage is None:
                raise Exception(
                    f"Instance {instance_obj.euid} is not currently in source queue {queue_step.euid}"
                )

            self._ensure_lineage(destination_queue.euid, instance_obj.euid)
            self.delete_obj(source_lineage)

        self.session.commit()
        return destination_queue

    def do_action_plate_create_fill_auto(self, wfs_euid, action_ds):
        queue_step = self.get_by_euid(wfs_euid)
        source_refs = self._parse_instance_refs(action_ds)
        plate_obj = self._create_plate_instance("fixed-plate-96")
        self._fill_plate_from_sources(queue_step, plate_obj, source_refs)
        self.session.commit()
        return plate_obj

    def do_action_plate_create_fill_directed(self, wfs_euid, action_ds):
        queue_step = self.get_by_euid(wfs_euid)
        mapping_rows = self._parse_mapping_rows(action_ds)
        source_refs = self._parse_reference_tokens(
            self._merge_captured_text(
                action_ds.get("captured_data", {}),
                ("instance_refs", "instance_refs_file_text", "instance_refs_file"),
            )
        )
        if not source_refs:
            source_refs = [source_ref for source_ref, _ in mapping_rows]
        source_ref_set = set(source_refs)
        for source_ref, _ in mapping_rows:
            if source_ref not in source_ref_set:
                raise Exception(
                    f"Directed mapping source '{source_ref}' was not provided in source refs"
                )

        plate_obj = self._create_plate_instance("fixed-plate-96")
        self._fill_plate_from_sources(
            queue_step,
            plate_obj,
            source_refs,
            directed_mapping=mapping_rows,
        )
        self.session.commit()
        return plate_obj

    def do_action_existing_plate_fill_auto(self, wfs_euid, action_ds):
        queue_step = self.get_by_euid(wfs_euid)
        captured = action_ds.get("captured_data", {})
        destination_plate_euid = str(captured.get("destination_plate_euid", "")).strip()
        if not destination_plate_euid:
            raise Exception("Missing destination plate EUID")
        plate_obj = self.get_by_euid(destination_plate_euid)
        if (
            plate_obj is None
            or plate_obj.category != "container"
            or plate_obj.type != "plate"
            or plate_obj.is_deleted
        ):
            raise Exception(f"Destination plate not found: {destination_plate_euid}")

        source_refs = self._parse_instance_refs(action_ds)
        self._fill_plate_from_sources(queue_step, plate_obj, source_refs)
        self.session.commit()
        return plate_obj

    def do_action_existing_plate_fill_directed(self, wfs_euid, action_ds):
        queue_step = self.get_by_euid(wfs_euid)
        captured = action_ds.get("captured_data", {})
        destination_plate_euid = str(captured.get("destination_plate_euid", "")).strip()
        if not destination_plate_euid:
            raise Exception("Missing destination plate EUID")
        plate_obj = self.get_by_euid(destination_plate_euid)
        if (
            plate_obj is None
            or plate_obj.category != "container"
            or plate_obj.type != "plate"
            or plate_obj.is_deleted
        ):
            raise Exception(f"Destination plate not found: {destination_plate_euid}")

        mapping_rows = self._parse_mapping_rows(action_ds)
        source_refs = self._parse_reference_tokens(
            self._merge_captured_text(
                captured, ("instance_refs", "instance_refs_file_text", "instance_refs_file")
            )
        )
        if not source_refs:
            source_refs = [source_ref for source_ref, _ in mapping_rows]
        source_ref_set = set(source_refs)
        for source_ref, _ in mapping_rows:
            if source_ref not in source_ref_set:
                raise Exception(
                    f"Directed mapping source '{source_ref}' was not provided in source refs"
                )

        self._fill_plate_from_sources(
            queue_step,
            plate_obj,
            source_refs,
            directed_mapping=mapping_rows,
        )
        self.session.commit()
        return plate_obj

    def do_action_save_quant_data(self, wfs_euid, action_ds):
        queue_step = self.get_by_euid(wfs_euid)
        quant_rows = self._parse_quant_rows(action_ds)
        updated_wells = {}

        for plate_euid, well_address, quant_value in quant_rows:
            well_obj = self._resolve_well_by_plate_and_address(plate_euid, well_address)
            props = well_obj.json_addl.setdefault("properties", {})
            props["quant_value"] = quant_value
            flag_modified(well_obj, "json_addl")
            updated_wells[well_obj.euid] = well_obj

        self._route_instances_to_library_prep_queues(
            queue_step, list(updated_wells.values())
        )
        self.session.commit()
        return list(updated_wells.values())

    def do_action_add_container_to_assay_q(self, obj_euid, action_ds):
        # This action should be coming to us from a TRI ... kind of breaking my model... how to deal with this?
        assay_selection = str(
            action_ds.get("captured_data", {}).get("assay_selection", "")
        ).strip()
        if not assay_selection:
            raise Exception("Missing assay selection")

        cont_euid = action_ds["captured_data"]["Container EUID"]

        try:
            cx = self.get_by_euid(cont_euid)
            if not self.check_lineages_for_type(
                cx.child_of_lineages, "clinical", parent_or_child="parent"
            ):
                raise Exception(
                    f"Container {cont_euid} does not have a test request as a parent"
                )

        except Exception as e:
            self.logger.exception(f"ERROR: {e}")
            self.session.rollback()
            raise e

        wf = None
        selection_parts = assay_selection.lstrip("/").rstrip("/").split("/")
        # Backward-compatible support for legacy layout-coded selection values.
        if len(selection_parts) == 4 and selection_parts[0] == "workflow":
            category, type_name, subtype, version = selection_parts
            results = self.query_instance_by_component_v2(
                category, type_name, subtype, version
            )
            if len(results) == 0:
                raise Exception(
                    f"Could not find assay instance for {category}/{type_name}/{subtype}/{version}"
                )
            if len(results) > 1:
                # Prefer active instance if multiple are present.
                active_results = [res for res in results if str(res.bstatus) == "active"]
                wf = active_results[0] if active_results else results[0]
                self.logger.warning(
                    "Multiple assay instances for %s/%s/%s/%s; using %s",
                    category,
                    type_name,
                    subtype,
                    version,
                    wf.euid,
                )
            else:
                wf = results[0]
        else:
            # New preferred behavior: assay_selection is selected workflow EUID.
            wf = self.get_by_euid(assay_selection)
            if (
                wf is None
                or wf.category != "workflow"
                or wf.type != "assay"
                or wf.is_deleted
            ):
                raise Exception(
                    f"Selected assay '{assay_selection}' is not a valid active workflow/assay instance"
                )

        wfs = ""

        try:
            extraction_batch_steps = self._get_workflow_steps(
                wf, subtype="extraction-batch-eligible"
            )
            if extraction_batch_steps:
                wfs = extraction_batch_steps[0]
            else:
                # Create the expected ingress queue topology on demand when missing.
                try:
                    wfs = self._get_or_create_queue_step(wf, "extraction-batch-eligible")
                    self.logger.info(
                        "Created extraction ingress queue step %s for assay workflow %s",
                        wfs.euid,
                        wf.euid,
                    )
                except Exception:
                    candidate_steps = self._get_workflow_steps(wf)
                    if candidate_steps:
                        wfs = candidate_steps[0]
                        self.logger.warning(
                            "Fell back to first available queue %s for assay workflow %s",
                            wfs.euid,
                            wf.euid,
                        )
                    else:
                        wfs = self._get_or_create_queue_step(wf, "all-purpose")
                        self.logger.info(
                            "Created fallback queue step %s for assay workflow %s",
                            wfs.euid,
                            wf.euid,
                        )
        except Exception as e:
            self.logger.exception(f"ERROR: {e}")
            self.session.rollback()
            raise e

        # Prevent adding duplicate to queue
        for cur_ci in wfs.parent_of_lineages:
            if cur_ci.is_deleted or getattr(cur_ci.child_instance, "is_deleted", False):
                continue
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
            if i.child_instance.category == "container":
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
            if i.child_instance.type == "tube":
                prior_cont_euid = i.child_instance.euid
                prior_cont_euid_n += 1
        if prior_cont_euid_n != 1:
            self.logger.exception(
                f"Prior container count is {prior_cont_euid_n} for {wfs.euid}, and should be ==1... this logic needs tightening up w/r/t finding the desired plate"
            )
            raise Exception(
                f"Prior container count is {prior_cont_euid_n} for {wfs.euid}, and should be ==1... this logic needs tightening up"
            )

        self.create_generic_instance_lineage_by_euids(
            new_test_req.euid, prior_cont_euid
        )
        self.create_generic_instance_lineage_by_euids(child_wfs.euid, new_test_req.euid)
        self.session.commit()
        return (child_wfs, new_test_req, prior_cont_euid)




__all__ = [
    "BloomWorkflow",
    "BloomWorkflowStep",
]
