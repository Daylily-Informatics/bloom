#!/usr/bin/env python3
"""Validate one native TapDB transition and freeze prior/future floor files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

TAPDB_VERSION = "10.1.1rc1"


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write_new(path: Path, value: dict[str, Any]) -> None:
    if not path.is_absolute() or path.resolve() != path or not path.parent.is_dir():
        raise ValueError(
            "output must be a canonical absolute path with existing parent"
        )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _records(values: list[dict[str, Any]]) -> Counter[tuple[str, int, str]]:
    return Counter(
        (str(item["name"]), int(item["value"]), str(item["source"])) for item in values
    )


def _validated_floor_sets(
    plan: dict[str, Any], result: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prior = plan["floors"]
    reservations = [
        {
            "name": item["name"],
            "value": item["next_value"],
            "source": "sequence_advance_intent",
        }
        for item in plan["advances"]
    ]
    if (
        result["phase"] != "committed"
        or result["plan_sha256"] != plan["sha256"]
        or result["verification"]["ok"] is not True
        or result["verification"]["violations"] != []
        or result["verification"]["floors"] != prior
        or result["verification"]["inventory_sha256"] != result["inventory"]["sha256"]
        or result["floors"] != prior + reservations
    ):
        raise ValueError(
            "result does not prove advancement against its prior plan floors"
        )
    return prior, result["floors"]


def main() -> int:
    from daylily_tapdb.backup.recovery import recovery_family_state
    from daylily_tapdb.identity_inventory import seal_receipt, validate_receipt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--recovery-family", required=True, type=Path)
    parser.add_argument("--prior-floors", required=True, type=Path)
    parser.add_argument("--future-floors", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--review-reference", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if importlib.metadata.version("daylily-tapdb") != TAPDB_VERSION:
        raise RuntimeError(f"exact daylily-tapdb {TAPDB_VERSION} is required")
    inputs = (args.plan, args.result, args.recovery_family)
    if any(
        not path.is_absolute() or path.resolve() != path or not path.is_file()
        for path in inputs
    ):
        raise ValueError("all inputs must be existing canonical absolute files")
    if not args.review_reference.strip():
        raise ValueError("independent review reference is required")

    plan = _read(args.plan)
    result = _read(args.result)
    family = _read(args.recovery_family)
    validate_receipt(plan, "tapdb-sequence-advance/v1")
    validate_receipt(result, "tapdb-sequence-apply/v1")
    validate_receipt(result["verification"], "tapdb-sequence-verification/v1")
    validate_receipt(result["inventory"], "tapdb-sequence-inventory/v1")
    release = result["writer_fence_release"]
    validate_receipt(release, "tapdb-writer-fence/v1")
    prior, future = _validated_floor_sets(plan, result)
    unsigned = {
        key: value for key, value in result.items() if key != "writer_fence_release"
    }
    if (
        release["phase"] != "released"
        or release["result_sha256"] != seal_receipt(unsigned)["sha256"]
        or not (release["target"] == result["inventory"]["target"] == plan["target"])
        or release["physical_target"] != result["inventory"]["physical_target"]
        or (
            plan.get("physical_target") is not None
            and release["physical_target"] != plan["physical_target"]
        )
        or not (
            release["recovery_family"]
            == result["recovery_family"]
            == plan["recovery_family"]
            == family
        )
    ):
        raise ValueError(
            "native committed result, fence release, target, or family diverges"
        )
    state = recovery_family_state(family, require_terminal=True)
    if set(_records(state["floors"])) != set(_records(result["floors"])):
        raise ValueError(
            "terminal recovery family does not retain the completed transition floors"
        )

    _write_new(args.prior_floors, {"floors": prior})
    _write_new(args.future_floors, {"floors": future})
    _write_new(
        args.receipt,
        {
            "schema_version": "bloom-sequence-transition-receipt/v1",
            "status": "verified",
            "review_reference": args.review_reference,
            "inputs": [{"path": str(path), "sha256": _hash(path)} for path in inputs],
            "plan_sha256": plan["sha256"],
            "inventory_sha256": result["inventory"]["sha256"],
            "verification_sha256": result["verification"]["sha256"],
            "prior_floor_count": len(prior),
            "future_floor_count": len(future),
            "prior_floors": {
                "path": str(args.prior_floors),
                "sha256": _hash(args.prior_floors),
            },
            "future_floors": {
                "path": str(args.future_floors),
                "sha256": _hash(args.future_floors),
            },
        },
    )
    print(
        json.dumps({"status": "verified", "receipt": str(args.receipt)}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
