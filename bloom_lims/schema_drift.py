from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bloom_lims.config import apply_runtime_environment, get_settings


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _state_dir() -> Path:
    try:
        from cli_core_yo.runtime import get_context

        return get_context().xdg_paths.state
    except Exception:
        return Path.home() / ".local" / "state" / "bloom"


def schema_drift_state_file() -> Path:
    return _state_dir() / "schema_drift.json"


def tapdb_tool_version() -> str:
    try:
        return importlib.metadata.version("daylily-tapdb")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _tapdb_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = apply_runtime_environment(get_settings())
    runtime = os.environ.copy()
    runtime.setdefault("TAPDB_ENV", env.env)
    runtime.setdefault("TAPDB_DATABASE_NAME", env.database_name)
    if env.config_path:
        runtime.setdefault("TAPDB_CONFIG_PATH", env.config_path)
    runtime.setdefault("AWS_PROFILE", env.aws_profile)
    runtime.setdefault("AWS_REGION", env.aws_region)
    runtime.setdefault("AWS_DEFAULT_REGION", env.aws_region)
    return subprocess.run(
        [sys.executable, "-m", "daylily_tapdb.cli", *args],
        env=runtime,
        capture_output=True,
        text=True,
    )


def _schema_drift_summary(payload: dict[str, object]) -> str:
    counts = payload.get("counts")
    if isinstance(counts, dict):
        expected = counts.get("expected")
        live = counts.get("live")
        return f"expected={expected} live={live}"
    return "drift report available"


def _status_for_returncode(returncode: int) -> str:
    if returncode == 0:
        return "clean"
    if returncode == 1:
        return "drift"
    return "check_failed"


def _truncate_stderr(stderr: str) -> str:
    cleaned = (stderr or "").strip()
    if len(cleaned) <= 1000:
        return cleaned
    return f"{cleaned[:1000]}..."


def run_schema_drift_check(env_name: str) -> dict[str, Any]:
    result = _tapdb_cmd(["db", "schema", "drift-check", env_name, "--json", "--no-strict"])
    payload: dict[str, object] = {}
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {"raw_stdout": result.stdout.strip()}

    status = _status_for_returncode(result.returncode)
    return {
        "status": status,
        "checked_at": _utcnow(),
        "environment": env_name,
        "tool_version": tapdb_tool_version(),
        "summary": _schema_drift_summary(payload) if payload else ("schema drift check failed" if status == "check_failed" else "schema drift check completed"),
        "report": payload,
        "stderr": _truncate_stderr(result.stderr) if status == "check_failed" else "",
    }


def write_schema_drift_report(report: dict[str, Any]) -> None:
    path = schema_drift_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def read_schema_drift_report(*, environment: str) -> dict[str, Any]:
    path = schema_drift_state_file()
    if not path.exists():
        return {
            "status": "not_run",
            "checked_at": None,
            "environment": environment,
            "tool_version": tapdb_tool_version(),
            "summary": "Schema drift check has not been run",
            "report": {},
            "stderr": "",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "check_failed",
            "checked_at": _utcnow(),
            "environment": environment,
            "tool_version": tapdb_tool_version(),
            "summary": "Stored schema drift report could not be read",
            "report": {},
            "stderr": _truncate_stderr(str(exc)),
        }
    if not isinstance(payload, dict):
        return {
            "status": "check_failed",
            "checked_at": _utcnow(),
            "environment": environment,
            "tool_version": tapdb_tool_version(),
            "summary": "Stored schema drift report has invalid format",
            "report": {},
            "stderr": "",
        }
    payload.setdefault("status", "check_failed")
    payload.setdefault("checked_at", None)
    payload.setdefault("environment", environment)
    payload.setdefault("tool_version", tapdb_tool_version())
    payload.setdefault("summary", "")
    payload.setdefault("report", {})
    payload.setdefault("stderr", "")
    return payload
