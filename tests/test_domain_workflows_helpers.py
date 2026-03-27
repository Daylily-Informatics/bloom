from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skip(reason="Workflow helper surface is retired in queue-centric Bloom beta.")

import bloom_lims.domain.workflows as workflows_mod
from bloom_lims.domain.workflows import BloomWorkflowStep


def _subject() -> BloomWorkflowStep:
    return BloomWorkflowStep.__new__(BloomWorkflowStep)


def _lineage(child, *, is_deleted: bool = False, parent=None):
    return SimpleNamespace(
        child_instance=child,
        parent_instance=parent,
        is_deleted=is_deleted,
    )


def _obj(
    euid: str,
    *,
    category: str = "workflow_step",
    type_name: str = "queue",
    subtype: str = "queue-subtype",
    is_deleted: bool = False,
    step_number: str | None = None,
    cont_address: dict | None = None,
):
    json_addl = {"properties": {}}
    if step_number is not None:
        json_addl["properties"]["step_number"] = step_number
    if cont_address is not None:
        json_addl["cont_address"] = cont_address
    return SimpleNamespace(
        euid=euid,
        category=category,
        type=type_name,
        subtype=subtype,
        is_deleted=is_deleted,
        json_addl=json_addl,
        parent_of_lineages=[],
        child_of_lineages=[],
    )


def test_step_sort_key_handles_numeric_and_invalid_values():
    s = _subject()
    assert s._step_sort_key(_obj("A", step_number="2")) == (2, "A")
    assert s._step_sort_key(_obj("B", step_number="not-int")) == (10**9, "B")


def test_iter_active_child_instances_filters_deleted_and_type():
    s = _subject()
    keep = _obj("KEEP", category="container", type_name="well")
    deleted_lineage = _obj("DEL-LIN", category="container", type_name="well")
    deleted_child = _obj("DEL-CHILD", category="container", type_name="well", is_deleted=True)
    wrong_type = _obj("WRONG", category="container", type_name="plate")
    parent = SimpleNamespace(
        parent_of_lineages=[
            _lineage(keep),
            _lineage(deleted_lineage, is_deleted=True),
            _lineage(deleted_child),
            _lineage(wrong_type),
        ]
    )
    found = list(s._iter_active_child_instances(parent, category="container", type_name="well"))
    assert [child.euid for _, child in found] == ["KEEP"]


def test_get_parent_workflow_for_step_returns_workflow_and_raises_when_missing():
    s = _subject()
    wf = _obj("WF1", category="workflow", type_name="run", subtype="x")
    not_wf = _obj("NW1", category="container", type_name="plate", subtype="x")
    step = _obj("STEP1")
    step.child_of_lineages = [_lineage(not_wf, parent=not_wf), _lineage(wf, parent=wf)]
    assert s._get_parent_workflow_for_step(step).euid == "WF1"

    step_missing = _obj("STEP2")
    step_missing.child_of_lineages = [_lineage(not_wf, parent=not_wf)]
    with pytest.raises(Exception, match="Could not determine parent workflow"):
        s._get_parent_workflow_for_step(step_missing)


def test_get_workflow_steps_sorts_by_step_number():
    s = _subject()
    st3 = _obj("S3", step_number="3")
    st1 = _obj("S1", step_number="1")
    st_invalid = _obj("SZ", step_number="x")
    workflow = SimpleNamespace(
        parent_of_lineages=[
            _lineage(st3),
            _lineage(st1),
            _lineage(st_invalid),
        ]
    )
    steps = s._get_workflow_steps(workflow)
    assert [item.euid for item in steps] == ["S1", "S3", "SZ"]


def test_default_queue_name_handles_special_tokens():
    s = _subject()
    assert s._default_queue_name("input-gdna-normalization-eligible") == "Input gDNA Normalization Eligible"
    assert s._default_queue_name("ont-novaseq-libprep") == "ONT Novaseq LibPrep"


def test_parse_instance_refs_merges_keys_and_deduplicates():
    s = _subject()
    action_ds = {
        "captured_data": {
            "instance_refs": "A1\nA2",
            "instance_refs_file_text": ["A2", "A3"],
            "instance_refs_file": "A4;A4",
        }
    }
    assert s._parse_instance_refs(action_ds) == ["A1", "A2", "A3", "A4"]

    with pytest.raises(Exception, match="No instance refs"):
        s._parse_instance_refs({"captured_data": {}})


