"""
Database-backed regression tests for accessioning package workflow actions.
"""

import copy
import html
import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bloom_lims.bobjs import BloomWorkflow, BloomWorkflowStep, BloomObj


# Ensure GUI route auth bypass works in these endpoint tests.
os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

from main import app


def _get_accessioning_assay_workflow(bwf: BloomWorkflow):
    workflows = bwf.query_instance_by_component_v2(
        category="workflow",
        type="assay",
        subtype="accessioning-RnD",
        version="1.0",
    )
    if not workflows:
        pytest.skip("Missing seeded workflow instance: workflow/assay/accessioning-RnD/1.0")
    return workflows[0]


def _find_action_by_method(instance, method_name: str):
    action_groups = (
        instance.json_addl.get("action_groups", {})
        if isinstance(instance.json_addl, dict)
        else {}
    )
    for group_name, group_data in action_groups.items():
        actions = group_data.get("actions", {}) if isinstance(group_data, dict) else {}
        for action_name, action_ds in actions.items():
            if action_ds.get("method_name") == method_name:
                return group_name, action_name, copy.deepcopy(action_ds)
    raise AssertionError(f"No action found for method {method_name}")


def _find_action(instance, method_name: str = None, action_display_name: str = None):
    action_groups = (
        instance.json_addl.get("action_groups", {})
        if isinstance(instance.json_addl, dict)
        else {}
    )
    for group_name, group_data in action_groups.items():
        actions = group_data.get("actions", {}) if isinstance(group_data, dict) else {}
        for action_name, action_ds in actions.items():
            if method_name and action_ds.get("method_name") != method_name:
                continue
            if action_display_name and action_ds.get("action_name") != action_display_name:
                continue
            return group_name, action_name, copy.deepcopy(action_ds)
    raise AssertionError(
        f"No action found for method={method_name!r} action_name={action_display_name!r}"
    )


def _run_register_package_action(bwf: BloomWorkflow, workflow):
    action_group, action_name, action_ds = _find_action_by_method(
        workflow, "do_action_create_package_and_first_workflow_step_assay"
    )
    action_ds.setdefault("captured_data", {})
    action_ds["captured_data"]["Carrier Name"] = "FedEx"
    action_ds["captured_data"]["Tracking Number"] = "TEST-TRACK-1001"
    return bwf.do_action(
        workflow.euid,
        action=action_name,
        action_group=action_group,
        action_ds=action_ds,
    )


def _get_or_create_assay_workflow_with_step_one(bwfs: BloomWorkflowStep):
    def _has_step_one(assay):
        for lin in assay.parent_of_lineages:
            child = lin.child_instance
            if (
                not lin.is_deleted
                and child.category == "workflow_step"
                and str(child.json_addl.get("properties", {}).get("step_number", "")) == "1"
            ):
                return True
        return False

    assays = bwfs.query_instance_by_component_v2(category="workflow", type="assay")
    for assay in assays:
        if _has_step_one(assay):
            return assay

    assay_templates = bwfs.query_template_by_component_v2(category="workflow", type="assay")
    for template in assay_templates:
        try:
            created = bwfs.create_instances(template.euid)
        except Exception:
            # Singleton assay templates may already have an existing instance.
            continue
        assay = created[0][0]
        if _has_step_one(assay):
            return assay

    pytest.skip("No workflow/assay instance with step_number=1 available for assay queue test")


def _get_assay_instance(bobj: BloomObj, subtype: str, version: str):
    assays = bobj.query_instance_by_component_v2(
        category="workflow",
        type="assay",
        subtype=subtype,
        version=version,
    )
    if not assays:
        pytest.skip(f"Missing seeded workflow instance workflow/assay/{subtype}/{version}")
    return assays[0]


def _get_active_queue_step_by_subtype(workflow_obj, subtype: str):
    for lin in workflow_obj.parent_of_lineages:
        child = lin.child_instance
        if lin.is_deleted:
            continue
        if child is None or child.is_deleted:
            continue
        if child.category == "workflow_step" and child.type == "queue" and child.subtype == subtype:
            return child
    return None


def _require_queue_template_or_skip(bobj: BloomObj, subtype: str):
    templates = bobj.query_template_by_component_v2(
        category="workflow_step",
        type="queue",
        subtype=subtype,
        version="1.0",
    )
    if not templates:
        pytest.skip(
            f"Missing workflow_step/queue/{subtype}/1.0 template in DB; run bloom db reset -y && bloom db seed"
        )


