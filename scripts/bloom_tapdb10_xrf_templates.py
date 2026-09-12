#!/usr/bin/env python3
"""Plan or add the package-declared TapDB 10.1 core XRF templates for Bloom."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

TAPDB_VERSION = "10.1.3"
_ROLES = {"opaque", "tapdb_object"}
_FIELDS = (
    "name",
    "polymorphic_discriminator",
    "category",
    "type",
    "subtype",
    "version",
    "instance_prefix",
    "is_singleton",
    "bstatus",
    "json_addl",
    "json_addl_schema",
)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        result = json.load(handle)
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    return result


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    if not path.is_absolute() or path.resolve() != path or not path.parent.is_dir():
        raise ValueError(
            "receipt must be a canonical absolute path in an existing directory"
        )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _replace_reserved(path: Path, payload: dict[str, Any]) -> None:
    reserved = _read(path)
    if (
        reserved.get("schema_version") != "bloom-tapdb10-xrf-template-reservation/v1"
        or reserved.get("status") != "reserved"
    ):
        raise ValueError("XRF template receipt is not the reserved output")
    temporary = path.with_name(path.name + f".final-{os.getpid()}")
    _write_new(temporary, payload)
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _validate_after(before: dict[str, Any], after: dict[str, Any]) -> None:
    if (
        after["all_template_count"]
        != before["all_template_count"] + before["expected_inserted"]
        or len(after["existing"]) != 2
        or any(item not in after["existing"] for item in before["existing"])
        or any(
            after["all_template_fingerprints"].get(key) != fingerprint
            for key, fingerprint in before["all_template_fingerprints"].items()
        )
    ):
        raise ValueError(
            "XRF setup changed existing templates or inserted the wrong set"
        )


def _receipt_value(value: Any) -> Any:
    """Normalize complete ORM values for a stable, private receipt fingerprint."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _receipt_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_receipt_value(item) for item in value]
    return value


def _complete_template_fingerprint(row: Any, columns: tuple[str, ...]) -> str:
    from daylily_tapdb.identity_inventory import content_hash

    return content_hash(
        {field: _receipt_value(getattr(row, field, None)) for field in columns}
    )


def _definitions() -> tuple[Path, list[dict[str, Any]]]:
    from daylily_tapdb.templates.loader import (
        find_tapdb_core_config_dir,
        load_template_configs,
    )

    root = find_tapdb_core_config_dir().resolve()
    selected = [
        row
        for row in load_template_configs(root)
        if (row.get("category"), row.get("type"))
        == ("reference", "external_identifier")
        and row.get("subtype") in _ROLES
    ]
    if (
        len(selected) != 2
        or {row["subtype"] for row in selected} != _ROLES
        or any(row.get("instance_prefix") != "XRF" for row in selected)
    ):
        raise ValueError(
            "installed TapDB does not supply the exact two core XRF templates"
        )
    return root, sorted(selected, key=lambda row: row["subtype"])


def _state(session: Any, definitions: list[dict[str, Any]]) -> dict[str, Any]:
    from daylily_tapdb.identity_inventory import content_hash
    from daylily_tapdb.models.template import generic_template

    all_rows = (
        session.query(generic_template).order_by(generic_template.uid.asc()).all()
    )
    all_columns = tuple(column.name for column in generic_template.__table__.columns)
    existing: list[dict[str, Any]] = []
    for definition in definitions:
        matches = [
            row
            for row in all_rows
            if row.domain_code == "M"
            and row.issuer_app_code == "daylily-tapdb"
            and (row.category, row.type, row.subtype, row.version)
            == (
                definition["category"],
                definition["type"],
                definition["subtype"],
                definition["version"],
            )
        ]
        if len(matches) > 1:
            raise ValueError("ambiguous core XRF template")
        if matches:
            row = matches[0]
            if row.is_deleted or any(
                getattr(row, field, None) != definition.get(field) for field in _FIELDS
            ):
                raise ValueError(
                    "existing core XRF template differs; never overwrite it"
                )
            existing.append(
                {
                    "uid": row.uid,
                    "euid": row.euid,
                    "category": row.category,
                    "type": row.type,
                    "subtype": row.subtype,
                    "version": row.version,
                    "fingerprint": content_hash(
                        {field: getattr(row, field, None) for field in _FIELDS}
                    ),
                }
            )
    return {
        "all_template_count": len(all_rows),
        "all_template_fingerprints": {
            str(row.uid): _complete_template_fingerprint(row, all_columns)
            for row in all_rows
        },
        "existing": existing,
        "expected_inserted": 2 - len(existing),
    }


