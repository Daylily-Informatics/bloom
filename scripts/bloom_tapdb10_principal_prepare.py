#!/usr/bin/env python3
"""Plan and apply Bloom's TapDB runtime principal through a reviewed overlay."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any

TAPDB_VERSION = "10.1.3"
OPERATOR_FIELDS = (
    "operator_user",
    "operator_password",
    "operator_secret_arn",
    "operator_iam_auth",
    "operator_configured",
)
MATCH_FIELDS = (
    "engine_type",
    "host",
    "hostaddr",
    "port",
    "server_port",
    "database",
    "schema_name",
    "client_id",
    "database_name",
    "domain_code",
    "owner_repo_name",
    "user",
    "tenant_id",
    "allow_global_claims",
    "iam_auth",
    "secret_arn",
    "password",
    "region",
    "cluster_identifier",
    "aws_profile",
    "ssl",
    "sslmode",
    "sslrootcert",
    "domain_registry_path",
    "prefix_ownership_registry_path",
)


class PreparationError(RuntimeError):
    """An operator input does not match the reviewed Bloom target."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PreparationError(reason)


def _file(path: Path, *, private: bool = False) -> Path:
    _require(path.is_absolute() and path.resolve() == path, "canonical path required")
    _require(path.is_file(), "existing file required")
    if private:
        _require(path.stat().st_mode & 0o077 == 0, "configuration must be private")
    return path


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _sealed(payload: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "sha256"}
    rendered = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**body, "sha256": hashlib.sha256(rendered.encode()).hexdigest()}


