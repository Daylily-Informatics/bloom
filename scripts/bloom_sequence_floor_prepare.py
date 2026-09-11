#!/usr/bin/env python3
"""Project frozen Bloom source-next evidence into explicit transition floors."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any

TAPDB_VERSION = "10.1.1rc1"


def _read(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.resolve() != path or not path.is_file():
        raise ValueError("inputs must be existing canonical absolute files")
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write_new(path: Path, value: dict[str, Any]) -> None:
    if not path.is_absolute() or path.resolve() != path or not path.parent.is_dir():
        raise ValueError("output must use an existing canonical absolute directory")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _require_new(path: Path) -> None:
    if (
        not path.is_absolute()
        or path.resolve() != path
        or not path.parent.is_dir()
        or path.exists()
        or path.is_symlink()
    ):
        raise ValueError("output must be a new canonical path in an existing directory")


def _cli_floor_document(floors: list[dict[str, Any]]) -> dict[str, Any]:
    """Return exactly the public CLI's accepted floor input object."""
    return {"floors": floors}


def main() -> int:
    from daylily_tapdb.backup.recovery import inventory_floors, recovery_family_state
    from daylily_tapdb.identity_inventory import validate_receipt
    from daylily_tapdb.sequences import build_sequence_advance_plan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--source-next-plan", type=Path, required=True)
    parser.add_argument("--recovery-family", type=Path, required=True)
    parser.add_argument("--floors", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if importlib.metadata.version("daylily-tapdb") != TAPDB_VERSION:
        raise RuntimeError(f"exact daylily-tapdb {TAPDB_VERSION} is required")
    _require_new(args.floors)
    _require_new(args.receipt)
    source = _read(args.source_contract)
    plan = _read(args.source_next_plan)
    family = _read(args.recovery_family)
    validate_receipt(source, "tapdb-source-contract/v1")
    validate_receipt(plan, "tapdb-sequence-advance/v1")
    validate_receipt(source["sequence_inventory"], "tapdb-sequence-inventory/v1")
    recovery_family_state(family, require_terminal=False)
    if (
        plan["inventory"] != source["sequence_inventory"]
        or plan.get("recovery_family") != family
        or build_sequence_advance_plan(
            plan["inventory"],
            floors=plan.get("input_floors", plan["floors"]),
            recovery_family=family,
        )
        != plan
    ):
        raise ValueError("source-next plan does not match the frozen family contract")
    provenance = (
        f"{args.source_next_plan}:file_sha256={_sha256(args.source_next_plan)}:"
        f"native_sha256={plan['sha256']}"
    )
    records = inventory_floors(plan["inventory"], source=provenance + ":inventory")
    records.extend(
        {**item, "source": provenance + ":retained:" + item["source"]}
        for item in plan["floors"]
    )
    records.extend(
        {
            "name": item["name"],
            "value": item["next_value"],
            "source": provenance + ":native_planned_next",
        }
        for item in plan["advances"]
    )
    unique = {
        (str(item["name"]), int(item["value"]), str(item["source"])): {
            "name": str(item["name"]),
            "value": int(item["value"]),
            "source": str(item["source"]),
        }
        for item in records
    }
    floors = [unique[key] for key in sorted(unique)]
    _write_new(args.floors, _cli_floor_document(floors))
    _write_new(
        args.receipt,
        {
            "schema_version": "bloom-sequence-floor-projection/v1",
            "status": "prepared",
            "floors": {
                "path": str(args.floors),
                "sha256": _sha256(args.floors),
                "count": len(floors),
            },
            "source_contract": {
                "path": str(args.source_contract),
                "sha256": _sha256(args.source_contract),
                "native_sha256": source["sha256"],
            },
            "source_next_plan": {
                "path": str(args.source_next_plan),
                "sha256": _sha256(args.source_next_plan),
                "native_sha256": plan["sha256"],
            },
            "recovery_family": {
                "path": str(args.recovery_family),
                "sha256": _sha256(args.recovery_family),
            },
        },
    )
    print(
        json.dumps({"status": "prepared", "floor_count": len(floors)}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
