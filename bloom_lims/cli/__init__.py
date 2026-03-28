"""BLOOM LIMS CLI — built on cli-core-yo."""

from __future__ import annotations

import os
from pathlib import Path

from cli_core_yo.app import create_app as _create_app
from cli_core_yo.app import run
from cli_core_yo.spec import CliSpec, ConfigSpec, PluginSpec, XdgSpec

from bloom_lims.config import (
    apply_runtime_environment,
    assert_tapdb_version,
    get_settings,
    get_tapdb_db_config,
    validate_config_content,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        app_dir_name="bloom",
    ),
    config=ConfigSpec(
        primary_filename="config.yaml",
        template_resource=("bloom_lims", "etc/bloom-config-template.yaml"),
        validator=_validate_bloom_config,
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


def main() -> None:
    """Main CLI entry point."""
    raise SystemExit(run(spec))


if __name__ == "__main__":
    main()
