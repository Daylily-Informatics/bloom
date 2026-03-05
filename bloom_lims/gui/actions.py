from __future__ import annotations

import copy
from html import escape as html_escape

from bloom_lims.bobjs import BloomObj


def _build_assay_selection_options(bobdb: BloomObj) -> list[dict]:
    """Build assay options from live workflow/assay instances."""
    assay_workflows = bobdb.query_instance_by_component_v2(category="workflow", type="assay")
    assay_workflows = [wf for wf in assay_workflows if not getattr(wf, "is_deleted", False)]
    assay_workflows.sort(
        key=lambda wf: (
            str(getattr(wf, "subtype", "") or "").lower(),
            str(getattr(wf, "version", "") or ""),
            str(getattr(wf, "name", "") or "").lower(),
            str(getattr(wf, "euid", "") or ""),
        )
    )

    options = []
    for wf in assay_workflows:
        props = wf.json_addl.get("properties", {}) if isinstance(wf.json_addl, dict) else {}
        display_name = (props.get("name") if isinstance(props, dict) else None) or wf.name or wf.subtype or wf.euid
        label = f"{display_name} ({wf.subtype} v{wf.version}) [{wf.euid}]"
        options.append({"value": str(wf.euid), "label": str(label)})

    return options


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
            captured = action_data.get("captured_data", {})
            if isinstance(captured, dict) and "___workflow/assay/" in captured:
                if assay_selection_options is None:
                    assay_selection_options = _build_assay_selection_options(bobdb)
                if assay_selection_html is None:
                    assay_selection_html = _build_assay_selection_html(assay_selection_options)
                captured["___workflow/assay/"] = assay_selection_html

            ui_schema = action_data.get("ui_schema")
            fields = ui_schema.get("fields") if isinstance(ui_schema, dict) else None
            if not isinstance(fields, list):
                continue
            for field in fields:
                if not isinstance(field, dict):
                    continue
                if field.get("options_source") == "workflow_assays":
                    if assay_selection_options is None:
                        assay_selection_options = _build_assay_selection_options(bobdb)
                    field["options"] = copy.deepcopy(assay_selection_options)

    return hydrated

