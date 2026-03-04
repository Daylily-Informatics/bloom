#!/usr/bin/env python3
"""
One-off codemod: canonicalize Bloom templates' `action_imports` to TapDB format.

Bloom legacy templates sometimes define `action_imports` in a grouped shape:

  {
    "core": {"group_order": "...", "group_name": "...", "actions": { ... }},
    ...
  }

TapDB's canonical format is a flat dict:

  {"create_note": "action/core/create-note/1.0", ...}

This script:
1) Converts all Bloom template JSON under bloom_lims/config/**.json to flat action_imports.
2) Expands wildcard imports like action/core/*/1.0/ into explicit mappings.
3) Preserves per-action overrides by generating new action template variants in
   bloom_lims/config/action/*.json and pointing imports at the variants.

Notes:
- Template codes are normalized to *no trailing slash*.
- For one known edge case (extraction-plate-filled importing set-child-object twice with
  differing overrides), we collapse to a single base import and drop overrides.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "bloom_lims" / "config"
ACTION_DIR = CONFIG_DIR / "action"

ACTION_IMPORT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _normalize_code(value: object) -> str:
    s = str(value).strip()
    if s.endswith("/"):
        s = s[:-1]
    return s


def _snake(value: object) -> str:
    s = str(value).strip().lower().replace("-", "_")
    # Tighten to [a-z0-9_] only for deterministic keys/names.
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """Merge src into dst recursively (mutates dst) and returns dst."""
    for k, v in src.items():
        if (
            k in dst
            and isinstance(dst[k], dict)
            and isinstance(v, dict)
        ):
            _deep_merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


@dataclass
class ActionTemplateIndex:
    by_code: Dict[str, Tuple[str, str, str]]  # code -> (type, subtype, version)
    by_type_version: Dict[Tuple[str, str], List[str]]  # (type, version) -> [code]
    files: Dict[str, Path]  # type -> json file
    data: Dict[str, Dict[str, Any]]  # type -> parsed json payload
    base_entry: Dict[str, Dict[str, Any]]  # code -> version entry (dict)


def _load_action_templates() -> ActionTemplateIndex:
    by_code: Dict[str, Tuple[str, str, str]] = {}
    by_type_version: Dict[Tuple[str, str], List[str]] = {}
    files: Dict[str, Path] = {}
    data: Dict[str, Dict[str, Any]] = {}
    base_entry: Dict[str, Dict[str, Any]] = {}

    for path in sorted(ACTION_DIR.glob("*.json")):
        action_type = path.stem
        files[action_type] = path
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid action template file (expected dict): {path}")
        data[action_type] = payload

        for subtype, versions in payload.items():
            if not isinstance(versions, dict):
                continue
            for version, entry in versions.items():
                code = f"action/{action_type}/{subtype}/{version}"
                by_code[code] = (action_type, str(subtype), str(version))
                by_type_version.setdefault((action_type, str(version)), []).append(code)
                if isinstance(entry, dict):
                    base_entry[code] = entry

    for codes in by_type_version.values():
        codes.sort()

    return ActionTemplateIndex(
        by_code=by_code,
        by_type_version=by_type_version,
        files=files,
        data=data,
        base_entry=base_entry,
    )


def _expand_action_ref(index: ActionTemplateIndex, action_ref: object) -> List[str]:
    code = _normalize_code(action_ref)
    parts = [p for p in code.split("/") if p]

    if len(parts) == 4 and parts[0] == "action" and parts[2] == "*":
        action_type = parts[1]
        version = parts[3]
        expanded = index.by_type_version.get((action_type, version), [])
        if not expanded:
            raise ValueError(f"Wildcard action import expanded to 0 templates: {code}")
        return expanded

    # Legacy malformed form observed in Bloom configs:
    #   action/{type}/{subtype}/*/{version}
    # Treat as an exact action/{type}/{subtype}/{version}.
    if len(parts) == 5 and parts[0] == "action" and parts[3] == "*":
        return [f"action/{parts[1]}/{parts[2]}/{parts[4]}"]

    if len(parts) == 4 and parts[0] == "action":
        return [code]

    raise ValueError(f"Unsupported action import reference: {action_ref!r}")


def _ensure_action_variant(
    index: ActionTemplateIndex,
    *,
    base_code: str,
    overrides: Dict[str, Any],
    context_template_subtype: str,
) -> str:
    base_code = _normalize_code(base_code)
    parts = base_code.split("/")
    if len(parts) != 4 or parts[0] != "action":
        raise ValueError(f"Invalid base action code: {base_code}")

    action_type, base_subtype, version = parts[1], parts[2], parts[3]
    if base_code not in index.base_entry:
        raise ValueError(f"Missing base action template for import: {base_code}")

    variant_subtype = f"{_snake(base_subtype)}__{_snake(context_template_subtype)}"
    variant_code = f"action/{action_type}/{variant_subtype}/{version}"

    payload = index.data.get(action_type)
    if payload is None:
        raise ValueError(f"Missing action template file for type '{action_type}'")

    base_version_entry = index.base_entry[base_code]
    if not isinstance(base_version_entry, dict) or "action_template" not in base_version_entry:
        raise ValueError(
            f"Action template {base_code} missing required 'action_template' block"
        )

    desired_entry = copy.deepcopy(base_version_entry)
    desired_action_template = copy.deepcopy(base_version_entry["action_template"])
    _deep_merge(desired_action_template, overrides)
    desired_entry["action_template"] = desired_action_template

    existing = payload.get(variant_subtype, {}).get(version)
    if existing is not None:
        if existing != desired_entry:
            raise ValueError(
                "Variant action template name collision with differing content: "
                f"{variant_code}"
            )
        return variant_code

    payload.setdefault(variant_subtype, {})[version] = desired_entry
    # Keep index updated for subsequent lookups/expansions.
    index.by_code[variant_code] = (action_type, variant_subtype, version)
    index.by_type_version.setdefault((action_type, version), []).append(variant_code)
    index.by_type_version[(action_type, version)].sort()
    index.base_entry[variant_code] = desired_entry

    return variant_code


def _convert_action_imports_value(
    index: ActionTemplateIndex,
    *,
    value: Any,
    context_template_subtype: str,
    containing_template_code: str,
) -> Dict[str, str]:
    if value is None:
        return {}

    if not isinstance(value, dict):
        raise ValueError(
            f"{containing_template_code}: action_imports must be dict, got {type(value)}"
        )

    # Already-flat form: {action_key: "action/type/subtype/version"}
    if all(isinstance(v, str) for v in value.values()):
        flat: Dict[str, str] = {}
        for k, v in value.items():
            action_key = str(k)
            if not ACTION_IMPORT_KEY_RE.match(action_key):
                raise ValueError(
                    f"{containing_template_code}: invalid action_imports key: {action_key!r}"
                )
            template_code = _normalize_code(v)
            if "*" in template_code:
                raise ValueError(
                    f"{containing_template_code}: wildcard not allowed in action_imports: {template_code}"
                )
            flat[action_key] = template_code
        return flat

    # Grouped legacy form: {group_name: {actions: {template_code: overrides}}}
    flat: Dict[str, str] = {}
    for group_name, group_data in value.items():
        if not isinstance(group_data, dict) or "actions" not in group_data:
            raise ValueError(
                f"{containing_template_code}: unexpected key under grouped action_imports: {group_name!r}"
            )

        actions = group_data.get("actions", {})
        if not isinstance(actions, dict):
            raise ValueError(
                f"{containing_template_code}: action group {group_name!r} actions must be dict"
            )

        for action_ref, overrides in actions.items():
            expanded_codes = _expand_action_ref(index, action_ref)
            ov = overrides if isinstance(overrides, dict) else {}

            for base_code in expanded_codes:
                base_code = _normalize_code(base_code)
                base_parts = base_code.split("/")
                if len(base_parts) != 4:
                    raise ValueError(
                        f"{containing_template_code}: invalid action code: {base_code}"
                    )
                base_subtype = base_parts[2]

                action_key = _snake(base_subtype)
                if not ACTION_IMPORT_KEY_RE.match(action_key):
                    raise ValueError(
                        f"{containing_template_code}: derived invalid action key: {action_key!r} "
                        f"from subtype {base_subtype!r}"
                    )

                # Special-case (decision-locked): extraction-plate-filled imports set-child-object
                # twice with different overrides. Collapse to a single base import (drop overrides).
                if (
                    base_code == "action/object/set-child-object/1.0"
                    and context_template_subtype == "extraction-plate-filled"
                ):
                    ov = {}

                template_code = base_code
                if ov:
                    template_code = _ensure_action_variant(
                        index,
                        base_code=base_code,
                        overrides=ov,
                        context_template_subtype=context_template_subtype,
                    )

                if action_key in flat and flat[action_key] != template_code:
                    raise ValueError(
                        f"{containing_template_code}: duplicate action_imports key {action_key!r} "
                        f"maps to both {flat[action_key]!r} and {template_code!r}"
                    )

                flat[action_key] = template_code

    return flat


def _walk_and_rewrite_action_imports(
    index: ActionTemplateIndex,
    obj: Any,
    *,
    context_template_subtype: str,
    containing_template_code: str,
) -> bool:
    """Recursively convert action_imports in-place. Returns True if modified."""
    changed = False

    if isinstance(obj, dict):
        # Fix a known legacy bug: json_addl nested inside action_imports by accident.
        # If present, lift it to be a sibling key on the containing object.
        if (
            "action_imports" in obj
            and isinstance(obj.get("action_imports"), dict)
            and isinstance(obj["action_imports"].get("json_addl"), dict)
            and "json_addl" not in obj
        ):
            obj["json_addl"] = obj["action_imports"].pop("json_addl")
            changed = True

        if "action_imports" in obj:
            new_value = _convert_action_imports_value(
                index,
                value=obj.get("action_imports"),
                context_template_subtype=context_template_subtype,
                containing_template_code=containing_template_code,
            )
            if obj.get("action_imports") != new_value:
                obj["action_imports"] = new_value
                changed = True

        for v in obj.values():
            if _walk_and_rewrite_action_imports(
                index,
                v,
                context_template_subtype=context_template_subtype,
                containing_template_code=containing_template_code,
            ):
                changed = True

    elif isinstance(obj, list):
        for v in obj:
            if _walk_and_rewrite_action_imports(
                index,
                v,
                context_template_subtype=context_template_subtype,
                containing_template_code=containing_template_code,
            ):
                changed = True

    return changed


def _scan_for_wildcards_in_action_imports(obj: Any) -> List[str]:
    """Returns list of offending action_imports values containing '*'."""
    hits: List[str] = []
    if isinstance(obj, dict):
        if "action_imports" in obj and isinstance(obj["action_imports"], dict):
            for v in obj["action_imports"].values():
                if isinstance(v, str) and "*" in v:
                    hits.append(v)
        for v in obj.values():
            hits.extend(_scan_for_wildcards_in_action_imports(v))
    elif isinstance(obj, list):
        for v in obj:
            hits.extend(_scan_for_wildcards_in_action_imports(v))
    return hits


def _write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    index = _load_action_templates()

    changed_template_files: List[Path] = []

    for path in sorted(CONFIG_DIR.rglob("*.json")):
        if path.name == "metadata.json":
            continue
        if ACTION_DIR in path.parents:
            # Action template files are updated separately via variant generation.
            continue

        category = path.parent.name
        type_name = path.stem

        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            continue

        file_changed = False
        for template_subtype, versions in payload.items():
            if not isinstance(versions, dict):
                continue
            for version, template_data in versions.items():
                if not isinstance(template_data, dict):
                    continue
                template_code = f"{category}/{type_name}/{template_subtype}/{version}"
                if _walk_and_rewrite_action_imports(
                    index,
                    template_data,
                    context_template_subtype=str(template_subtype),
                    containing_template_code=template_code,
                ):
                    file_changed = True

                wild = _scan_for_wildcards_in_action_imports(template_data)
                if wild:
                    raise ValueError(
                        f"{template_code}: wildcard '*' remains in action_imports: {wild[:3]}"
                    )

        if file_changed:
            _write_json(path, payload)
            changed_template_files.append(path)

    # Write action template files (including any variants added).
    changed_action_files: List[Path] = []
    for action_type, payload in index.data.items():
        out_path = index.files[action_type]
        # Conservative: only write files when we added a __ variant.
        if any("__" in k for k in payload.keys()):
            _write_json(out_path, payload)
            changed_action_files.append(out_path)

    print("Canonicalize action_imports complete.")
    print(f"Updated template files: {len(changed_template_files)}")
    print(f"Updated action template files: {len(changed_action_files)}")


if __name__ == "__main__":
    main()

