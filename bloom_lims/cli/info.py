"""Information and diagnostic commands for BLOOM CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bloom_lims.config import (
    apply_runtime_environment,
    assert_tapdb_version,
    get_settings,
    get_tapdb_db_config,
)

console = Console()
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _get_version() -> str:
    try:
        from bloom_lims._version import get_version

        return get_version()
    except ImportError:
        return "dev"


def _tapdb_cmd(args: list[str]) -> subprocess.CompletedProcess:
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
        [sys.executable, "-m", "daylily_tapdb.cli"] + args,
        env=runtime,
        capture_output=True,
        text=True,
    )


@click.command()
def version():
    """Show BLOOM version."""
    console.print(f"bloom [cyan]{_get_version()}[/cyan]")


@click.command()
def info():
    """Show BLOOM configuration and runtime info."""
    settings = get_settings()
    ctx = apply_runtime_environment(settings)
    db_cfg = get_tapdb_db_config()

    table = Table(title="BLOOM LIMS Info")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    table.add_row("Version", _get_version())
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Project Root", str(PROJECT_ROOT))
    table.add_row("Environment", settings.environment)
    table.add_row("TapDB Env", ctx.env)
    table.add_row("TapDB Namespace", ctx.database_name)
    table.add_row("TapDB Target", f"{db_cfg['host']}:{db_cfg['port']}/{db_cfg['database']}")
    table.add_row("AWS Profile", os.environ.get("AWS_PROFILE", ctx.aws_profile))
    table.add_row("AWS Region", os.environ.get("AWS_REGION", ctx.aws_region))

    try:
        table.add_row("daylily-tapdb", assert_tapdb_version())
    except Exception as exc:
        table.add_row("daylily-tapdb", f"[red]invalid[/red] ({exc})")

    conda_env = os.environ.get("CONDA_DEFAULT_ENV", "[dim]not set[/dim]")
    table.add_row("Conda Env", conda_env)

    console.print(table)


@click.command()
def status():
    """Check DB/runtime status via tapdb."""
    result = _tapdb_cmd(["db", "schema", "status", apply_runtime_environment(get_settings()).env])
    if result.returncode == 0:
        console.print(result.stdout.strip())
    else:
        console.print(result.stdout.strip())
        console.print(result.stderr.strip())
        raise SystemExit(result.returncode)


@click.command()
def doctor():
    """Verify environment, dependencies, and configuration."""
    console.print("[bold]BLOOM Doctor - Environment Check[/bold]")
    console.print()

    issues: list[str] = []
    warnings: list[str] = []

    py_version = sys.version_info
    if py_version >= (3, 12):
        console.print(f"[green]✓[/green] Python {py_version.major}.{py_version.minor}")
    else:
        issues.append(f"Python 3.12+ required, found {py_version.major}.{py_version.minor}")
        console.print(f"[red]✗[/red] Python {py_version.major}.{py_version.minor} (3.12+ required)")

    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    if conda_env == "BLOOM":
        console.print("[green]✓[/green] Conda environment: BLOOM")
    else:
        warnings.append(f"Not in BLOOM conda environment (current: {conda_env})")
        console.print(f"[yellow]⚠[/yellow] Conda environment: {conda_env or 'none'} (expected: BLOOM)")

    for module_name in ["bloom_lims.db", "bloom_lims.config", "daylily_tapdb"]:
        try:
            __import__(module_name)
            console.print(f"[green]✓[/green] Import: {module_name}")
        except ImportError as exc:
            issues.append(f"Cannot import {module_name}: {exc}")
            console.print(f"[red]✗[/red] Import: {module_name}")

    try:
        tapdb_version = assert_tapdb_version()
        console.print(f"[green]✓[/green] daylily-tapdb version: {tapdb_version}")
    except Exception as exc:
        issues.append(str(exc))
        console.print(f"[red]✗[/red] daylily-tapdb version check failed: {exc}")

    env_name = apply_runtime_environment(get_settings()).env
    result = _tapdb_cmd(["db", "schema", "status", env_name])
    if result.returncode == 0:
        console.print("[green]✓[/green] TapDB connectivity and schema status")
    else:
        issues.append("TapDB schema status check failed")
        console.print("[red]✗[/red] TapDB schema status")
        if result.stderr:
            warnings.append(result.stderr.strip())

    from bloom_lims.config import validate_settings

    for warning in validate_settings():
        warnings.append(f"Config: {warning}")

    console.print()
    if issues:
        console.print(f"[red]Found {len(issues)} issue(s):[/red]")
        for issue in issues:
            console.print(f"  [red]•[/red] {issue}")
    if warnings:
        console.print(f"[yellow]Found {len(warnings)} warning(s):[/yellow]")
        for warning in warnings:
            console.print(f"  [yellow]•[/yellow] {warning}")
    if not issues and not warnings:
        console.print("[green]✓ All checks passed![/green]")

    if issues:
        raise SystemExit(1)
