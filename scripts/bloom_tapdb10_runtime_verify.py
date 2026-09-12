#!/usr/bin/env python3
"""Verify Bloom's constrained TapDB runtime principal from fresh sessions."""

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


class VerificationError(RuntimeError):
    """A credential-free runtime verification failure."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise VerificationError(reason)


def _file(path: Path, *, private: bool = False) -> Path:
    _require(path.is_absolute() and path.resolve() == path, "canonical path required")
    _require(path.is_file(), "existing file required")
    if private:
        _require(path.stat().st_mode & 0o077 == 0, "runtime config must be private")
    return path


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _sealed(payload: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "sha256"}
    rendered = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**body, "sha256": hashlib.sha256(rendered.encode()).hexdigest()}


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    _require(
        path.is_absolute() and path.resolve() == path and path.parent.is_dir(),
        "receipt must be a canonical absolute path in an existing directory",
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read(path: Path) -> dict[str, Any]:
    with _file(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    _require(isinstance(payload, dict), "manifest must be a JSON object")
    return payload


def _validate_runtime(
    cfg: dict[str, Any], expected: dict[str, Any], path: Path
) -> None:
    pairs = {
        "engine_type": expected["engine_type"],
        "database": expected["database"],
        "schema_name": expected["schema_name"],
        "client_id": expected["client_id"],
        "database_name": expected["database_name"],
        "domain_code": expected["domain_code"],
        "owner_repo_name": expected["owner_repo_name"],
        "allow_global_claims": expected["allow_global_claims"],
        "user": expected["runtime_user"],
    }
    for key, value in pairs.items():
        _require(cfg.get(key) == value, f"unexpected runtime target field: {key}")
    _require(cfg.get("config_path") == str(path), "runtime config identity changed")
    _require(
        cfg.get("operator_configured") is False, "runtime config has operator scope"
    )
    _require(
        not any(cfg.get(key) for key in OPERATOR_FIELDS),
        "runtime config contains an operator field",
    )
    _require(
        cfg.get("iam_auth") in (False, "false"),
        "runtime IAM mode must be explicit false",
    )
    _require(cfg.get("password") == "", "plaintext runtime password is forbidden")
    _require(bool(cfg.get("secret_arn")), "runtime secret reference is required")


def _session_evidence(session: Any, cfg: dict[str, Any], expected: dict[str, Any]):
    from sqlalchemy import text

    row = dict(
        session.execute(
            text(
                """
                SELECT current_database() AS database, current_user AS role,
                  session_user AS login, pg_backend_pid() AS backend_pid,
                  has_database_privilege(current_user,current_database(),'CONNECT') AS connect,
                  has_database_privilege(current_user,current_database(),'TEMP') AS temp,
                  has_database_privilege(current_user,current_database(),'CREATE') AS db_create,
                  has_schema_privilege(current_user,:schema,'CREATE') AS schema_create,
                  current_setting('session.current_config_identity') AS config_identity,
                  current_setting('session.current_domain_code') AS domain,
                  current_setting('session.current_owner_repo_name') AS owner,
                  current_setting('session.current_tenant_id') AS tenant,
                  current_setting('session.allow_global_rows') AS allow_global,
                  rolsuper, rolbypassrls, rolcreatedb, rolcreaterole,
                  rolreplication, rolinherit
                FROM pg_catalog.pg_roles WHERE rolname=current_user
                """
            ),
            {"schema": cfg["schema_name"]},
        )
        .mappings()
        .one()
    )
    for key in (
        "temp",
        "db_create",
        "schema_create",
        "rolsuper",
        "rolbypassrls",
        "rolcreatedb",
        "rolcreaterole",
        "rolreplication",
        "rolinherit",
    ):
        _require(row[key] is False, f"runtime retains forbidden privilege: {key}")
    _require(row["connect"] is True, "runtime CONNECT is missing")
    _require(row["database"] == expected["database"], "runtime database mismatch")
    _require(
        row["role"] == row["login"] == expected["runtime_user"],
        "runtime login identity mismatch",
    )
    _require(
        row["config_identity"] == cfg["config_path"], "runtime config scope mismatch"
    )
    _require(
        row["domain"] == expected["domain_code"]
        and row["owner"] == expected["owner_repo_name"],
        "runtime domain/owner scope mismatch",
    )
    _require(row["tenant"] == (cfg.get("tenant_id") or ""), "runtime tenant mismatch")
    _require(
        row["allow_global"] == ("true" if expected["allow_global_claims"] else "false"),
        "runtime global-row policy mismatch",
    )
    return row


def _sequence_evidence(session: Any, cfg: dict[str, Any], operator_user: str):
    from sqlalchemy import text

    rows = [
        dict(row)
        for row in session.execute(
            text(
                """
                SELECT c.relname AS name, pg_get_userbyid(c.relowner) AS owner,
                  has_sequence_privilege(current_user,
                    format('%I.%I', n.nspname, c.relname), 'USAGE') AS usage,
                  has_sequence_privilege(current_user,
                    format('%I.%I', n.nspname, c.relname), 'SELECT') AS selectable
                  ,has_sequence_privilege(current_user,
                    format('%I.%I', n.nspname, c.relname), 'UPDATE') AS updatable
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=:schema AND c.relkind='S'
                ORDER BY c.relname
                """
            ),
            {"schema": cfg["schema_name"]},
        ).mappings()
    ]
    granted = [
        row for row in rows if row["usage"] or row["selectable"] or row["updatable"]
    ]
    _require(bool(granted), "runtime has no managed sequence grants")
    for row in granted:
        _require(
            row["usage"] is True and row["selectable"] is True, "partial sequence grant"
        )
        _require(row["updatable"] is False, "runtime can change a managed sequence")
        _require(
            row["owner"] == operator_user, "granted sequence owner is not operator_user"
        )
    return {
        "catalog_count": len(rows),
        "granted_count": len(granted),
        "granted": [{"name": row["name"], "owner": row["owner"]} for row in granted],
    }


def main() -> int:
    from daylily_tapdb.cli.context import set_cli_context
    from daylily_tapdb.cli.db_config import get_db_config
    from daylily_tapdb.web.runtime import dispose_all_runtime_engines, get_db
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    _require(
        importlib.metadata.version("daylily-tapdb") == TAPDB_VERSION,
        "wrong TapDB version",
    )
    _require(
        importlib.metadata.version("bloom_lims") == "10.0.1", "wrong Bloom release"
    )
    runtime_path = _file(args.runtime_config, private=True)
    manifest_path = _file(args.manifest)
    manifest = _read(manifest_path)
    _require(
        manifest.get("schema_version") == "bloom-tapdb10-conversion-manifest/v1",
        "unexpected migration manifest",
    )
    expected = manifest["target"]
    cfg = get_db_config(
        config_path=runtime_path,
        client_id=expected["client_id"],
        database_name=expected["database_name"],
    )
    _validate_runtime(cfg, expected, runtime_path)
    _require(not args.receipt.exists(), "runtime receipt already exists")
    set_cli_context(
        config_path=runtime_path,
        client_id=expected["client_id"],
        database_name=expected["database_name"],
    )
    result: dict[str, Any] = {
        "schema_version": "bloom-tapdb10-runtime-verification/v1",
        "runtime_config": str(runtime_path),
        "runtime_config_sha256": _sha256(runtime_path),
        "manifest_sha256": _sha256(manifest_path),
    }
    try:
        dispose_all_runtime_engines()
        db = get_db(str(runtime_path))
        db.app_username = "bloom-migration-acceptance"
        transactions = []
        for _index in range(2):
            with db.session_scope(commit=False) as session:
                transactions.append(_session_evidence(session, cfg, expected))
        try:
            with db.session_scope(commit=False) as session:
                _session_evidence(session, cfg, expected)
                raise RuntimeError("intentional-runtime-rollback-probe")
        except RuntimeError as exc:
            _require(
                str(exc) == "intentional-runtime-rollback-probe",
                "rollback probe changed",
            )
        with db.session_scope(commit=False) as session:
            after_rollback = _session_evidence(session, cfg, expected)
            required_table_access = {
                "generic_template": ("SELECT",),
                "generic_instance": ("SELECT", "INSERT", "UPDATE", "DELETE"),
                "generic_instance_lineage": (
                    "SELECT",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                ),
            }
            table_access = {
                table_name: {
                    privilege: bool(
                        session.execute(
                            text(
                                "SELECT has_table_privilege(current_user, "
                                "format('%I.%I', :schema, :table), :privilege)"
                            ),
                            {
                                "schema": cfg["schema_name"],
                                "table": table_name,
                                "privilege": privilege,
                            },
                        ).scalar_one()
                    )
                    for privilege in privileges
                }
                for table_name, privileges in required_table_access.items()
            }
            _require(
                all(
                    granted
                    for privileges in table_access.values()
                    for granted in privileges.values()
                ),
                "required application table access is missing",
            )
            sequence_evidence = _sequence_evidence(
                session, cfg, expected["operator_user"]
            )
        ddl_denial = []
        statements = (
            (
                "temporary_table",
                "CREATE TEMP TABLE bloom_runtime_temp_probe (n integer)",
            ),
            (
                "managed_schema_table",
                f'CREATE TABLE "{cfg["schema_name"]}"."bloom_runtime_ddl_probe" (n integer)',
            ),
        )
        for label, statement in statements:
            dispose_all_runtime_engines()
            db = get_db(str(runtime_path))
            db.app_username = "bloom-migration-acceptance"
            attempted = False
            denied = False
            try:
                with db.session_scope(commit=False) as session:
                    attempted = True
                    session.execute(text(statement))
            except DBAPIError as exc:
                sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
                    exc.orig, "pgcode", None
                )
                denied = attempted and sqlstate == "42501"
                if not denied:
                    raise
            _require(denied, f"runtime DDL was not denied: {label}")
            ddl_denial.append({"probe": label, "sqlstate": "42501"})
        result.update(
            status="verified",
            transactions=transactions,
            rollback_recovery=after_rollback,
            table_access=table_access,
            sequences=sequence_evidence,
            ddl_denial=ddl_denial,
        )
        _write_new(args.receipt, _sealed(result))
        print(
            json.dumps(
                {"status": "verified", "receipt": str(args.receipt)}, sort_keys=True
            )
        )
        return 0
    finally:
        dispose_all_runtime_engines()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        payload = {"status": "stopped", "error_class": type(exc).__name__}
        if isinstance(exc, VerificationError):
            payload["reason"] = str(exc)
        print(json.dumps(payload, sort_keys=True))
        raise SystemExit(1) from None
