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
    apply_runtime_environment,
    get_settings,
    get_tapdb_db_config,
)
from bloom_lims.core.template_seed import seed_bloom_templates

db_app = typer.Typer(help="Database management commands routed through daylily-tapdb.")
console = Console()

_DEFAULT_AUDIT_LOG_EUID_PREFIX = "TAG"


def _bloom_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_tapdb_schema_source() -> Path | None:
    """Locate tapdb_schema.sql from installed package or local dev checkouts."""
    candidates: list[Path] = []

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

    root = _bloom_root()
    candidates.extend(
        [
            root.parent / "daylily-tapdb" / "schema" / "tapdb_schema.sql",
            root.parent / "daylily" / "daylily-tapdb" / "schema" / "tapdb_schema.sql",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
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
    env.setdefault("TAPDB_ENV", ctx.env)
    env.setdefault("TAPDB_DATABASE_NAME", ctx.database_name)
    if ctx.config_path:
        env.setdefault("TAPDB_CONFIG_PATH", ctx.config_path)
    env.setdefault("AWS_PROFILE", ctx.aws_profile)
    env.setdefault("AWS_REGION", ctx.aws_region)
    env.setdefault("AWS_DEFAULT_REGION", ctx.aws_region)
    return env


def _current_env() -> str:
    return _runtime_env().get("TAPDB_ENV", "dev").strip().lower()


def _local_pg_port(env_name: str) -> str:
    env = _runtime_env()
    scoped_key = f"TAPDB_{env_name.upper()}_PORT"
    return (
        env.get(scoped_key) or env.get("BLOOM_TAPDB_LOCAL_PG_PORT") or "5566"
    ).strip()


def _local_ui_port(env_name: str) -> str:
    env = _runtime_env()
    scoped_key = f"TAPDB_{env_name.upper()}_UI_PORT"
    return (env.get(scoped_key) or env.get("BLOOM_UI_PORT") or "8912").strip()


def _tapdb_audit_log_euid_prefix(env_name: str) -> str:
    env = _runtime_env()
    scoped_key = f"TAPDB_{env_name.upper()}_AUDIT_LOG_EUID_PREFIX"
    return (
        env.get(scoped_key)
        or env.get("BLOOM_TAPDB_AUDIT_LOG_EUID_PREFIX")
        or _DEFAULT_AUDIT_LOG_EUID_PREFIX
    ).strip()


def _tapdb_support_email(env_name: str) -> str:
    env = _runtime_env()
    scoped_key = f"TAPDB_{env_name.upper()}_SUPPORT_EMAIL"
    return (
        env.get(scoped_key)
        or env.get("BLOOM_UI__SUPPORT_EMAIL")
        or get_settings().ui.support_email
    ).strip()


def _tapdb_namespace_config_path(client_id: str, database_name: str) -> Path:
    env = _runtime_env()
    explicit_path = (env.get("TAPDB_CONFIG_PATH") or "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()
    return (
        Path.home()
        / ".config"
        / "tapdb"
        / client_id
        / database_name
        / "tapdb-config.yaml"
    )


def _normalize_tapdb_namespace_config(
    env_name: str, client_id: str, database_name: str
) -> None:
    import yaml

    config_path = _tapdb_namespace_config_path(client_id, database_name)
    if not config_path.exists():
        return

    with config_path.open(encoding="utf-8") as handle:
        root = yaml.safe_load(handle) or {}
    if not isinstance(root, dict):
        return

    envs = root.get("environments")
    if not isinstance(envs, dict):
        return

    env_cfg = envs.get(env_name)
    if not isinstance(env_cfg, dict):
        return

    updated = False
    if not str(env_cfg.get("audit_log_euid_prefix") or "").strip():
        env_cfg["audit_log_euid_prefix"] = _tapdb_audit_log_euid_prefix(env_name)
        updated = True
    if not str(env_cfg.get("support_email") or "").strip():
        env_cfg["support_email"] = _tapdb_support_email(env_name)
        updated = True
    if not updated:
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(root, handle, sort_keys=False)


def _run_tapdb(args: list[str], check: bool = True) -> int:
    cmd = _tapdb_base_cmd() + args
    env = _runtime_env()
    result = subprocess.run(cmd, env=env)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def _ensure_tapdb_namespace_config(env_name: str) -> None:
    """Initialize TapDB namespaced config so first-run bootstrap works in clean homes."""
    env = _runtime_env()
    client_id = (env.get("TAPDB_CLIENT_ID") or "").strip()
    database_name = (env.get("TAPDB_DATABASE_NAME") or "").strip()
    if not client_id or not database_name:
        return

    args = [
        "config",
        "init",
        "--client-id",
        client_id,
        "--database-name",
        database_name,
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
    _normalize_tapdb_namespace_config(env_name, client_id, database_name)


def _seed_bloom_templates() -> None:
    """Seed Bloom legacy template configs into TAPDB generic_template."""
    summary = seed_bloom_templates()
    console.print(
        "[cyan]Bloom template seed:[/cyan] "
        f"loaded={summary.templates_loaded}, "
        f"inserted={summary.inserted}, "
        f"updated={summary.updated}, "
        f"prefixes={summary.prefixes_ensured}"
    )


def _seed_tapdb_templates(
    env_name: str,
    *,
    include_workflow: bool = False,
    overwrite: bool = False,
) -> None:
    """Seed TAPDB templates (TapDB core config is always included by TapDB)."""
    tapdb_config_dir = os.environ.get("TAPDB_SEED_CONFIG_PATH", "").strip()
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


@db_app.command("init")
def db_init(
    force: bool = typer.Option(False, "--force", "-f", help="Force re-initialization"),
) -> None:
    """Initialize database/runtime via tapdb orchestration."""
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
        _seed_bloom_templates()
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
    _seed_bloom_templates()


@db_app.command("auth-setup")
def db_auth_setup(
    pool_name: str = typer.Option(
        "", "--pool-name", help="Optional Cognito pool name override"
    ),
    region: str = typer.Option(
        "us-east-1", "--region", help="AWS region for Cognito setup"
    ),
    port: int = typer.Option(8912, "--port", help="Bloom HTTPS port"),
    domain_prefix: str = typer.Option(
        "",
        "--domain-prefix",
        help="Optional Cognito Hosted UI domain prefix override",
    ),
) -> None:
    """Create/reuse Cognito app client for BLOOM with fixed app name 'bloom'."""
    env_name = _current_env()
    callback_url = f"https://localhost:{port}/auth/callback"
    logout_url = f"https://localhost:{port}/"
    args = [
        "cognito",
        "setup",
        env_name,
        "--client-name",
        "bloom",
        "--callback-url",
        callback_url,
        "--logout-url",
        logout_url,
        "--region",
        region,
    ]
    if pool_name.strip():
        args.extend(["--pool-name", pool_name.strip()])
    if domain_prefix.strip():
        args.extend(["--domain-prefix", domain_prefix.strip()])

    console.print(
        "[cyan]Configuring Cognito for BLOOM[/cyan] "
        f"(env={env_name}, client-name=bloom, callback={callback_url})"
    )
    _run_tapdb(args)


@db_app.command("start")
def db_start() -> None:
    """Start runtime PostgreSQL service via tapdb."""
    env_name = _current_env()
    if env_name in {"dev", "test"}:
        _run_tapdb(["pg", "start-local", env_name, "--port", _local_pg_port(env_name)])
    else:
        _run_tapdb(["pg", "start"])


@db_app.command("stop")
def db_stop() -> None:
    """Stop runtime PostgreSQL service via tapdb."""
    env_name = _current_env()
    if env_name in {"dev", "test"}:
        _run_tapdb(["pg", "stop-local", env_name])
    else:
        _run_tapdb(["pg", "stop"])


@db_app.command("status")
def db_status() -> None:
    """Show schema/database status via tapdb."""
    env_name = _current_env()
    _run_tapdb(["info"])
    _run_tapdb(["db", "schema", "status", env_name])


@db_app.command("migrate")
def db_migrate(
    revision: str = typer.Option(
        "head", "--revision", help="Ignored; tapdb manages migrations"
    ),
) -> None:
    """Run schema migrations via tapdb."""
    env_name = _current_env()
    if revision != "head":
        console.print(
            "[yellow]Revision argument is ignored; using tapdb managed migrations.[/yellow]"
        )
    _ensure_schema_available_for_bloom_root()
    _run_tapdb(["db", "schema", "migrate", env_name])


@db_app.command("seed")
def db_seed() -> None:
    """Seed template data via tapdb."""
    env_name = _current_env()
    _seed_tapdb_templates(env_name, include_workflow=False, overwrite=False)
    _seed_bloom_templates()


@db_app.command("shell")
def db_shell() -> None:
    """Show active DB target and open Aurora connection when applicable."""
    env_name = _current_env()
    cfg = get_tapdb_db_config(env_name=env_name)
    console.print(
        f"[bold]Active TapDB target:[/bold] {cfg['host']}:{cfg['port']}/{cfg['database']}"
    )
    if cfg.get("engine_type") == "aurora":
        _run_tapdb(["aurora", "connect", env_name])
        return

    console.print(
        "[yellow]Use `tapdb info` for current context and target details.[/yellow]"
    )
    _run_tapdb(["info"])


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
    _seed_bloom_templates()


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register the db command group."""
    registry.add_typer_app(None, db_app, "db", "Database management commands.")