def _get_assay_workflow_without_steps(bwfs: BloomWorkflowStep):
    assays = bwfs.query_instance_by_component_v2(category="workflow", type="assay")
    for assay in assays:
        has_workflow_step = any(
            not lin.is_deleted
            and lin.child_instance.category == "workflow_step"
            and not lin.child_instance.is_deleted
            for lin in assay.parent_of_lineages
        )
        if not has_workflow_step:
            return assay
    pytest.skip("No workflow/assay instance without workflow_step children available")


def _get_or_create_test_requisition_with_assay_action(bobj: BloomObj):
    test_reqs = bobj.query_instance_by_component_v2(
        category="test_requisition",
        type="clinical",
    )
    for tri in test_reqs:
        try:
            _find_action_by_method(tri, "do_action_add_container_to_assay_q")
            return tri
        except AssertionError:
            continue

    templates = bobj.query_template_by_component_v2(
        category="test_requisition",
        type="clinical",
        subtype="pan-cancer-panel",
        version="1.0",
    )
    if not templates:
        pytest.skip("Missing clinical test_requisition template with assay queue action")
    created = bobj.create_instances(templates[0].euid)
    tri = created[0][0]
    _find_action_by_method(tri, "do_action_add_container_to_assay_q")
    return tri


def test_register_package_creates_queue_step_when_missing(bdb_function):
    bwf = BloomWorkflow(bdb_function)
    workflow = _get_accessioning_assay_workflow(bwf)

    created_step = _run_register_package_action(bwf, workflow)
    assert hasattr(created_step, "euid")

    workflow = bwf.get_by_euid(workflow.euid)
    queue_steps = [
        lin.child_instance
        for lin in workflow.parent_of_lineages
        if (
            not lin.is_deleted
            and lin.child_instance.category == "workflow_step"
            and lin.child_instance.type == "queue"
            and lin.child_instance.subtype == "all-purpose"
        )
    ]
    assert queue_steps, "Register Package should create/link an all-purpose queue step"

    created_step = bwf.get_by_euid(created_step.euid)
    assert any(
        not lin.is_deleted and lin.parent_instance.euid == queue_steps[0].euid
        for lin in created_step.child_of_lineages
    ), "New package-generated step should be attached under the queue step"

    packages = [
        lin.child_instance
        for lin in created_step.parent_of_lineages
        if (
            not lin.is_deleted
            and lin.child_instance.category == "container"
            and lin.child_instance.type == "package"
        )
    ]
    assert packages, "Register Package should create and link a package container"
    package_props = (
        packages[0].json_addl.get("properties", {})
        if isinstance(packages[0].json_addl, dict)
        else {}
    )
    assert package_props.get("Tracking Number") == "TEST-TRACK-1001"


def test_register_package_output_step_can_advance_accessioning_flow(bdb_function):
    bwf = BloomWorkflow(bdb_function)
    bwfs = BloomWorkflowStep(bdb_function)
    workflow = _get_accessioning_assay_workflow(bwf)
    created_step = _run_register_package_action(bwf, workflow)

    step_obj = bwfs.get_by_euid(created_step.euid)
    action_group, action_name, action_ds = _find_action_by_method(
        step_obj, "do_action_create_child_container_and_link_child_workflow_step"
    )
    child_step = bwfs.do_action(
        created_step.euid,
        action=action_name,
        action_group=action_group,
        action_ds=action_ds,
    )
    assert hasattr(child_step, "euid")

    child_step = bwfs.get_by_euid(child_step.euid)
    assert any(
        not lin.is_deleted and lin.child_instance.category == "container"
        for lin in child_step.parent_of_lineages
    ), "Follow-up accessioning step should have a linked container"


def test_assays_endpoint_handles_missing_status_buckets(bdb_function):
    bwf = BloomWorkflow(bdb_function)
    _get_accessioning_assay_workflow(bwf)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/assays")
    assert response.status_code == 200


def test_workflow_details_renders_child_type_count_chips(bdb_function):
    bwf = BloomWorkflow(bdb_function)
    workflow = _get_accessioning_assay_workflow(bwf)
    _run_register_package_action(bwf, workflow)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/workflow_details?workflow_euid={workflow.euid}")
    assert response.status_code == 200
    assert "child-type-chip" in response.text
    assert 'data-child-type="package"' in response.text or " package" in response.text


