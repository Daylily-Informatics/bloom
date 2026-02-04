import pytest
from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomWorkflow, BloomWorkflowStep
import sys


def set_status(b, obj, status):
    action = "action/core/set_object_status/1.0"
    action_group = "core"

    action_ds = obj.json_addl["action_groups"][action_group]["actions"][action]
    action_ds["captured_data"]["object_status"] = status
    b.do_action(obj.euid, action, action_group, action_ds)
            
    def create_tubes(n=1):
        ctr = 0
        while ctr < n:

            #records = (
            #    bob_wfs.session.query(bob_wfs.Base.classes.workflow_template)
            #    .filter(
            #        bob_wfs.Base.classes.workflow_template.subtype
            #        == "accession-package-kit-tubes-testreq"
            #    )
            #    .all()
            #)

            #wf = bob_wfs.create_instances(records[0].euid)[0][0]

            # Clinical ACC Queue
            #    accessioning-RnD
            
            #from IPython import embed; embed()
            #raise
            # 
            # 
            wf = bob_wf.query_instance_by_component_v2("workflow", "assay", "accessioning-RnD", "1.0")[0]

            action_group = "accessioning"
            action = "action/accessioning-ay/create_package_and_first_workflow_step_assay_root/1.0"
            action_data = wf.json_addl["action_groups"][action_group]["actions"][action]
            # action_data = wf.json_addl["actions"]["create_package_and_first_workflow_step"]
            action_data["captured_data"]["Tracking Number"] = "1001897582860000245100773464327825"
            action_data["captured_data"]["Fedex Tracking Data"] = {}


            wfs=bob_wf.do_action(wf.euid, action, action_group, action_data)
            set_status(bob_wfs, wfs, "in_progress")

            #wfs = bob_wf.do_action_create_package_and_first_workflow_step_assay(wf.euid, action_data)
        
            assert hasattr(wfs, "euid") == True

            b_action_group = "create_child"  # change to child
            #create_package_and_first_workflow_step_assay
            b_action = "action/workflow_step_accessioning/create_child_container_and_link_child_workflow_step/1.0" # "action/workflow_step_accessioning/create_child_container_and_link_child_workflow_step/1.0"
            wfs_action_data = wfs.json_addl["action_groups"][b_action_group]["actions"][b_action]

            wfs_action_data["captured_data"]["Tracking Number"] = "1001897582860000245100773464327825"
            wfs_action_data["captured_data"]["Fedex Tracking Data"] = {}
            bob_wfs.do_action(wfs.euid, b_action, b_action_group, wfs_action_data)

            
            child_wfs = ""
            for i in wfs.parent_of_lineages:
                if i.child_instance.type == "accessioning-steps":
                    child_wfs = i.child_instance

            assert hasattr(child_wfs, "euid") == True
            c_action_group = "specimen_actions"  # change to child
            c_action = "action/workflow_step_accessioning/create_child_container_and_link_child_workflow_step_specimen/1.0"
            c_wfs_action_data = child_wfs.json_addl["action_groups"][c_action_group]["actions"][
                c_action
            ]

            bob_wfs.do_action(child_wfs.euid, c_action, c_action_group, c_wfs_action_data)
            set_status(bob_wfs, wfs, "complete")

            set_status(bob_wfs, child_wfs, "in_progress")

            new_child_wfs = ""
            for i in child_wfs.parent_of_lineages:
                if i.child_instance.category == "workflow_step":
                    new_child_wfs = i.child_instance
            assert hasattr(new_child_wfs, "euid") == True




            trf_wfs = bob_wfs.do_action(
                new_child_wfs.euid,
                "action/workflow_step_accessioning/create_test_req_and_link_child_workflow_step_dup/1.0",
                "test_req",
                new_child_wfs.json_addl["action_groups"]["test_req"]["actions"][
                    "action/workflow_step_accessioning/create_test_req_and_link_child_workflow_step_dup/1.0"
                ],
            )
            set_status(bob_wfs, new_child_wfs, "in_progress")
            set_status(bob_wfs, child_wfs, "complete")


            assert hasattr(trf_wfs, "euid") == True


            trf_child_wfs = ""
            trf_child_cont = ""
            for i in trf_wfs.parent_of_lineages:
                if i.child_instance.category == "workflow_step":
                    trf_child_wfs = i.child_instance
                if i.child_instance.category == "container":
                    trf_child_cont = i.child_instance

            trf = ""
            for i in trf_child_cont.child_of_lineages:
                if i.parent_instance.category == "test_requisition":
                    trf = i.parent_instance


            trf_assay_data = trf.json_addl["action_groups"]["test_requisitions"]["actions"][
                "action/test_requisitions/add_container_to_assay_q/1.0"
            ]
            # This is super brittle, how I am currently linking Assay to TestReq...
            # = tr.json_addl["actions"]["add_container_to_assay_q"]
            trf_assay_data["captured_data"]["assay_selection"] = ASSAY
            trf_assay_data["captured_data"]["Container EUID"] = trf_child_cont.euid

            wfs_queue = bob_wfs.do_action(
                trf.euid,
                action_group="test_requisitions",
                action="action/test_requisitions/add_container_to_assay_q/1.0",
                action_ds=trf_assay_data,
            )
            assert hasattr(wfs_queue, "euid") == True
            set_status(bob_wfs, wfs_queue, "in_progress")


            scanned_bcs = trf_child_cont.euid

            ctr = ctr + 1
            print('CCCCCCCCCCC',ctr)
            TUBES.append(trf_child_cont.euid)



            wset_q = wfs
            wset_q_axn = "action/move-queues/move-among-ay-top-queues/1.0"
            wset_q_axn_grp = "acc-queue-move"
            wset_q_ad = wset_q.json_addl["action_groups"][wset_q_axn_grp][
                "actions"][wset_q_axn]  
            wset_q_ad["captured_data"]["q_selection"] = "workflow_step/queue/plasma-isolation-queue-exception/1.0" if randint(0,13) > 10 else "workflow_step/queue/plasma-isolation-queue-removed/1.0"
            bob_wfs.do_action(
                wset_q.euid,
                action_group=wset_q_axn_grp,
                action=wset_q_axn,
                action_ds=wset_q_ad
            )


    def fill_plates(tubes=[]):
            # Create some controls to add to the plate!
            giab_cx, giab_mx = bob_wf.create_container_with_content(
                ("container", "tube", "tube-generic-10ml", "1.0"),
                ("content", "control", "giab-HG002", "1.0")
            )   
    
            cfsynctl_cx, cfsynctl_mx = bob_wf.create_container_with_content(
                ("container", "tube", "tube-10ml-glass", "1.0"),
                ("content", "control", "synthetic-cfdna", "1.0")
            )  

            ntc_cx, ntc_mx = bob_wf.create_container_with_content( 
                ("container", "tube", "tube-eppi-1.5ml", "1.0"),
                ("content", "control", "water-ntc", "1.0")
            )
            trf_child_cont = bob_wf.get_by_euid(tubes[-1])
            tubes.append(giab_cx.euid)
            tubes.append(cfsynctl_cx.euid)
            tubes.append(ntc_cx.euid)

            scanned_bcs = "\n".join(tubes)
            q_wfs = ""
            for i in trf_child_cont.child_of_lineages:
                if i.parent_instance.subtype == "plasma-isolation-queue-available":
                    q_wfs = i.parent_instance

            piso_q_action_data = q_wfs.json_addl["action_groups"]["tube_xfer"]["actions"][
                "action/workflow_step_queue/link_tubes_auto/1.0"
            ]
            piso_q_action_data["captured_data"]["discard_barcodes"] = scanned_bcs
            wfs_plasma = bob_wfs.do_action(
                q_wfs.euid,
                action_group="tube_xfer",
                action="action/workflow_step_queue/link_tubes_auto/1.0",
                action_ds=piso_q_action_data,
            )  # _link_tubes_auto(wfs_queue.euid, piso_q_action_data)

            plasma_cont = None
            for i in trf_child_cont.parent_of_lineages:
                if i.child_instance.subtype == "tube-generic-10ml":
                    plasma_cont = i.child_instance
            scanned_bcs_plasma = plasma_cont.euid

            for i in plasma_cont.child_of_lineages:
                if i.parent_instance.category == "workflow_step":
                    pi_wfs = i.parent_instance
            
            wfset_wf = pi_wfs.child_of_lineages[0].parent_instance
            
            action_ds_plasma = pi_wfs.json_addl["action_groups"]["fill_plate"]["actions"][
                "action/workflow_step_queue/fill_plate_undirected/1.0"
            ]
            # wfs_plasma.json_addl["actions"]["fill_plate_undirected"]
            action_ds_plasma["captured_data"]["discard_barcodes"] = scanned_bcs_plasma
            wfs_plt = bob_wfs.do_action(
                pi_wfs.euid,
                action_group="fill_plate",
                action="action/workflow_step_queue/fill_plate_undirected/1.0",
                action_ds=action_ds_plasma,
            )
            set_status(bob_wfs, pi_wfs, "complete")

            ### ENDING WITH ANEXTRACTION PLATE!  Need to check quant and add more from here.

            plt_fill_wfs = ""
            for i in wfs_plt.parent_of_lineages:
                if i.child_instance.category == "workflow_step":
                    plt_fill_wfs = i.child_instance

            action_data_dat = plt_fill_wfs.json_addl["action_groups"]["plate_operations"][
                "actions"
            ]["action/workflow_step_plate_operations/cfdna_quant/1.0"]
            # action_data_dat = wfs_plt.json_addl["actions"]["cfdna_quant"]
            action_data_dat["captured_data"]["gdna_quant"] = ""
            yy = bob_wfs.do_action(
                plt_fill_wfs.euid,
                action_group="plate_operations",
                action="action/workflow_step_plate_operations/cfdna_quant/1.0",
                action_ds=action_data_dat,
            )
            set_status(bob_wfs, plt_fill_wfs, "complete")

            eplt = None
            for i in plt_fill_wfs.parent_of_lineages:
                if i.child_instance.category == "workflow_step":
                    eplt = i.child_instance
            set_status(bob_wfs, eplt, "in_progress")

            next_plate = ""
            for i in plt_fill_wfs.parent_of_lineages:
                if i.child_instance.type == "plate":
                    next_plate = i.child_instance.euid

            stamp_action_data = plt_fill_wfs.json_addl["action_groups"]["plate_operations"][
                "actions"
            ]["action/workflow_step_plate_operations/stamp_copy_plate/1.0"]
            stamp_action_data["captured_data"]["plate_euid"] = next_plate

            xx = bob_wfs.do_action(
                plt_fill_wfs.euid,
                action_group="plate_operations",
                action="action/workflow_step_plate_operations/stamp_copy_plate/1.0",
                action_ds=stamp_action_data,
            )

            for i in plt_fill_wfs.parent_of_lineages:
                if i.child_instance.type == "plate-operations":
                    sec_stamp_wfs = i.child_instance

            for i in sec_stamp_wfs.parent_of_lineages:
                if i.child_instance.category == "container":
                    next_plate2 = i.child_instance.euid

            stamp_action_data2 = sec_stamp_wfs.json_addl["action_groups"]["plate_operations"][
                "actions"
            ]["action/workflow_step_plate_operations/stamp_copy_plate/1.0"]
            stamp_action_data2["captured_data"]["plate_euid"] = next_plate2
            stamp_wfs2 = bob_wfs.do_action(
                sec_stamp_wfs.euid,
                action_group="plate_operations",
                action="action/workflow_step_plate_operations/stamp_copy_plate/1.0",
                action_ds=stamp_action_data2,
            )


            # make a control
            rgnt = bob_wfs.create_instance_by_template_components(
                "content", "control", "giab-HG002", "1.0", "active"
            )[0][0]
            # put in a tube
            tube = bob_wfs.create_instance_by_template_components(
                "container", "tube", "tube-generic-10ml", "1.0", "active"
            )[0][0]
            # put the reagent in the tube

            bob_wfs.create_generic_instance_lineage_by_euids(tube.euid, rgnt.euid)


            wset_q = wfset_wf
            wset_q_axn = "action/move-queues/move-among-ay-top-queues/1.0"
            wset_q_axn_grp = "queue-move"
            wset_q_ad = wset_q.json_addl["action_groups"][wset_q_axn_grp][
                "actions"][wset_q_axn]  
            wset_q_ad["captured_data"]["q_selection"] = "workflow_step/queue/plasma-isolation-queue-exception/1.0" if randint(0,5) > 4 else "workflow_step/queue/plasma-isolation-queue-removed/1.0"
            bob_wfs.do_action(
                wset_q.euid,
                action_group=wset_q_axn_grp,
                action=wset_q_axn,
                action_ds=wset_q_ad
            )
            

    n_tubes = 1 # no more than 20

    create_tubes(n_tubes)

    fill_plates(tubes=TUBES) 
    
    assert 1 == 1 