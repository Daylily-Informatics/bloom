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
    candidates = []
    for lin in workflow_obj.parent_of_lineages:
        child = lin.child_instance
        if lin.is_deleted:
            continue
        if child is None or child.is_deleted:
            continue
        if child.category == "workflow_step" and child.type == "queue" and child.subtype == subtype:
            candidates.append(child)

    if not candidates:
        return None

    def _sort_key(step_obj):
        props = step_obj.json_addl.get("properties", {}) if isinstance(step_obj.json_addl, dict) else {}
        step_number = props.get("step_number")
        try:
            order = int(step_number)
        except (TypeError, ValueError):
            order = 10**9
        return (order, str(step_obj.euid))

    candidates.sort(key=_sort_key)
    return candidates[0]


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


def test_workflow_details_renders_descendant_category_chips(bdb_function):
    bwf = BloomWorkflow(bdb_function)
    workflow = _get_accessioning_assay_workflow(bwf)
    _run_register_package_action(bwf, workflow)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/workflow_details?workflow_euid={workflow.euid}")
    assert response.status_code == 200
    assert "descendant-chip" in response.text
    assert "chip-label\">total" in response.text
    assert 'data-child-category="container"' in response.text
    container_icon_chip = re.compile(
        r'data-child-category="container"[^>]*>.*?fa-box',
        re.S,
    )
    assert container_icon_chip.search(response.text)


def test_workflow_details_descendant_chips_include_recursive_counts(bdb_function):
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

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/workflow_details?workflow_euid={workflow.euid}")
    assert response.status_code == 200

    # The parent queue step summary should include recursive tube descendants
    # in the type breakdown tooltip.
    parent_step_recursive_tube_summary = re.compile(
        rf'id="accordion-{re.escape(created_step.euid)}".*?title="[^"]*tube:\s*[0-9]+',
        re.S,
    )
    assert parent_step_recursive_tube_summary.search(response.text)

    # Parent queue total descendants should be >= child step total descendants.
    parent_total_match = re.search(
        rf'id="accordion-{re.escape(created_step.euid)}".*?descendant-chip total.*?<span class="chip-count">(\d+)</span>',
        response.text,
        re.S,
    )
    child_total_match = re.search(
        rf'id="accordion-{re.escape(child_step.euid)}".*?descendant-chip total.*?<span class="chip-count">(\d+)</span>',
        response.text,
        re.S,
    )
    assert parent_total_match and child_total_match
    assert int(parent_total_match.group(1)) >= int(child_total_match.group(1))


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