def test_euid_details_renders_dynamic_assay_dropdown_from_live_instances(bdb_function):
    bobj = BloomObj(bdb_function)
    tri = _get_or_create_test_requisition_with_assay_action(bobj)
    assay = _get_or_create_assay_workflow_with_step_one(BloomWorkflowStep(bdb_function))

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/euid_details?euid={tri.euid}")
    assert response.status_code == 200

    action_payloads = re.findall(r'data-action-json="([^"]+)"', response.text)
    add_to_queue_action = None
    for encoded_payload in action_payloads:
        payload = json.loads(html.unescape(encoded_payload))
        if payload.get("method_name") == "do_action_add_container_to_assay_q":
            add_to_queue_action = payload
            break

    assert add_to_queue_action is not None, "Expected Add Specimen to Assay Queue action payload"
    select_markup = add_to_queue_action.get("captured_data", {}).get("___workflow/assay/", "")
    assert 'name="assay_selection"' in select_markup
    assert f'value="{assay.euid}"' in select_markup


def test_add_specimen_to_assay_queue_accepts_assay_euid_selection(bdb_function):
    bobj = BloomWorkflowStep(bdb_function)
    tri = _get_or_create_test_requisition_with_assay_action(bobj)
    assay = _get_or_create_assay_workflow_with_step_one(bobj)

    container_templates = bobj.query_template_by_component_v2(
        category="container",
        type="tube",
    )
    if not container_templates:
        pytest.skip("Missing container/tube template for assay queue action test")
    container = bobj.create_instances(container_templates[0].euid)[0][0]

    # Required by the action: the container must be child of a clinical test requisition.
    bobj.create_generic_instance_lineage_by_euids(tri.euid, container.euid)
    bobj.session.commit()

    action_group, action_name, action_ds = _find_action_by_method(
        tri, "do_action_add_container_to_assay_q"
    )
    action_ds.setdefault("captured_data", {})
    action_ds["captured_data"]["Container EUID"] = container.euid
    action_ds["captured_data"]["assay_selection"] = assay.euid

    queued_step = bobj.do_action(
        tri.euid,
        action=action_name,
        action_group=action_group,
        action_ds=action_ds,
    )
    assert hasattr(queued_step, "euid")
    queued_step = bobj.get_by_euid(queued_step.euid)
    assert any(
        not lin.is_deleted and lin.child_instance.euid == container.euid
        for lin in queued_step.parent_of_lineages
    ), "Container should be linked into selected assay queue step"


def test_add_specimen_to_assay_queue_creates_queue_step_when_assay_has_no_steps(
    bdb_function,
):
    bobj = BloomWorkflowStep(bdb_function)
    tri = _get_or_create_test_requisition_with_assay_action(bobj)
    assay = _get_assay_workflow_without_steps(bobj)

    container_templates = bobj.query_template_by_component_v2(
        category="container",
        type="tube",
    )
    if not container_templates:
        pytest.skip("Missing container/tube template for assay queue action test")
    container = bobj.create_instances(container_templates[0].euid)[0][0]

    bobj.create_generic_instance_lineage_by_euids(tri.euid, container.euid)
    bobj.session.commit()

    action_group, action_name, action_ds = _find_action_by_method(
        tri, "do_action_add_container_to_assay_q"
    )
    action_ds.setdefault("captured_data", {})
    action_ds["captured_data"]["Container EUID"] = container.euid
    action_ds["captured_data"]["assay_selection"] = assay.euid

    bobj.do_action(
        tri.euid,
        action=action_name,
        action_group=action_group,
        action_ds=action_ds,
    )
    assay = bobj.get_by_euid(assay.euid)
    queue_steps = [
        lin.child_instance
        for lin in assay.parent_of_lineages
        if (
            not lin.is_deleted
            and lin.child_instance.category == "workflow_step"
            and lin.child_instance.type == "queue"
            and not lin.child_instance.is_deleted
        )
    ]
    assert queue_steps, "Fallback queue step should be linked under selected assay workflow"

    queued_step = None
    for step in queue_steps:
        if any(
            not lin.is_deleted and lin.child_instance.euid == container.euid
            for lin in step.parent_of_lineages
        ):
            queued_step = step
            break

    assert queued_step is not None, "Container should be linked into fallback queue step"
    assert str(queued_step.json_addl.get("properties", {}).get("step_number", "")) == "1"