def test_resolve_well_by_plate_and_address_success_and_failures():
    s = _subject()
    plate = _obj("PLATE1", category="container", type_name="plate")
    well_a1 = _obj(
        "WELL1",
        category="container",
        type_name="well",
        cont_address={"name": "A1"},
    )
    well_b1 = _obj(
        "WELL2",
        category="container",
        type_name="well",
        cont_address={"name": "B1"},
    )
    plate.parent_of_lineages = [_lineage(well_b1), _lineage(well_a1)]
    s.get_by_euid = lambda euid: plate if euid == "PLATE1" else None

    assert s._resolve_well_by_plate_and_address("PLATE1", "a1").euid == "WELL1"

    with pytest.raises(Exception, match="Could not resolve well"):
        s._resolve_well_by_plate_and_address("PLATE1", "C1")

    invalid_plate = _obj("BAD", category="content", type_name="sample")
    s.get_by_euid = lambda _euid: invalid_plate
    with pytest.raises(Exception, match="Invalid plate EUID"):
        s._resolve_well_by_plate_and_address("BAD", "A1")


def test_resolve_instance_reference_supports_plate_dot_well_and_direct():
    s = _subject()
    s._resolve_well_by_plate_and_address = lambda plate, addr: _obj(f"{plate}.{addr}")
    direct = _obj("CNT-1", category="container", type_name="tube")
    s.get_by_euid = lambda euid: direct if euid == "CNT-1" else None

    assert s._resolve_instance_reference("PLATE1.A1").euid == "PLATE1.A1"
    assert s._resolve_instance_reference("CNT-1").euid == "CNT-1"

    with pytest.raises(Exception, match="Could not resolve instance ref"):
        s._resolve_instance_reference("DOES-NOT-EXIST")


def test_content_helpers_cover_first_active_child_and_occupancy():
    s = _subject()
    content = _obj("MX1", category="content", type_name="sample")
    instance = SimpleNamespace(parent_of_lineages=[_lineage(content)])

    assert s._get_first_active_child_content(instance).euid == "MX1"
    assert s._is_well_occupied(instance) is True

    empty = SimpleNamespace(parent_of_lineages=[])
    assert s._get_first_active_child_content(empty) is None
    assert s._is_well_occupied(empty) is False


def test_get_plate_wells_in_address_order_and_destination_resolution():
    s = _subject()
    w2 = _obj("W2", category="container", type_name="well", cont_address={"row_idx": "2", "col_idx": "1"})
    w1 = _obj("W1", category="container", type_name="well", cont_address={"row_idx": "1", "col_idx": "2"})
    w0 = _obj("W0", category="container", type_name="well", cont_address={"row_idx": "1", "col_idx": "1"})
    plate = _obj("PLATE1", category="container", type_name="plate")
    plate.parent_of_lineages = [_lineage(w2), _lineage(w1), _lineage(w0)]

    ordered = s._get_plate_wells_in_address_order(plate)
    assert [well.euid for well in ordered] == ["W0", "W1", "W2"]

    s._resolve_well_by_plate_and_address = lambda plate_euid, addr: _obj(f"{plate_euid}.{addr}")
    assert s._resolve_destination_well_ref(plate, "B2").euid == "PLATE1.B2"
    assert s._resolve_destination_well_ref(plate, "PLATE1.A1").euid == "PLATE1.A1"
    with pytest.raises(Exception, match="does not target destination plate"):
        s._resolve_destination_well_ref(plate, "OTHER.A1")


def test_parse_mapping_rows_and_quant_rows_validation():
    s = _subject()
    mapping_ds = {
        "captured_data": {
            "mapping_csv_text": "source_ref,destination_ref\nPLATE1.A1,A1\nPLATE1.B1,B1\n"
        }
    }
    assert s._parse_mapping_rows(mapping_ds) == [("PLATE1.A1", "A1"), ("PLATE1.B1", "B1")]

    with pytest.raises(Exception, match="Invalid mapping row"):
        s._parse_mapping_rows({"captured_data": {"mapping_csv_text": "source_ref,destination_ref\nONLYSOURCE\n"}})

    quant_ds = {
        "captured_data": {
            "quant_csv_text": "plate_euid,well,quant\nPLATE1,A1,1.5\nPLATE1,B1,2.0\n"
        }
    }
    assert s._parse_quant_rows(quant_ds) == [("PLATE1", "A1", 1.5), ("PLATE1", "B1", 2.0)]

    with pytest.raises(Exception, match="Quant value must be float"):
        s._parse_quant_rows({"captured_data": {"quant_csv_text": "PLATE1,A1,not-a-float\n"}})


