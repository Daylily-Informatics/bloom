#!/usr/bin/env python3
"""Migrate legacy action_template.captured_data HTML snippets to ui_schema fields."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

ACTION_DIR = Path("bloom_lims/config/action")

NAME_RE = re.compile(r"name\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
TYPE_RE = re.compile(r"type\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
VALUE_RE = re.compile(r"value\s*=\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
ROWS_RE = re.compile(r"rows\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
ACCEPT_RE = re.compile(r"accept\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
OPTION_RE = re.compile(
    r"<option[^>]*value\s*=\s*['\"]([^'\"]*)['\"][^>]*>(.*?)</option>",
    re.IGNORECASE | re.DOTALL,
)
SELECT_OPEN_RE = re.compile(r"<select[^>]*>", re.IGNORECASE)


def _clean_label(raw: str, fallback: str) -> str:
    if not raw:
        return fallback
    text = raw.strip().strip(":").strip()
    return text or fallback


def _parse_markup_field(key: str, markup_value: str) -> dict[str, Any]:
    decoded = html.unescape(markup_value or "")
    lower = decoded.lower()

    name_match = NAME_RE.search(decoded)
    field_name = (name_match.group(1).strip() if name_match else "") or key.lstrip("_")

    label_raw = decoded.split("<", 1)[0]
    label = _clean_label(label_raw, field_name)

    field_type = "text"
    if "<textarea" in lower:
        field_type = "textarea"
    elif "<select" in lower:
        field_type = "select"
    elif "<input" in lower:
        type_match = TYPE_RE.search(decoded)
        field_type = (type_match.group(1).strip().lower() if type_match else "text") or "text"

    field: dict[str, Any] = {
        "name": field_name,
        "label": label,
        "type": field_type,
        "required": "required" in lower,
    }

    if field_type == "textarea":
        rows_match = ROWS_RE.search(decoded)
        if rows_match:
            try:
                field["rows"] = int(rows_match.group(1))
            except ValueError:
                pass
    elif field_type == "select":
        options: list[dict[str, str]] = []
        for value, option_label in OPTION_RE.findall(decoded):
            clean_option_label = re.sub(r"<[^>]+>", "", option_label).strip()
            options.append({"value": html.unescape(value), "label": html.unescape(clean_option_label)})

        if field_name == "assay_selection" or "___workflow/assay/" in key:
            field["options_source"] = "workflow_assays"

        if options:
            field["options"] = options
    elif field_type == "file":
        accept_match = ACCEPT_RE.search(decoded)
        if accept_match:
            field["accept"] = accept_match.group(1)
    else:
        value_match = VALUE_RE.search(decoded)
        if value_match:
            field["default"] = html.unescape(value_match.group(1))

    return field


def _parse_simple_field(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, str) and "<" in value and ">" in value:
        return _parse_markup_field(key, value)

    field: dict[str, Any] = {
        "name": key,
        "label": key,
        "type": "text",
        "required": False,
    }

    if isinstance(value, list):
        field["type"] = "textarea"
        field["default"] = "\n".join(str(v) for v in value)
        field["rows"] = max(4, min(20, len(value) + 1))
    elif isinstance(value, (int, float)):
        field["type"] = "number"
        field["default"] = value
    elif isinstance(value, str):
        field["default"] = value

    if key == "assay_selection":
        field["options_source"] = "workflow_assays"

    return field


def _migrate_action_template(action_template: dict[str, Any]) -> bool:
    captured_data = action_template.get("captured_data")
    if not isinstance(captured_data, dict):
        captured_data = {}

    ui_schema = action_template.get("ui_schema")
    has_schema_fields = isinstance(ui_schema, dict) and isinstance(ui_schema.get("fields"), list)
    has_legacy_markup = any(
        (isinstance(key, str) and key.startswith("_"))
        or (isinstance(value, str) and ("<input" in value or "<select" in value or "<textarea" in value))
        for key, value in captured_data.items()
    )
    if has_schema_fields and not captured_data:
        return False
    if has_schema_fields and not has_legacy_markup and len(captured_data) == 0:
        return False

    fields: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for key, value in captured_data.items():
        if isinstance(key, str) and key.startswith("_"):
            field = _parse_markup_field(key, str(value))
        else:
            field = _parse_simple_field(str(key), value)

        name = str(field.get("name", "")).strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        fields.append(field)

    ui_schema = {
        "title": action_template.get("action_name", "Action"),
        "fields": fields,
    }

    action_template["ui_schema"] = ui_schema
    action_template["captured_data"] = {}
    if fields:
        action_template["capture_data"] = "yes"
    return True


def _migrate_structure(node: Any) -> int:
    changes = 0
    if isinstance(node, dict):
        if isinstance(node.get("action_template"), dict):
            if _migrate_action_template(node["action_template"]):
                changes += 1
        for child in node.values():
            changes += _migrate_structure(child)
    elif isinstance(node, list):
        for child in node:
            changes += _migrate_structure(child)
    return changes


def migrate_action_file(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    changes = _migrate_structure(payload)
    if changes:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="check mode: fail if migration is needed")
    args = parser.parse_args()

    total_files = 0
    total_actions = 0

    for path in sorted(ACTION_DIR.glob("*.json")):
        total_files += 1
        changes = migrate_action_file(path)
        total_actions += changes

    if args.check and total_actions:
        print(f"Migration needed for {total_actions} action templates across {total_files} files")
        return 1

    print(f"Migrated {total_actions} action templates across {total_files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