def test_assay_templates_define_extraction_pipeline_layout(bdb_function):
    project_root = Path(__file__).resolve().parent.parent
    assay_config = json.loads(
        (project_root / "bloom_lims/config/workflow/assay.json").read_text(encoding="utf-8")
    )
    expected_subtypes = [
        "extraction-batch-eligible",
        "blood-to-gdna-extraction-eligible",
        "buccal-to-gdna-extraction-eligible",
        "input-gdna-normalization-eligible",
        "illumina-novaseq-libprep-eligible",
        "ont-libprep-eligible",
    ]

    for assay_subtype, assay_version in (("hla-typing", "1.2"), ("carrier-screen", "3.9")):
        assay_def = assay_config[assay_subtype][assay_version]
        layout = assay_def.get("instantiation_layouts", [[]])[0]
        queue_subtypes = []
        for entry in layout:
            key = list(entry.keys())[0]
            parts = key.strip("/").split("/")
            if len(parts) >= 4 and parts[0] == "workflow_step" and parts[1] == "queue":
                queue_subtypes.append(parts[2])

        assert queue_subtypes[: len(expected_subtypes)] == expected_subtypes
        props = assay_def.get("properties", {})
        assert props.get("library_prep_queue_subtypes") == [
            "illumina-novaseq-libprep-eligible",
            "ont-libprep-eligible",
        ]


def test_add_specimen_routes_to_extraction_batch_queue(bdb_function):
    bobj = BloomWorkflowStep(bdb_function)
    _require_queue_template_or_skip(bobj, "extraction-batch-eligible")
    tri = _get_or_create_test_requisition_with_assay_action(bobj)
    assay = _get_assay_instance(bobj, "hla-typing", "1.2")

    container_templates = bobj.query_template_by_component_v2(
        category="container",
        type="tube",
    )
    if not container_templates:
        pytest.skip("Missing container/tube template for assay queue routing test")
    container = bobj.create_instances(container_templates[0].euid)[0][0]
    bobj.create_generic_instance_lineage_by_euids(tri.euid, container.euid)
    bobj.session.commit()

    action_group, action_name, action_ds = _find_action_by_method(
        tri, "do_action_add_container_to_assay_q"
    )
    action_ds.setdefault("captured_data", {})
    action_ds["captured_data"]["Container EUID"] = container.euid
    action_ds["captured_data"]["assay_selection"] = assay.euid

    bobj.do_action(
        tri.euid,
        action=action_name,
        action_group=action_group,
        action_ds=action_ds,
    )
    assay = bobj.get_by_euid(assay.euid)
    queued_step = _get_active_queue_step_by_subtype(assay, "extraction-batch-eligible")
    assert queued_step is not None
    assert any(
        not lin.is_deleted and lin.child_instance.euid == container.euid
        for lin in queued_step.parent_of_lineages
    )