def test_get_library_prep_targets_from_properties_or_defaults():
    s = _subject()
    wf_with_list = _obj("WF1", category="workflow")
    wf_with_list.json_addl["properties"]["library_prep_queue_subtypes"] = [
        "illumina-novaseq-libprep-eligible",
        "ont-libprep-eligible",
    ]
    assert s._get_library_prep_targets(wf_with_list) == [
        "illumina-novaseq-libprep-eligible",
        "ont-libprep-eligible",
    ]

    wf_with_string = _obj("WF2", category="workflow")
    wf_with_string.json_addl["properties"]["library_prep_queue_subtypes"] = "ont-libprep-eligible"
    assert s._get_library_prep_targets(wf_with_string) == ["ont-libprep-eligible"]

    wf_default = _obj("WF3", category="workflow")
    assert s._get_library_prep_targets(wf_default) == [
        "illumina-novaseq-libprep-eligible",
        "ont-libprep-eligible",
    ]


def test_route_instances_to_library_prep_queues_links_each_instance():
    s = _subject()
    queue_step = _obj("Q1", category="workflow_step", subtype="extract")
    parent_workflow = _obj("WF1", category="workflow")
    calls: list[tuple[str, str]] = []
    created_steps = {
        "illumina-novaseq-libprep-eligible": _obj("Q-ILMN"),
        "ont-libprep-eligible": _obj("Q-ONT"),
    }

    s._get_parent_workflow_for_step = lambda _step: parent_workflow
    s._get_library_prep_targets = lambda _wf: list(created_steps.keys())
    s._get_or_create_queue_step = lambda _wf, subtype: created_steps[subtype]
    s._ensure_lineage = lambda parent, child: calls.append((parent, child))

    inst_a = _obj("CNT-A", category="container", type_name="tube")
    inst_b = _obj("CNT-B", category="container", type_name="tube")
    s._route_instances_to_library_prep_queues(queue_step, [inst_a, inst_b])

    assert calls == [
        ("Q-ILMN", "CNT-A"),
        ("Q-ILMN", "CNT-B"),
        ("Q-ONT", "CNT-A"),
        ("Q-ONT", "CNT-B"),
    ]


def test_get_or_create_queue_step_returns_existing_without_creation():
    s = _subject()
    existing = _obj("STEP-EXIST", category="workflow_step", subtype="target")
    s._get_workflow_steps = lambda _wf, subtype=None: [existing] if subtype == "target" else [existing]
    s.create_instance_by_code = lambda *_args, **_kwargs: _obj("STEP-NEW")
    s.create_generic_instance_lineage_by_euids = lambda *_args, **_kwargs: None
    s.session = SimpleNamespace(commit=lambda: None)
    workflow = _obj("WF1", category="workflow")
    assert s._get_or_create_queue_step(workflow, "target").euid == "STEP-EXIST"


def test_get_or_create_queue_step_creates_new_step_with_incremented_number():
    s = _subject()
    highest = _obj("STEP-HIGH", category="workflow_step", subtype="other", step_number="4")
    call_state = {"count": 0}

    def _get_steps(_wf, subtype=None):
        call_state["count"] += 1
        if subtype == "target-queue":
            return []
        return [highest]

    created = _obj("STEP-NEW", category="workflow_step", subtype="target-queue")
    captured = {"layout": "", "payload": None, "lineage": None}
    s._get_workflow_steps = _get_steps
    s.create_instance_by_code = (
        lambda layout, payload: captured.update({"layout": layout, "payload": payload}) or created
    )
    s.create_generic_instance_lineage_by_euids = (
        lambda parent, child: captured.update({"lineage": (parent, child)})
    )
    s.session = SimpleNamespace(commit=lambda: None)
    workflow = _obj("WF1", category="workflow")

    result = s._get_or_create_queue_step(workflow, "target-queue")
    assert result.euid == "STEP-NEW"
    assert captured["layout"] == "workflow_step/queue/target-queue/1.0"
    assert captured["payload"]["json_addl"]["properties"]["step_number"] == "5"
    assert captured["lineage"] == ("WF1", "STEP-NEW")


