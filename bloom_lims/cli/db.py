"""Database management commands for BLOOM CLI (TapDB-orchestrated)."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List

import click
from rich.console import Console

from bloom_lims.core.template_seed import seed_bloom_templates
from bloom_lims.config import (
    apply_runtime_environment,
    get_settings,
    get_tapdb_db_config,
)

console = Console()


def _tapdb_base_cmd() -> List[str]:
    """Run tapdb via module entrypoint to avoid PATH dependency issues."""
    return [sys.executable, "-m", "daylily_tapdb.cli"]


def _runtime_env() -> dict:
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
        env.get(scoped_key)
        or env.get("BLOOM_TAPDB_LOCAL_PG_PORT")
        or "5566"
    ).strip()


def _run_tapdb(args: List[str], check: bool = True) -> int:
    cmd = _tapdb_base_cmd() + args
    env = _runtime_env()
    result = subprocess.run(cmd, env=env)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def _seed_bloom_templates(*, overwrite: bool = False) -> None:
    """Seed Bloom legacy template configs into TAPDB generic_template."""
    summary = seed_bloom_templates(overwrite=overwrite)
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
    include_workflow: bool = True,
    overwrite: bool = False,
) -> None:
    """Seed TAPDB templates (TapDB core config is always included by TapDB)."""
    tapdb_config_dir = os.environ.get("TAPDB_SEED_CONFIG_PATH", "").strip()
    args = ["db", "data", "seed", env_name]
    if tapdb_config_dir:
        args.extend(["--config", tapdb_config_dir])
        console.print(
            f"[cyan]TapDB template seed config:[/cyan] {tapdb_config_dir}"
        )
    else:
        console.print(
            "[cyan]TapDB template seed:[/cyan] using built-in TapDB core config"
        )
    if include_workflow:
        args.append("--include-workflow")
    args.append("--overwrite" if overwrite else "--skip-existing")
    _run_tapdb(args)


@click.group()
def db():
    """Database management commands routed through daylily-tapdb."""
    pass


@db.command("init")
@click.option("--force", "-f", is_flag=True, help="Force re-initialization")
def db_init(force: bool):
    """Initialize database/runtime via tapdb orchestration."""
    env_name = _current_env()
    console.print(f"[cyan]Initializing BLOOM database via tapdb (env={env_name})...[/cyan]")

    if env_name in {"dev", "test"}:
        local_port = _local_pg_port(env_name)
        console.print(
            f"[cyan]Using local TapDB PostgreSQL port {local_port} for env={env_name}[/cyan]"
        )
        _run_tapdb(["pg", "init", env_name], check=False)
        _run_tapdb(["pg", "start-local", env_name, "--port", local_port])
        setup_args = ["db", "setup", env_name, "--include-workflow"]
        if force:
            setup_args.append("--force")
        _run_tapdb(setup_args)
        _seed_tapdb_templates(env_name, include_workflow=True, overwrite=force)
        _seed_bloom_templates(overwrite=force)
        return

    create_args = ["db", "create", env_name]
    if force:
        create_args.append("--force")
    _run_tapdb(create_args, check=False)

    setup_args = ["db", "setup", env_name, "--include-workflow"]
    if force:
        setup_args.append("--force")
    _run_tapdb(setup_args)
    _seed_tapdb_templates(env_name, include_workflow=True, overwrite=force)
    _seed_bloom_templates(overwrite=force)


@db.command("auth-setup")
@click.option("--pool-name", default="", help="Optional Cognito pool name override")
@click.option("--region", default="us-east-1", help="AWS region for Cognito setup")
@click.option("--port", type=int, default=8912, show_default=True, help="Bloom HTTPS port")
@click.option(
    "--domain-prefix",
    default="",
    help="Optional Cognito Hosted UI domain prefix override",
)
def db_auth_setup(pool_name: str, region: str, port: int, domain_prefix: str):
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


@db.command("start")
def db_start():
    """Start runtime PostgreSQL service via tapdb."""
    env_name = _current_env()
    if env_name in {"dev", "test"}:
        _run_tapdb(["pg", "start-local", env_name, "--port", _local_pg_port(env_name)])
    else:
        _run_tapdb(["pg", "start"])


@db.command("stop")
def db_stop():
    """Stop runtime PostgreSQL service via tapdb."""
    env_name = _current_env()
    if env_name in {"dev", "test"}:
        _run_tapdb(["pg", "stop-local", env_name])
    else:
        _run_tapdb(["pg", "stop"])


@db.command("status")
def db_status():
    """Show schema/database status via tapdb."""
    env_name = _current_env()
    _run_tapdb(["info"])
    _run_tapdb(["db", "schema", "status", env_name])


@db.command("migrate")
@click.option("--revision", default="head", help="Ignored; tapdb manages migration targets")
def db_migrate(revision: str):
    """Run schema migrations via tapdb."""
    env_name = _current_env()
    if revision != "head":
        console.print("[yellow]Revision argument is ignored; using tapdb managed migrations.[/yellow]")
    _run_tapdb(["db", "schema", "migrate", env_name])


@db.command("seed")
@click.option("--overwrite", is_flag=True, help="Overwrite/update existing templates")
def db_seed(overwrite: bool):
    """Seed template data via tapdb."""
    env_name = _current_env()
    _seed_tapdb_templates(env_name, include_workflow=True, overwrite=overwrite)
    _seed_bloom_templates(overwrite=overwrite)


@db.command("shell")
def db_shell():
    """Show active DB target and open Aurora connection when applicable."""
    env_name = _current_env()
    cfg = get_tapdb_db_config(env_name=env_name)
    console.print(f"[bold]Active TapDB target:[/bold] {cfg['host']}:{cfg['port']}/{cfg['database']}")
    if cfg.get("engine_type") == "aurora":
        _run_tapdb(["aurora", "connect", env_name])
        return

    console.print("[yellow]Use `tapdb info` for current context and target details.[/yellow]")
    _run_tapdb(["info"])


@db.command("reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def db_reset(yes: bool):
    """Reset schema/data and rebuild via tapdb (DESTRUCTIVE)."""
    env_name = _current_env()

    if not yes:
        console.print("[yellow]⚠️  WARNING: This will DROP ALL DATA and rebuild the schema.[/yellow]")
        if not click.confirm("Are you sure you want to continue?"):
            console.print("[dim]Aborted.[/dim]")
            return

    args = ["db", "schema", "reset", env_name, "--force"]
    _run_tapdb(args)
    setup_args = ["db", "setup", env_name, "--include-workflow", "--force"]
    _run_tapdb(setup_args)
    _seed_tapdb_templates(env_name, include_workflow=True, overwrite=True)
    _seed_bloom_templates(overwrite=True)