def test_queue_move_plate_fill_quant_and_fanout(bdb_function):
    bobj = BloomWorkflowStep(bdb_function)
    _require_queue_template_or_skip(bobj, "extraction-batch-eligible")
    _require_queue_template_or_skip(bobj, "blood-to-gdna-extraction-eligible")
    _require_queue_template_or_skip(bobj, "input-gdna-normalization-eligible")
    _require_queue_template_or_skip(bobj, "illumina-novaseq-libprep-eligible")
    _require_queue_template_or_skip(bobj, "ont-libprep-eligible")
    tri = _get_or_create_test_requisition_with_assay_action(bobj)
    assay = _get_assay_instance(bobj, "carrier-screen", "3.9")

    tube_templates = bobj.query_template_by_component_v2(category="container", type="tube")
    specimen_templates = bobj.query_template_by_component_v2(
        category="content", type="specimen", subtype="blood-whole", version="1.0"
    )
    if not tube_templates or not specimen_templates:
        pytest.skip("Missing required tube/specimen templates for assay extraction pipeline test")

    tube = bobj.create_instances(tube_templates[0].euid)[0][0]
    specimen = bobj.create_instances(specimen_templates[0].euid)[0][0]
    bobj.create_generic_instance_lineage_by_euids(tube.euid, specimen.euid)
    bobj.create_generic_instance_lineage_by_euids(tri.euid, tube.euid)
    bobj.session.commit()

    add_group, add_action, add_ds = _find_action_by_method(tri, "do_action_add_container_to_assay_q")
    add_ds.setdefault("captured_data", {})
    add_ds["captured_data"]["Container EUID"] = tube.euid
    add_ds["captured_data"]["assay_selection"] = assay.euid
    bobj.do_action(
        tri.euid, action=add_action, action_group=add_group, action_ds=add_ds
    )
    assay = bobj.get_by_euid(assay.euid)
    extraction_queue = _get_active_queue_step_by_subtype(assay, "extraction-batch-eligible")
    assert extraction_queue is not None
    assert extraction_queue.subtype == "extraction-batch-eligible"

    move_group, move_action, move_ds = _find_action(
        extraction_queue,
        method_name="do_action_move_instances_to_queue",
        action_display_name="Add to Blood to gDNA Extraction Queue",
    )
    move_ds.setdefault("captured_data", {})
    move_ds["captured_data"]["instance_refs"] = tube.euid
    blood_queue = bobj.do_action(
        extraction_queue.euid,
        action=move_action,
        action_group=move_group,
        action_ds=move_ds,
    )
    blood_queue = bobj.get_by_euid(blood_queue.euid)
    assert blood_queue.subtype == "blood-to-gdna-extraction-eligible"
    assert any(
        lin.is_deleted and lin.parent_instance.euid == extraction_queue.euid
        for lin in tube.child_of_lineages
    )
    assert any(
        not lin.is_deleted and lin.parent_instance.euid == blood_queue.euid
        for lin in tube.child_of_lineages
    )

    to_norm_group, to_norm_action, to_norm_ds = _find_action(
        blood_queue,
        method_name="do_action_move_instances_to_queue",
        action_display_name="Add gDNA to gDNA Normalization Queue",
    )
    to_norm_ds.setdefault("captured_data", {})
    to_norm_ds["captured_data"]["instance_refs"] = tube.euid
    norm_queue = bobj.do_action(
        blood_queue.euid,
        action=to_norm_action,
        action_group=to_norm_group,
        action_ds=to_norm_ds,
    )
    norm_queue = bobj.get_by_euid(norm_queue.euid)
    assert norm_queue.subtype == "input-gdna-normalization-eligible"

    plate_group, plate_action, plate_ds = _find_action(
        norm_queue, method_name="do_action_plate_create_fill_auto"
    )
    plate_ds.setdefault("captured_data", {})
    plate_ds["captured_data"]["instance_refs"] = tube.euid
    created_plate = bobj.do_action(
        norm_queue.euid,
        action=plate_action,
        action_group=plate_group,
        action_ds=plate_ds,
    )
    created_plate = bobj.get_by_euid(created_plate.euid)
    assert created_plate.type == "plate"
    assert created_plate.subtype == "fixed-plate-96"

    linked_wells = []
    for lin in tube.parent_of_lineages:
        if lin.is_deleted:
            continue
        child = lin.child_instance
        if child.type != "well":
            continue
        if any(
            not wl.is_deleted and wl.parent_instance.euid == created_plate.euid
            for wl in child.child_of_lineages
        ):
            linked_wells.append(child)
    assert linked_wells, "Expected at least one destination well linked from source tube"
    target_well = linked_wells[0]
    well_address = target_well.json_addl.get("cont_address", {}).get("name", "")
    assert well_address

    quant_group, quant_action, quant_ds = _find_action(
        norm_queue, method_name="do_action_save_quant_data"
    )
    quant_ds.setdefault("captured_data", {})
    quant_ds["captured_data"]["quant_csv_text"] = f"{created_plate.euid},{well_address},4.2"
    bobj.do_action(
        norm_queue.euid,
        action=quant_action,
        action_group=quant_group,
        action_ds=quant_ds,
    )

    refreshed_well = bobj.get_by_euid(target_well.euid)
    assert float(refreshed_well.json_addl.get("properties", {}).get("quant_value")) == pytest.approx(4.2)

    assay = bobj.get_by_euid(assay.euid)
    illumina_q = _get_active_queue_step_by_subtype(assay, "illumina-novaseq-libprep-eligible")
    ont_q = _get_active_queue_step_by_subtype(assay, "ont-libprep-eligible")
    assert illumina_q is not None
    assert ont_q is not None
    assert any(
        not lin.is_deleted and lin.parent_instance.euid == illumina_q.euid
        for lin in refreshed_well.child_of_lineages
    )
    assert any(
        not lin.is_deleted and lin.parent_instance.euid == ont_q.euid
        for lin in refreshed_well.child_of_lineages
    )
