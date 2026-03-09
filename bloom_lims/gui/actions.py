from __future__ import annotations

import copy
from html import escape as html_escape

from bloom_lims.bobjs import BloomObj


def _build_assay_selection_options(_bobdb: BloomObj) -> list[dict]:
    """Workflow-backed assay selection is retired in queue-centric Bloom beta."""
    return []


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


def _build_assay_selection_html(options: list[dict]) -> str:
    rendered_options = []
    for option in options:
        option_value = html_escape(str(option.get("value", "")), quote=True)
        option_label = html_escape(str(option.get("label", "")))
        rendered_options.append(f'<option value="{option_value}">{option_label}</option>')

    if not rendered_options:
        rendered_options.append('<option value="" disabled selected>No assay workflows available</option>')

    return '<select name="assay_selection" required>' + "".join(rendered_options) + "</select>"


def hydrate_dynamic_action_groups(action_groups: dict, bobdb: BloomObj) -> dict:
    """Hydrate dynamic UI bits inside action groups (assay dropdown, etc)."""
    if not isinstance(action_groups, dict):
        return {}

    hydrated = copy.deepcopy(action_groups)
    assay_selection_options = None
    assay_selection_html = None

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

            if isinstance(captured, dict) and "___workflow/assay/" in captured:
                if assay_selection_options is None:
                    assay_selection_options = _build_assay_selection_options(bobdb)
                if assay_selection_html is None:
                    assay_selection_html = _build_assay_selection_html(assay_selection_options)
                captured["___workflow/assay/"] = assay_selection_html

            for field in fields:
                if not isinstance(field, dict):
                    continue
                if field.get("options_source") == "workflow_assays":
                    if assay_selection_options is None:
                        assay_selection_options = _build_assay_selection_options(bobdb)
                    if assay_selection_html is None:
                        assay_selection_html = _build_assay_selection_html(assay_selection_options)
                    field["options"] = copy.deepcopy(assay_selection_options)
                    if field.get("name") == "assay_selection":
                        captured.setdefault("___workflow/assay/", assay_selection_html)

    return hydrated
