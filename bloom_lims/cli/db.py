"""Database management commands for BLOOM CLI (TapDB-orchestrated)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from bloom_lims.config import (
    DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT,
    DEFAULT_BLOOM_WEB_PORT,
    apply_runtime_environment,
    get_settings,
)

db_app = typer.Typer(help="Database management commands routed through daylily-tapdb.")
console = Console()

_DEFAULT_AUDIT_LOG_EUID_PREFIX = "BGX"
_DEFAULT_TAPDB_CLIENT_ID = "bloom"
_DEFAULT_TAPDB_DATABASE_NAME = "bloom"
_DEFAULT_TAPDB_EUID_CLIENT_CODE = "B"
_DEFAULT_MERIDIAN_DOMAIN_CODE = "B"
_DEFAULT_TAPDB_APP_CODE = "B"


def _bloom_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_dayhoff_artifact_path(path: Path) -> bool:
    return ".dayhoff/local" in str(path)


def _resolve_tapdb_schema_source() -> Path | None:
    """Locate tapdb_schema.sql from installed package or local dev checkouts."""
    candidates: list[Path] = []

    root = _bloom_root()
    candidates.extend(
        [
            root.parent / "daylily-tapdb" / "schema" / "tapdb_schema.sql",
            root.parent / "daylily" / "daylily-tapdb" / "schema" / "tapdb_schema.sql",
        ]
    )

    try:
        tapdb_pkg = importlib.import_module("daylily_tapdb")
        pkg_file = Path(tapdb_pkg.__file__).resolve()
        candidates.extend(
            [
                pkg_file.parents[1] / "schema" / "tapdb_schema.sql",
                pkg_file.parents[2] / "schema" / "tapdb_schema.sql",
            ]
        )
    except Exception:
        pass

    for candidate in candidates:
        if candidate.exists() and not _is_dayhoff_artifact_path(candidate):
            return candidate
    return None


def _ensure_schema_available_for_bloom_root() -> None:
    """Ensure tapdb schema is visible when running tapdb from bloom repo root."""
    target = _bloom_root() / "schema" / "tapdb_schema.sql"
    if target.exists():
        return

    source = _resolve_tapdb_schema_source()
    if source is None:
        return

    if target.is_symlink():
        target.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source)
    except Exception:
        if target.exists() or target.is_symlink():
            target.unlink()
        shutil.copy2(source, target)


def _tapdb_base_cmd() -> list[str]:
    """Run tapdb via module entrypoint to avoid PATH dependency issues."""
    return [sys.executable, "-m", "daylily_tapdb.cli"]


def _runtime_env() -> dict[str, str]:
    """Build normalized runtime env for tapdb commands."""
    settings = get_settings()
    ctx = apply_runtime_environment(settings)

    env = os.environ.copy()
    env["AWS_PROFILE"] = ctx.aws_profile
    env["AWS_REGION"] = ctx.aws_region
    env["AWS_DEFAULT_REGION"] = ctx.aws_region
    env["MERIDIAN_DOMAIN_CODE"] = os.environ.get(
        "MERIDIAN_DOMAIN_CODE", _DEFAULT_MERIDIAN_DOMAIN_CODE
    )
    env["TAPDB_APP_CODE"] = os.environ.get("TAPDB_APP_CODE", _DEFAULT_TAPDB_APP_CODE)
    return env


def _ensure_runtime_config_parent() -> None:
    config_path = (apply_runtime_environment(get_settings()).config_path or "").strip()
    if not config_path:
        return
    Path(config_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _current_env() -> str:
    return apply_runtime_environment(get_settings()).env


def _local_pg_port(env_name: str) -> str:
    settings = get_settings()
    return str(
        settings.tapdb.local_pg_port or DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT
    ).strip()


def _local_ui_port(env_name: str) -> str:
    _ = env_name
    return str(DEFAULT_BLOOM_WEB_PORT).strip()


def _tapdb_audit_log_euid_prefix(env_name: str) -> str:
    _ = env_name
    return _DEFAULT_AUDIT_LOG_EUID_PREFIX


def _tapdb_support_email(env_name: str) -> str:
    _ = env_name
    return get_settings().ui.support_email.strip()


def _update_tapdb_namespace_config(env_name: str) -> None:
    _run_tapdb(
        [
            "config",
            "update",
            "--env",
            env_name,
            "--audit-log-euid-prefix",
            _tapdb_audit_log_euid_prefix(env_name),
            "--support-email",
            _tapdb_support_email(env_name),
        ]
    )


def _run_tapdb(args: list[str], check: bool = True) -> int:
    ctx = apply_runtime_environment(get_settings())
    config_path = str(ctx.config_path or "").strip()
    if not config_path:
        raise RuntimeError(
            "TapDB config path is required. Resolve it via Bloom settings and pass it explicitly "
            "to TapDB with --config."
        )
    cmd = _tapdb_base_cmd() + [
        "--config",
        config_path,
        "--env",
        ctx.env,
    ]
    cmd.extend(args)
    env = _runtime_env()
    result = subprocess.run(cmd, env=env)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def _ensure_tapdb_namespace_config(env_name: str) -> None:
    """Initialize TapDB namespaced config so first-run bootstrap works in clean homes."""
    ctx = apply_runtime_environment(get_settings())
    if not str(ctx.config_path or "").strip():
        return
    _ensure_runtime_config_parent()

    args = [
        "config",
        "init",
        "--client-id",
        _DEFAULT_TAPDB_CLIENT_ID,
        "--database-name",
        _DEFAULT_TAPDB_DATABASE_NAME,
        "--euid-client-code",
        _DEFAULT_TAPDB_EUID_CLIENT_CODE,
        "--env",
        env_name,
    ]
    if env_name in {"dev", "test"}:
        args.extend(
            [
                "--db-port",
                f"{env_name}={_local_pg_port(env_name)}",
                "--ui-port",
                f"{env_name}={_local_ui_port(env_name)}",
            ]
        )
    _run_tapdb(args)
    _update_tapdb_namespace_config(env_name)


def _seed_tapdb_templates(
    env_name: str,
    *,
    include_workflow: bool = False,
    overwrite: bool = False,
) -> None:
    """Seed TAPDB templates (TapDB core config is always included by TapDB)."""
    tapdb_config_dir = str(_bloom_root() / "config" / "tapdb_templates")
    args = ["db", "data", "seed", env_name]
    if tapdb_config_dir:
        args.extend(["--config", tapdb_config_dir])
        console.print(f"[cyan]TapDB template seed config:[/cyan] {tapdb_config_dir}")
    else:
        console.print(
            "[cyan]TapDB template seed:[/cyan] using built-in TapDB core config"
        )
    if include_workflow:
        console.print(
            "[yellow]Workflow overlay seeding is not supported in Bloom.[/yellow]"
        )
    args.append("--overwrite" if overwrite else "--skip-existing")
    _run_tapdb(args)


@db_app.command("build")
def db_build(
    force: bool = typer.Option(False, "--force", "-f", help="Force re-initialization"),
) -> None:
    """Build database/runtime via tapdb orchestration."""
    env_name = _current_env()
    console.print(
        f"[cyan]Initializing BLOOM database via tapdb (env={env_name})...[/cyan]"
    )
    _ensure_tapdb_namespace_config(env_name)

    if env_name in {"dev", "test"}:
        _ensure_schema_available_for_bloom_root()
        local_port = _local_pg_port(env_name)
        console.print(
            f"[cyan]Using local TapDB PostgreSQL port {local_port} for env={env_name}[/cyan]"
        )
        _run_tapdb(["pg", "init", env_name], check=False)
        _run_tapdb(["pg", "start-local", env_name, "--port", local_port])
        setup_args = ["db", "setup", env_name]
        if force:
            setup_args.append("--force")
        _run_tapdb(setup_args)
        _seed_tapdb_templates(env_name, overwrite=force)
        return

    create_args = ["db", "create", env_name]
    if force:
        create_args.append("--force")
    _run_tapdb(create_args, check=False)

    setup_args = ["db", "setup", env_name]
    _ensure_schema_available_for_bloom_root()
    if force:
        setup_args.append("--force")
    _run_tapdb(setup_args)
    _seed_tapdb_templates(env_name, overwrite=force)


@db_app.command("seed")
def db_seed() -> None:
    """Seed template data via tapdb."""
    env_name = _current_env()
    _seed_tapdb_templates(env_name, include_workflow=False, overwrite=False)


@db_app.command("reset")
def db_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Reset schema/data and rebuild via tapdb (destructive)."""
    env_name = _current_env()

    if not yes:
        console.print(
            "[yellow]WARNING: This will drop all data and rebuild the schema.[/yellow]"
        )
        if not typer.confirm("Are you sure you want to continue?"):
            console.print("[dim]Aborted.[/dim]")
            return

    _ensure_schema_available_for_bloom_root()
    _run_tapdb(["db", "schema", "reset", env_name, "--force"])
    _run_tapdb(["db", "setup", env_name, "--force"])
    _seed_tapdb_templates(env_name, include_workflow=False, overwrite=True)


@db_app.command("nuke")
def db_nuke(
    force: bool = typer.Option(
        False, "--force", "-f", help="Force destructive schema reset"
    ),
) -> None:
    """Delete schema only via TapDB."""
    env_name = _current_env()
    _run_tapdb(["db", "schema", "reset", env_name] + (["--force"] if force else []))


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register the db command group."""
    registry.add_typer_app(None, db_app, "db", "Database management commands.")
