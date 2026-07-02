from __future__ import annotations

import copy

from bloom_lims.domain import BloomObj

RELATIONSHIP_TYPE_OPTIONS = [
    {"value": "contains", "label": "contains"},
    {"value": "derived_from", "label": "derived_from"},
    {"value": "aliquot_of", "label": "aliquot_of"},
    {"value": "prepared_from", "label": "prepared_from"},
    {"value": "member_of", "label": "member_of"},
    {"value": "has_external_reference", "label": "has_external_reference"},
    {"value": "beta_extraction_batch_run", "label": "beta_extraction_batch_run"},
    {"value": "beta_extraction_run_input", "label": "beta_extraction_run_input"},
    {"value": "beta_extraction_plate", "label": "beta_extraction_plate"},
    {"value": "beta_extraction_well", "label": "beta_extraction_well"},
    {"value": "beta_extraction_output", "label": "beta_extraction_output"},
    {"value": "beta_extraction_run_output", "label": "beta_extraction_run_output"},
    {"value": "beta_post_extract_qc", "label": "beta_post_extract_qc"},
    {"value": "beta_library_prep_output", "label": "beta_library_prep_output"},
    {"value": "beta_library_material_output", "label": "beta_library_material_output"},
    {"value": "beta_library_qc", "label": "beta_library_qc"},
    {"value": "beta_pooling_run_output", "label": "beta_pooling_run_output"},
    {"value": "beta_pool_member", "label": "beta_pool_member"},
    {"value": "beta_pooling_run_input", "label": "beta_pooling_run_input"},
    {"value": "beta_sequencing_run", "label": "beta_sequencing_run"},
    {
        "value": "beta_sequenced_library_assignment",
        "label": "beta_sequenced_library_assignment",
    },
    {"value": "beta_assignment_source", "label": "beta_assignment_source"},
    {
        "value": "beta_assignment_library_material",
        "label": "beta_assignment_library_material",
    },
    {
        "value": "beta_assignment_barcode_reagent",
        "label": "beta_assignment_barcode_reagent",
    },
    {"value": "beta_run_artifact", "label": "beta_run_artifact"},
]


def _normalize_action_slug(action_data: dict) -> str:
    method_name = str(action_data.get("method_name") or "").strip()
    if method_name.startswith("do_action_"):
        return method_name.removeprefix("do_action_")
    return ""


def _default_ui_fields_for_action(action_data: dict) -> list[dict]:
    slug = _normalize_action_slug(action_data).replace("-", "_")
    if slug == "set_object_status":
        return [
            {
                "name": "object_status",
                "label": "New Status",
                "type": "select",
                "required": True,
                "options": [
                    {"value": "queued", "label": "queued"},
                    {"value": "ready", "label": "ready"},
                    {"value": "in_progress", "label": "in_progress"},
                    {"value": "complete", "label": "complete"},
                    {"value": "failed", "label": "failed"},
                    {"value": "abandoned", "label": "abandoned"},
                ],
            }
        ]
    if slug == "add_relationships":
        return [
            {
                "name": "lineage_type_to_create",
                "label": "Create Relationship As",
                "type": "select",
                "required": True,
                "options": [
                    {"value": "parent", "label": "parent"},
                    {"value": "child", "label": "child"},
                ],
            },
            {
                "name": "relationship_type",
                "label": "Relationship Type",
                "type": "select",
                "required": True,
                "options": RELATIONSHIP_TYPE_OPTIONS,
            },
            {
                "name": "euids",
                "label": "EUIDs (one per line)",
                "type": "textarea",
                "required": True,
                "rows": 6,
            },
        ]
    return []


def hydrate_dynamic_action_groups(action_groups: dict, bobdb: BloomObj) -> dict:
    """Hydrate dynamic UI bits for active action surfaces only."""
    del bobdb  # Legacy assay/workflow hydration is retired.
    if not isinstance(action_groups, dict):
        return {}

    hydrated = copy.deepcopy(action_groups)

    for group_data in hydrated.values():
        if not isinstance(group_data, dict):
            continue
        actions = group_data.get("actions", {})
        if not isinstance(actions, dict):
            continue
        for action_key, action_data in list(actions.items()):
            if not isinstance(action_data, dict):
                continue
            if (
                action_data.get("action_visible") == "0"
                or _normalize_action_slug(action_data) == "create_subject_and_anchor"
            ):
                actions.pop(action_key, None)
                continue
            captured = action_data.get("captured_data")
            if not isinstance(captured, dict):
                captured = {}
                action_data["captured_data"] = captured

            ui_schema = action_data.get("ui_schema")
            if not isinstance(ui_schema, dict):
                ui_schema = {
                    "title": str(action_data.get("action_name") or "Action"),
                    "fields": [],
                }
                action_data["ui_schema"] = ui_schema
            fields = ui_schema.get("fields")
            if not isinstance(fields, list):
                fields = []
                ui_schema["fields"] = fields

            if action_data.get("capture_data") == "yes" and not fields:
                default_fields = _default_ui_fields_for_action(action_data)
                if default_fields:
                    ui_schema["fields"] = copy.deepcopy(default_fields)
                    fields = ui_schema["fields"]

            # Hard-cut: remove retired assay/workflow-assay capture/UI selectors.
            captured.pop("___workflow/assay/", None)
            ui_schema["fields"] = [
                field
                for field in fields
                if isinstance(field, dict)
                and field.get("options_source") != "workflow_assays"
                and field.get("name") != "assay_selection"
            ]

    return hydrated