def main() -> int:
    from daylily_tapdb.cli.db_config import get_db_config
    from daylily_tapdb.identity_inventory import (
        content_hash,
        physical_target,
        validate_target,
    )
    from daylily_tapdb.runtime_principal import operator_connection
    from daylily_tapdb.security_context import (
        TapdbTransactionContext,
        apply_transaction_context,
        assert_operator_role,
    )
    from daylily_tapdb.templates.loader import seed_templates
    from sqlalchemy.orm import Session

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "apply", "reconcile"))
    parser.add_argument("--operator-config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    parser.add_argument("--review-reference")
    parser.add_argument("--actor", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if importlib.metadata.version("daylily-tapdb") != TAPDB_VERSION:
        raise RuntimeError(f"exact daylily-tapdb {TAPDB_VERSION} is required")
    if not args.actor or args.actor != args.actor.strip():
        raise ValueError("actor must be exact and non-empty")
    for path in (args.operator_config, args.manifest):
        if not path.is_absolute() or path.resolve() != path or not path.is_file():
            raise ValueError("operator config and manifest must be canonical files")
    manifest = _read(args.manifest)
    if manifest.get("schema_version") != "bloom-tapdb10-conversion-manifest/v1":
        raise ValueError("unexpected Bloom migration manifest")
    cfg = get_db_config(
        config_path=args.operator_config,
        client_id="bloom",
        database_name="bloom-day",
    )
    expected_target = manifest["target"]
    if any(
        cfg.get(key) != expected_target[key]
        for key in (
            "engine_type",
            "database",
            "schema_name",
            "client_id",
            "database_name",
            "domain_code",
            "owner_repo_name",
            "allow_global_claims",
        )
    ) or (
        cfg.get("user") != expected_target["runtime_user"]
        or cfg.get("operator_user") != expected_target["operator_user"]
    ):
        raise ValueError("operator config differs from Bloom's reviewed target scope")
    core_dir, definitions = _definitions()
    target = validate_target(
        {
            "engine_type": cfg["engine_type"],
            "host": cfg["host"],
            "port": cfg["port"],
            "database": cfg["database"],
            "schema_name": cfg["schema_name"],
            "config_identity": str(args.operator_config),
            "domain_code": "M",
            "owner_repo_name": "bloom",
        },
        cfg["schema_name"],
    )
    inputs = {
        "schema_version": "bloom-tapdb10-xrf-template-plan/v1",
        "operator_config": str(args.operator_config),
        "operator_config_sha256": _sha256(args.operator_config),
        "manifest": str(args.manifest),
        "manifest_sha256": _sha256(args.manifest),
        "script_sha256": _sha256(Path(__file__)),
        "target": target,
        "actor": args.actor,
        "definition_hashes": {
            row["subtype"]: content_hash({field: row.get(field) for field in _FIELDS})
            for row in definitions
        },
        "overwrite": False,
    }
    reviewed: dict[str, Any] | None = None
    if args.operation in {"apply", "reconcile"}:
        if args.plan is None or not args.plan.is_absolute() or not args.plan.is_file():
            raise ValueError("apply/reconcile requires a canonical reviewed plan")
        if (
            not args.reviewed_plan_sha256
            or _sha256(args.plan) != args.reviewed_plan_sha256
            or not str(args.review_reference or "").strip()
        ):
            raise ValueError(
                "apply/reconcile requires exact independent review evidence"
            )
        reviewed = _read(args.plan)
        if any(reviewed.get(key) != value for key, value in inputs.items()):
            raise ValueError("reviewed template inputs changed")

    if args.operation == "reconcile":
        reservation = _read(args.receipt)
        if (
            reservation.get("schema_version")
            != "bloom-tapdb10-xrf-template-reservation/v1"
            or reservation.get("status") != "reserved"
            or reservation.get("plan_sha256") != args.reviewed_plan_sha256
        ):
            raise ValueError("reconcile requires the exact reserved apply receipt")

    with operator_connection(cfg, read_only=args.operation != "apply") as connection:
        physical = physical_target(connection, target)
        with Session(bind=connection, expire_on_commit=False) as session:
            apply_transaction_context(
                session,
                TapdbTransactionContext(
                    config_identity=str(args.operator_config),
                    schema_name=cfg["schema_name"],
                    domain_code="M",
                    owner_repo_name="bloom",
                    tenant_id=cfg.get("tenant_id") or None,
                    actor=args.actor,
                    allow_global_rows=True,
                ),
                assert_runtime_role=False,
            )
            assert_operator_role(
                session,
                schema_name=cfg["schema_name"],
                operator_user=cfg["operator_user"],
            )
            before = _state(session, definitions)
            if args.operation == "reconcile":
                if physical != reviewed["physical_target"]:
                    raise ValueError("actual XRF target differs from reviewed plan")
                _validate_after(reviewed["before"], before)
                after = before
                reconciled = True
            elif args.operation == "plan":
                plan = {**inputs, "physical_target": physical, "before": before}
                _write_new(args.receipt, plan)
                print(
                    json.dumps(
                        {
                            "status": "planned",
                            "receipt": str(args.receipt),
                            "sha256": _sha256(args.receipt),
                        },
                        sort_keys=True,
                    )
                )
                return 0
            else:
                plan = {**inputs, "physical_target": physical, "before": before}
                if reviewed != plan:
                    raise ValueError(
                        "live template plan changed after independent review"
                    )
                _write_new(
                    args.receipt,
                    {
                        "schema_version": "bloom-tapdb10-xrf-template-reservation/v1",
                        "status": "reserved",
                        "plan_sha256": args.reviewed_plan_sha256,
                    },
                )
                summary = seed_templates(
                    session,
                    definitions,
                    overwrite=False,
                    core_config_dir=core_dir,
                    domain_code="M",
                    owner_repo_name="daylily-tapdb",
                    domain_registry_path=Path(cfg["domain_registry_path"]),
                    prefix_registry_path=Path(cfg["prefix_ownership_registry_path"]),
                )
                after = _state(session, definitions)
                _validate_after(before, after)
                if (
                    summary.updated != 0
                    or summary.inserted != before["expected_inserted"]
                ):
                    raise ValueError(
                        "native XRF seed summary differs from reviewed plan"
                    )
                reconciled = False

    _replace_reserved(
        args.receipt,
        {
            "schema_version": "bloom-tapdb10-xrf-template-result/v1",
            "status": "reconciled_committed" if reconciled else "committed",
            "review_reference": args.review_reference,
            "plan_sha256": args.reviewed_plan_sha256,
            "physical_target": physical,
            "inserted": after["all_template_count"]
            - reviewed["before"]["all_template_count"],
            "updated": 0,
            "skipped": len(reviewed["before"]["existing"]),
            "after": after,
        },
    )
    print(
        json.dumps(
            {
                "status": "reconciled_committed" if reconciled else "committed",
                "receipt": str(args.receipt),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "stopped", "error_class": type(exc).__name__}, sort_keys=True
            )
        )
        raise SystemExit(1) from None
