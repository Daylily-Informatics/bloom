from __future__ import annotations

import copy

from bloom_lims.bobjs import BloomObj


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
                "type": "text",
                "required": True,
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
        for action_data in actions.values():
            if not isinstance(action_data, dict):
                continue
            captured = action_data.get("captured_data")
            if not isinstance(captured, dict):
                captured = {}
                action_data["captured_data"] = captured

            ui_schema = action_data.get("ui_schema")
            if not isinstance(ui_schema, dict):
                ui_schema = {"title": str(action_data.get("action_name") or "Action"), "fields": []}
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
