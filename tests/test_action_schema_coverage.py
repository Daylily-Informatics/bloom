"""Schema coverage guard for action templates."""

from __future__ import annotations

import json
from pathlib import Path

ACTION_DIR = Path("bloom_lims/config/action")


def _iter_action_templates():
    for path in sorted(ACTION_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for action_name, versions in payload.items():
            if not isinstance(versions, dict):
                continue
            for version, data in versions.items():
                if not isinstance(data, dict):
                    continue
                action_template = data.get("action_template")
                if isinstance(action_template, dict):
                    yield path, action_name, version, action_template


def test_every_action_template_has_ui_schema_fields():
    missing = []
    for path, action_name, version, action_template in _iter_action_templates():
        ui_schema = action_template.get("ui_schema")
        fields = ui_schema.get("fields") if isinstance(ui_schema, dict) else None
        if not isinstance(fields, list):
            missing.append(f"{path}:{action_name}:{version}: missing ui_schema.fields")
            continue

        capture_mode = str(action_template.get("capture_data") or "").strip().lower()
        if capture_mode == "yes" and len(fields) == 0:
            missing.append(f"{path}:{action_name}:{version}: capture_data=yes requires non-empty ui_schema.fields")
            continue

        for idx, field in enumerate(fields):
            if not isinstance(field, dict):
                missing.append(f"{path}:{action_name}:{version}: field[{idx}] is not an object")
                continue
            for key in ("name", "type", "required"):
                if key not in field:
                    missing.append(f"{path}:{action_name}:{version}: field[{idx}] missing '{key}'")

    assert not missing, "\n".join(missing)


def test_no_legacy_html_captured_data_fields_remain():
    offenders = []
    for path, action_name, version, action_template in _iter_action_templates():
        captured_data = action_template.get("captured_data")
        if not isinstance(captured_data, dict):
            continue

        for key, value in captured_data.items():
            if isinstance(key, str) and key.startswith("_"):
                offenders.append(f"{path}:{action_name}:{version}: legacy captured_data key '{key}'")
            if isinstance(value, str) and ("<input" in value or "<select" in value or "<textarea" in value):
                offenders.append(f"{path}:{action_name}:{version}: legacy HTML markup still present")

    assert not offenders, "\n".join(offenders)
