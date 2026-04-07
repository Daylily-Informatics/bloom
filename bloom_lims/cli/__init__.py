"""BLOOM LIMS CLI — built on cli-core-yo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cli_core_yo.app import create_app as _create_app
from cli_core_yo.app import run
from cli_core_yo.spec import CliSpec, ConfigSpec, EnvSpec, PluginSpec, PolicySpec, XdgSpec

from bloom_lims.config import (
    _resolve_deployment_code,
    apply_runtime_environment,
    assert_tapdb_version,
    build_default_config_template,
    get_settings,
    get_tapdb_db_config,
    validate_config_content,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACTIVATE_SCRIPT = "./activate"
DEACTIVATE_SCRIPT = "./bloom_deactivate"


def _validate_bloom_config(content: str) -> list[str]:
    """Validate Bloom config file contents."""
    return validate_config_content(content)


def _bloom_info_hook() -> list[tuple[str, str]]:
    """Extra rows for the built-in ``info`` command."""
    settings = get_settings()
    ctx = apply_runtime_environment(settings)

    rows: list[tuple[str, str]] = [
        ("Project Root", str(PROJECT_ROOT)),
        ("Environment", settings.environment),
        ("TapDB Env", ctx.env),
        ("TapDB Namespace", ctx.database_name),
        ("TapDB Config", ctx.config_path or "(derived)"),
        ("AWS Profile", os.environ.get("AWS_PROFILE", ctx.aws_profile)),
        ("AWS Region", os.environ.get("AWS_REGION", ctx.aws_region)),
        ("Conda Env", os.environ.get("CONDA_DEFAULT_ENV", "(not set)")),
    ]

    try:
        db_cfg = get_tapdb_db_config()
        rows.append(
            (
                "TapDB Target",
                f"{db_cfg['host']}:{db_cfg['port']}/{db_cfg['database']}",
            )
        )
    except Exception as exc:
        rows.append(("TapDB Target", f"(unresolved: {exc})"))

    try:
        rows.append(("daylily-tapdb", assert_tapdb_version()))
    except Exception as exc:
        rows.append(("daylily-tapdb", f"invalid ({exc})"))

    from bloom_lims.cli.server import server_status_label

    rows.append(("Dev Server", server_status_label()))
    return rows


spec = CliSpec(
    prog_name="bloom",
    app_display_name="BLOOM LIMS",
    dist_name="bloom_lims",
    root_help="BLOOM LIMS — Development CLI for the laboratory information management system.",
    xdg=XdgSpec(
        app_dir_name=f"bloom-{_resolve_deployment_code()}",
    ),
    policy=PolicySpec(),
    config=ConfigSpec(
        xdg_relative_path=f"bloom-config-{_resolve_deployment_code()}.yaml",
        template_bytes=build_default_config_template(),
        validator=_validate_bloom_config,
    ),
    env=EnvSpec(
        active_env_var="BLOOM_ACTIVE",
        project_root_env_var="BLOOM_ROOT",
        activate_script_name=f"{ACTIVATE_SCRIPT} <deploy-name>",
        deactivate_script_name=DEACTIVATE_SCRIPT,
    ),
    plugins=PluginSpec(
        explicit=[
            "bloom_lims.cli.server.register",
            "bloom_lims.cli.db.register",
            "bloom_lims.cli.test.register",
            "bloom_lims.cli.quality.register",
            "bloom_lims.cli.users.register",
            "bloom_lims.cli.integrations.register",
            "bloom_lims.cli.config_extra.register",
        ],
    ),
    info_hooks=[_bloom_info_hook],
)


def build_app():
    """Create a fresh Typer app for Bloom."""
    return _create_app(spec)


app = build_app()

_SKIP_CONDA_ENV_CHECK_FLAG = "--skip-conda-env-check"
_CONDA_ENV_CHECK_EXEMPT_COMMANDS = frozenset({"version", "info", "env", "help"})


def _strip_skip_conda_env_check_flag(args: list[str]) -> tuple[list[str], bool]:
    filtered = [arg for arg in args if arg != _SKIP_CONDA_ENV_CHECK_FLAG]
    return filtered, len(filtered) != len(args)


def _command_requires_conda_env_check(args: list[str]) -> bool:
    if not args or "--help" in args or "-h" in args:
        return False
    for arg in args:
        if not arg or arg.startswith("-"):
            continue
        return arg not in _CONDA_ENV_CHECK_EXEMPT_COMMANDS
    return False


def _enforce_conda_env_contract(args: list[str]) -> None:
    if not _command_requires_conda_env_check(args):
        return
    active_env = os.environ.get("CONDA_DEFAULT_ENV", "").strip()
    if not active_env:
        raise SystemExit(
            "Bloom CLI requires an active deployment-scoped conda environment. "
            "Activate an env named like 'BLOOM-local2', or pass "
            "--skip-conda-env-check to override."
        )
    if "-" not in active_env:
        raise SystemExit(
            f"Bloom CLI requires a deployment-scoped conda environment name with '-'. "
            f"Current CONDA_DEFAULT_ENV='{active_env}'. Pass --skip-conda-env-check to override."
        )


def main() -> None:
    """Main CLI entry point."""
    args, skip_conda_env_check = _strip_skip_conda_env_check_flag(sys.argv[1:])
    if not skip_conda_env_check:
        _enforce_conda_env_contract(args)
    raise SystemExit(run(spec, args))


if __name__ == "__main__":
    main()
