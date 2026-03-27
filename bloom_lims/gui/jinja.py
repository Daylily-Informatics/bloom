from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

import json
from jinja2 import Environment, FileSystemLoader


templates = Environment(loader=FileSystemLoader("templates"))
templates.filters["tojson"] = lambda x: json.dumps(x)


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
        "color": "#0f766e",
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


refresh_template_globals()