def _new_output(path: Path) -> None:
    _require(
        path.is_absolute()
        and path.resolve() == path
        and path.parent.is_dir()
        and path.parent.stat().st_mode & 0o077 == 0,
        "receipt must use an existing private canonical directory",
    )
    _require(
        not path.exists() and not path.is_symlink(), "receipt output already exists"
    )


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    _new_output(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read(path: Path) -> dict[str, Any]:
    with _file(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    _require(isinstance(payload, dict), "expected a JSON object")
    return payload


def _read_sealed(path: Path) -> dict[str, Any]:
    payload = _read(path)
    _require(payload == _sealed(payload), "review receipt is not sealed")
    return payload


def _validate_configs(
    runtime: dict[str, Any],
    operator: dict[str, Any],
    target: dict[str, Any],
    runtime_path: Path,
    operator_path: Path,
) -> dict[str, Any]:
    expected = {
        "engine_type": target["engine_type"],
        "database": target["database"],
        "schema_name": target["schema_name"],
        "client_id": target["client_id"],
        "database_name": target["database_name"],
        "domain_code": target["domain_code"],
        "owner_repo_name": target["owner_repo_name"],
        "allow_global_claims": target["allow_global_claims"],
        "user": target["runtime_user"],
    }
    for name, value in expected.items():
        _require(runtime.get(name) == value, f"unexpected runtime target field: {name}")
        _require(
            operator.get(name) == value, f"unexpected operator target field: {name}"
        )
    _require(
        runtime.get("config_path") == str(runtime_path), "runtime identity changed"
    )
    _require(
        operator.get("config_path") == str(operator_path), "operator identity changed"
    )
    _require(
        runtime.get("operator_configured") is False, "runtime contains operator scope"
    )
    _require(
        not any(runtime.get(name) for name in OPERATOR_FIELDS),
        "runtime contains an operator field",
    )
    _require(
        runtime.get("iam_auth") in (False, "false"),
        "runtime IAM mode must be explicit false",
    )
    _require(runtime.get("password") == "", "runtime plaintext password is forbidden")
    _require(bool(runtime.get("secret_arn")), "runtime secret reference is required")
    _require(operator.get("operator_configured") is True, "operator overlay is missing")
    _require(
        operator.get("operator_user") == target["operator_user"],
        "operator role differs from the reviewed owner census",
    )
    _require(
        operator.get("operator_iam_auth") in (False, "false"),
        "operator IAM must be false",
    )
    _require(
        operator.get("operator_password") == "",
        "operator plaintext password is forbidden",
    )
    _require(
        bool(operator.get("operator_secret_arn")),
        "operator secret reference is required",
    )
    for name in MATCH_FIELDS:
        _require(
            runtime.get(name) == operator.get(name),
            f"runtime/operator mismatch: {name}",
        )
    return {**runtime, **{name: operator[name] for name in OPERATOR_FIELDS}}


def _inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    from daylily_tapdb.cli.db_config import get_db_config

    runtime_path = _file(args.runtime_config, private=True)
    operator_path = _file(args.operator_config, private=True)
    manifest_path = _file(args.manifest)
    manifest = _read(manifest_path)
    _require(
        manifest.get("schema_version") == "bloom-tapdb10-conversion-manifest/v1",
        "unexpected migration manifest",
    )
    target = manifest["target"]
    selectors = {
        "client_id": target["client_id"],
        "database_name": target["database_name"],
    }
    runtime = get_db_config(config_path=runtime_path, **selectors)
    operator = get_db_config(config_path=operator_path, **selectors)
    overlay = _validate_configs(runtime, operator, target, runtime_path, operator_path)
    evidence = {
        "launcher_sha256": _sha256(Path(__file__).resolve()),
        "runtime_config": str(runtime_path),
        "runtime_config_sha256": _sha256(runtime_path),
        "operator_config": str(operator_path),
        "operator_config_sha256": _sha256(operator_path),
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "runtime_config_identity": runtime["config_path"],
        "runtime_user": target["runtime_user"],
        "operator_user": target["operator_user"],
    }
    return overlay, evidence


def main() -> int:
    from daylily_tapdb.runtime_principal import (
        bind_runtime_principal,
        bootstrap_runtime_principal,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("bootstrap-plan", "bootstrap-apply", "bind-plan", "bind-apply"),
    )
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--operator-config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--review-reference")
    args = parser.parse_args()
    os.umask(0o077)
    _require(
        importlib.metadata.version("daylily-tapdb") == TAPDB_VERSION,
        "wrong TapDB version",
    )
    cfg, evidence = _inputs(args)
    receipt = args.receipt
    context = receipt.with_name(receipt.stem + ".inputs.json")
    result_path = receipt.with_name(receipt.stem + ".result.json")
    applying = args.phase.endswith("-apply")
    _require(
        bool(args.review_reference and args.review_reference.strip()) == applying,
        "apply alone requires an independent review reference",
    )
    if args.phase == "bootstrap-plan":
        plan = bootstrap_runtime_principal(cfg, apply=False)
        _write_new(
            receipt,
            _sealed({"operation": "bootstrap", "inputs": evidence, "native": plan}),
        )
    elif args.phase == "bootstrap-apply":
        _new_output(result_path)
        reviewed = _read_sealed(receipt)
        _require(reviewed["operation"] == "bootstrap", "wrong bootstrap plan")
        _require(reviewed["inputs"] == evidence, "bootstrap inputs changed")
        _require(
            reviewed["native"] == bootstrap_runtime_principal(cfg, apply=False),
            "bootstrap plan changed",
        )
        result = bootstrap_runtime_principal(cfg, apply=True)
        _require(result.get("status") == "applied", "bootstrap did not apply")
        _write_new(
            result_path,
            _sealed(
                {
                    "operation": "bootstrap",
                    "review_reference": args.review_reference,
                    "inputs": evidence,
                    "native": result,
                }
            ),
        )
    elif args.phase == "bind-plan":
        _new_output(receipt)
        _new_output(context)
        bind_runtime_principal(cfg, apply=False, receipt_path=receipt)
        _write_new(context, _sealed({"operation": "bind", "inputs": evidence}))
    else:
        _new_output(result_path)
        reviewed = _read_sealed(context)
        _require(reviewed["operation"] == "bind", "wrong bind context")
        _require(reviewed["inputs"] == evidence, "bind inputs changed")
        result = bind_runtime_principal(cfg, apply=True, receipt_path=receipt)
        _require(result.get("status") == "applied", "binding did not apply")
        _require(result.get("runtime_temp_denied") is True, "runtime TEMP remains")
        _require(result.get("privileges_verified") is True, "runtime grants failed")
        _require(result_path.is_file(), "native binding result receipt is missing")
    output = result_path if applying else receipt
    print(json.dumps({"status": "complete", "receipt": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        payload = {"status": "stopped", "error_class": type(exc).__name__}
        if isinstance(exc, PreparationError):
            payload["reason"] = str(exc)
        print(json.dumps(payload, sort_keys=True))
        raise SystemExit(1) from None