def test_ensure_lineage_skips_existing_and_creates_when_missing():
    s = _subject()
    existing_child = _obj("CHILD-1")
    parent = _obj("PARENT-1")
    parent.parent_of_lineages = [_lineage(existing_child)]
    created: list[tuple[str, str]] = []
    s.get_by_euid = lambda _euid: parent
    s.create_generic_instance_lineage_by_euids = lambda p, c: created.append((p, c))

    s._ensure_lineage("PARENT-1", "CHILD-1")
    assert created == []

    s._ensure_lineage("PARENT-1", "CHILD-2")
    assert created == [("PARENT-1", "CHILD-2")]


def test_fill_plate_from_sources_undirected_and_directed_error_paths():
    s = _subject()
    queue_step = _obj("Q1", category="workflow_step", subtype="input-gdna-normalization-eligible")
    plate = _obj("PLATE1", category="container", type_name="plate")
    source1 = _obj("SRC1", category="container", type_name="well")
    source2 = _obj("SRC2", category="container", type_name="well")
    dst1 = _obj("DST1", category="container", type_name="well")
    dst2 = _obj("DST2", category="container", type_name="well")
    src_content = _obj("MX1", category="content", type_name="sample")
    calls: list[tuple[str, str]] = []

    def _resolve(token):
        return {"A1": source1, "B1": source2}[token]

    s._resolve_instance_reference = _resolve
    s._get_plate_wells_in_address_order = lambda _plate: [dst1, dst2]
    s._is_well_occupied = lambda _well: False
    s._ensure_lineage = lambda parent, child: calls.append((parent, child))
    s._get_first_active_child_content = lambda _instance: src_content
    s._create_output_gdna_content = lambda normalized=False: _obj(
        f"OUT-{len(calls)}", category="content", type_name="sample"
    )

    s._fill_plate_from_sources(queue_step, plate, ["A1", "B1"])
    assert ("Q1", "PLATE1") in calls
    assert ("SRC1", "DST1") in calls
    assert ("SRC2", "DST2") in calls

    # Directed mapping path with occupied destination should raise.
    s._resolve_destination_well_ref = lambda _plate, _dest: dst1
    s._is_well_occupied = lambda _well: True
    with pytest.raises(Exception, match="Destination well already occupied"):
        s._fill_plate_from_sources(queue_step, plate, ["A1"], directed_mapping=[("A1", "A1")])


def test_fill_plate_from_sources_rejects_insufficient_wells():
    s = _subject()
    queue_step = _obj("Q1", category="workflow_step", subtype="extract")
    plate = _obj("PLATE1", category="container", type_name="plate")
    source1 = _obj("SRC1", category="container", type_name="well")
    source2 = _obj("SRC2", category="container", type_name="well")
    only_well = _obj("DST1", category="container", type_name="well")
    s._resolve_instance_reference = lambda token: {"A1": source1, "B1": source2}[token]
    s._get_plate_wells_in_address_order = lambda _plate: [only_well]
    s._is_well_occupied = lambda _well: False
    s._ensure_lineage = lambda *_args, **_kwargs: None
    s._get_first_active_child_content = lambda _instance: None
    s._create_output_gdna_content = lambda normalized=False: _obj("OUT", category="content", type_name="sample")

    with pytest.raises(Exception, match="Not enough available wells"):
        s._fill_plate_from_sources(queue_step, plate, ["A1", "B1"])


def test_create_output_gdna_content_sets_normalization_flags(monkeypatch):
    s = _subject()
    template = SimpleNamespace(euid="GT-1")
    content_obj = _obj("MX1", category="content", type_name="sample")
    touched: list[str] = []
    s.query_template_by_component_v2 = lambda *_args: [template]
    s.create_instances = lambda _template_euid: [[content_obj]]
    monkeypatch.setattr(workflows_mod, "flag_modified", lambda _obj, field: touched.append(field))

    out = s._create_output_gdna_content(normalized=True)
    assert out.euid == "MX1"
    assert out.json_addl["properties"]["normalized"] == "true"
    assert out.json_addl["properties"]["normalization_state"] == "normalized"
    assert touched == ["json_addl"]
