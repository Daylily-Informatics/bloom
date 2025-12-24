"""
BLOOM LIMS Domain - Workflow Classes

This module contains workflow-related classes for workflow definitions,
steps, and instances.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import logging

from sqlalchemy import desc
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.utils import get_datetime_string, generate_random_string
logger = logging.getLogger(__name__)


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
