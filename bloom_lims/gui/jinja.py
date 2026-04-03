from __future__ import annotations

from datetime import UTC, datetime
import subprocess
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

import json
from jinja2 import Environment, FileSystemLoader, pass_context

try:
    from daylily_tapdb.timezone_utils import (
        DEFAULT_DISPLAY_TIMEZONE,
        normalize_display_timezone,
    )
except Exception:
    DEFAULT_DISPLAY_TIMEZONE = "UTC"

    def normalize_display_timezone(value: str | None, default: str = "UTC") -> str:
        candidate = str(value or "").strip()
        if not candidate:
            return default
        if candidate.upper() in {"UTC", "GMT", "GMT+00:00", "Z"}:
            return "UTC"
        try:
            return ZoneInfo(candidate).key
        except Exception:
            return default


templates = Environment(loader=FileSystemLoader("templates"))
templates.filters["tojson"] = lambda x: json.dumps(x)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _resolve_display_timezone(context: dict[str, Any]) -> str:
    for key in ("udat", "user_data", "user"):
        prefs = context.get(key)
        if isinstance(prefs, dict):
            return normalize_display_timezone(
                prefs.get("display_timezone"),
                default=DEFAULT_DISPLAY_TIMEZONE,
            )
    return DEFAULT_DISPLAY_TIMEZONE


@pass_context
def format_dt(context: dict[str, Any], value: Any, format_type: str = "standard") -> str:
    dt = _coerce_datetime(value)
    if dt is None:
        if value is None:
            return ""
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)

    display_timezone = _resolve_display_timezone(context)
    try:
        dt = dt.astimezone(ZoneInfo(display_timezone))
    except Exception:
        dt = dt.astimezone(UTC)

    if format_type == "precise":
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f %Z")
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


@pass_context
def dt_local_input(context: dict[str, Any], value: Any) -> str:
    dt = _coerce_datetime(value)
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    display_timezone = _resolve_display_timezone(context)
    try:
        dt = dt.astimezone(ZoneInfo(display_timezone))
    except Exception:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _run_git_command(*args: str) -> str:
    """Run a git command from repo root and return stripped stdout."""
    repo_root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _resolve_gui_metadata() -> Dict[str, str]:
    """Resolve footer/help metadata from config and local git state."""
    app_name = "BLOOM LIMS"
    version = "dev"
    support_email = ""
    github_repo_url = "https://github.com/Daylily-Informatics/bloom"

    try:
        from bloom_lims.config import get_settings

        settings = get_settings()
        app_name = settings.app_name
        version = settings.api.version
        support_email = settings.ui.support_email
        github_repo_url = settings.ui.github_repo_url
    except Exception:
        pass

    branch = _run_git_command("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    commit_hash = _run_git_command("rev-parse", "--short", "HEAD") or "unknown"
    tag = _run_git_command("describe", "--tags", "--exact-match")
    if not tag:
        tag = _run_git_command("describe", "--tags", "--abbrev=0")
    if not tag:
        tag = "none"

    return {
        "app_name": app_name,
        "version": version,
        "branch": branch,
        "tag": tag,
        "hash": commit_hash,
        "support_email": support_email,
        "github_repo_url": github_repo_url,
    }

def _resolve_deployment_metadata() -> Dict[str, str | bool]:
    deployment = {
        "name": "",
        "color": "#AFEEEE",
        "is_production": False,
    }
    try:
        from bloom_lims.config import get_settings

        settings = get_settings()
        deployment = {
            "name": settings.deployment.name,
            "color": settings.deployment.color,
            "is_production": settings.deployment.is_production,
        }
    except Exception:
        pass
    return deployment


def refresh_template_globals() -> None:
    templates.globals["gui_meta"] = _resolve_gui_metadata()
    templates.globals["deployment_chrome"] = _resolve_deployment_metadata()


templates.filters["format_dt"] = format_dt
templates.filters["dt_local_input"] = dt_local_input
refresh_template_globals()
