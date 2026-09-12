#!/usr/bin/env python3
"""Build the narrow native identity manifest for Bloom's reviewed conversion."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ALLOWED_ADDITION_TABLES = frozenset(
    {"generic_instance", "generic_instance_lineage", "audit_log"}
)


def _read(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.resolve() != path or not path.is_file():
        raise ValueError("inputs must be existing canonical absolute files")
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _write_new(path: Path, value: dict[str, Any]) -> None:
    if not path.is_absolute() or path.resolve() != path or not path.parent.is_dir():
        raise ValueError("output must use an existing canonical absolute directory")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _identity(contract: dict[str, Any]) -> dict[str, Any]:
    value = contract.get("identity_inventory", contract)
    if not isinstance(value, dict):
        raise ValueError("identity inventory is missing")
    return value


def _canonical_target(target: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(target)
    port = canonical.get("port")
    server_port = canonical.get("server_port", port)
    if (
        not isinstance(port, int)
        or isinstance(port, bool)
        or not isinstance(server_port, int)
        or isinstance(server_port, bool)
        or not 1 <= port <= 65535
        or server_port != port
    ):
        raise ValueError("identity target ports are invalid or inconsistent")
    canonical["server_port"] = server_port
    return canonical


def main() -> int:
    from daylily_tapdb.identity_inventory import (
        validate_receipt,
        verify_identity_inventory,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--conversion-plan", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    before = _identity(_read(args.before))
    after = _identity(_read(args.after))
    plan = _read(args.conversion_plan)
    validate_receipt(before, "tapdb-identity-inventory/v1")
    validate_receipt(after, "tapdb-identity-inventory/v1")
    if (
        before["target"] != after["target"]
        or before["physical_target"] != after["physical_target"]
        or before["schema_name"] != after["schema_name"]
        or plan.get("schema_version") != "bloom-tapdb10-conversion-plan/v1"
        or _canonical_target(plan.get("target", {}))
        != _canonical_target(before["target"])
        or plan.get("physical_target") != before["physical_target"]
    ):
        raise ValueError("identity receipts and reviewed conversion target differ")
    permitted_instances = {
        (int(item["uid"]), str(item["euid"])): item
        for item in plan["conversion"]["metadata_changes"]
    }
    tables: dict[str, dict[str, Any]] = {}
    for name, original in before["tables"].items():
        current = after["tables"].get(name)
        if current is None:
            raise ValueError(f"original table is missing: {name}")
        old_rows = original["rows"]
        new_rows = current["rows"]
        additions = set(new_rows) - set(old_rows)
        if additions and name not in ALLOWED_ADDITION_TABLES:
            raise ValueError(f"conversion added rows to an unapproved table: {name}")
        changed_columns: dict[str, dict[str, Any]] = {}
        for key, old_row in old_rows.items():
            new_row = new_rows.get(key)
            if new_row is None or new_row["count"] < old_row["count"]:
                raise ValueError(f"conversion removed an original row: {name}:{key}")
            changed = {
                column: {
                    "before": old_hash,
                    "after": new_row["columns"].get(column),
                }
                for column, old_hash in old_row["columns"].items()
                if new_row["columns"].get(column) != old_hash
            }
            if not changed:
                continue
            identity = old_row["identity"]
            identity_key = (
                int(identity.get("uid", -1)),
                str(identity.get("euid", "")),
            )
            if name != "generic_instance" or identity_key not in permitted_instances:
                raise ValueError(
                    f"conversion changed an unapproved original row: {name}:{key}"
                )
            reviewed_change = permitted_instances[identity_key]
            if (
                set(changed) - {"json_addl", "modified_dt"}
                or "json_addl" not in changed
                or changed["json_addl"]
                != {
                    "before": reviewed_change["before"],
                    "after": reviewed_change["after"],
                }
            ):
                raise ValueError(
                    "conversion row changes differ from reviewed metadata update"
                )
            immutable = set(original["immutable_columns"]) | set(
                current["immutable_columns"]
            )
            if set(changed) & immutable:
                raise ValueError("conversion changed immutable instance identity")
            for column, hashes in changed.items():
                changed_columns.setdefault(
                    column, {"kind": "exact_value_hashes", "changes": {}}
                )["changes"][key] = hashes
        tables[name] = {
            "added_rows": bool(additions),
            "added_columns": [],
            "changed_columns": changed_columns,
            "schema_changes": False,
        }
    unexpected_tables = set(after["tables"]) - set(before["tables"])
    if unexpected_tables:
        raise ValueError("Bloom conversion added an unexpected table")
    manifest = {
        "schema_version": "tapdb-identity-conversion/v1",
        "tables": tables,
        "added_tables": [],
    }
    verified = verify_identity_inventory(before, after, conversion_manifest=manifest)
    if not verified["ok"]:
        raise ValueError("native identity verification rejected the generated manifest")
    _write_new(args.manifest, manifest)
    print(json.dumps({"status": "verified", "verification": verified}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
