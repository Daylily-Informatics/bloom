"""Information and diagnostic commands for BLOOM CLI."""

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
PGDATA = PROJECT_ROOT / "bloom_lims" / "database"


def _get_version() -> str:
    """Get version from _version module."""
    try:
        from bloom_lims._version import get_version
        return get_version()
    except ImportError:
        return "dev"


def _is_pg_running() -> bool:
    """Check if PostgreSQL is running."""
    if not PGDATA.exists():
        return False
    result = subprocess.run(
        ["pg_ctl", "-D", str(PGDATA), "status"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@click.command()
def version():
    """Show BLOOM version."""
    console.print(f"bloom [cyan]{_get_version()}[/cyan]")


@click.command()
def info():
    """Show BLOOM configuration and environment info."""
    from bloom_lims.config import get_settings, USER_CONFIG_FILE
    
    settings = get_settings()
    
    table = Table(title="BLOOM LIMS Info")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    # Version
    table.add_row("Version", _get_version())

    # Python
    table.add_row("Python", sys.version.split()[0])

    # Project root
    table.add_row("Project Root", str(PROJECT_ROOT))

    # Environment
    table.add_row("Environment", settings.environment)

    # Config file
    if USER_CONFIG_FILE.exists():
        table.add_row("Config File", str(USER_CONFIG_FILE))
    else:
        table.add_row("Config File", "[dim]not found (using defaults)[/dim]")

    # Database
    db_url = f"{settings.database.host}:{settings.database.port}/{settings.database.database}"
    table.add_row("Database", db_url)

    # Conda environment
    conda_env = os.environ.get("CONDA_DEFAULT_ENV", "[dim]not set[/dim]")
    table.add_row("Conda Env", conda_env)

    console.print(table)


@click.command()
def status():
    """Check status of all BLOOM services."""
    console.print("[bold]BLOOM Service Status[/bold]")
    console.print()

    # Check PostgreSQL
    if PGDATA.exists():
        if _is_pg_running():
            console.print("[green]●[/green] PostgreSQL: [green]running[/green]")
        else:
            console.print("[dim]○[/dim] PostgreSQL: [dim]stopped[/dim]")
    else:
        console.print("[yellow]○[/yellow] PostgreSQL: [yellow]not initialized[/yellow]")

    # Check database connection
    try:
        from bloom_lims.db import BLOOMdb3
        from sqlalchemy import text
        with BLOOMdb3(echo_sql=False) as bdb:
            bdb.session.execute(text("SELECT 1"))
        console.print("[green]●[/green] Database: [green]connected[/green]")
    except Exception as e:
        console.print(f"[red]●[/red] Database: [red]error[/red] - {e}")

    # Check conda environment
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    if conda_env == "BLOOM":
        console.print("[green]●[/green] Conda Env: [green]BLOOM active[/green]")
    elif conda_env:
        console.print(f"[yellow]●[/yellow] Conda Env: [yellow]{conda_env} (expected BLOOM)[/yellow]")
    else:
        console.print("[dim]○[/dim] Conda Env: [dim]not activated[/dim]")


@click.command()
def doctor():
    """Verify environment, dependencies, and configuration."""
    console.print("[bold]BLOOM Doctor - Environment Check[/bold]")
    console.print()
    
    issues = []
    warnings = []

    # Check Python version
    py_version = sys.version_info
    if py_version >= (3, 12):
        console.print(f"[green]✓[/green] Python {py_version.major}.{py_version.minor}")
    else:
        issues.append(f"Python 3.12+ required, found {py_version.major}.{py_version.minor}")
        console.print(f"[red]✗[/red] Python {py_version.major}.{py_version.minor} (3.12+ required)")

    # Check conda environment
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    if conda_env == "BLOOM":
        console.print("[green]✓[/green] Conda environment: BLOOM")
    else:
        warnings.append(f"Not in BLOOM conda environment (current: {conda_env})")
        console.print(f"[yellow]⚠[/yellow] Conda environment: {conda_env or 'none'} (expected: BLOOM)")

    # Check key imports
    for module_name in ["bloom_lims.db", "bloom_lims.config", "daylily_tapdb"]:
        try:
            __import__(module_name)
            console.print(f"[green]✓[/green] Import: {module_name}")
        except ImportError as e:
            issues.append(f"Cannot import {module_name}: {e}")
            console.print(f"[red]✗[/red] Import: {module_name}")

    # Check PostgreSQL
    if PGDATA.exists():
        if _is_pg_running():
            console.print("[green]✓[/green] PostgreSQL: running")
        else:
            warnings.append("PostgreSQL not running")
            console.print("[yellow]⚠[/yellow] PostgreSQL: stopped (run: bloom db start)")
    else:
        warnings.append("PostgreSQL not initialized")
        console.print("[yellow]⚠[/yellow] PostgreSQL: not initialized")

    # Check database connection
    try:
        from bloom_lims.db import BLOOMdb3
        from sqlalchemy import text
        with BLOOMdb3(echo_sql=False) as bdb:
            bdb.session.execute(text("SELECT 1"))
        console.print("[green]✓[/green] Database connection")
    except Exception as e:
        issues.append(f"Database connection failed: {e}")
        console.print(f"[red]✗[/red] Database connection")

    # Check config
    try:
        from bloom_lims.config import get_settings, validate_settings
        settings = get_settings()
        config_warnings = validate_settings()
        console.print("[green]✓[/green] Configuration loaded")
        for w in config_warnings:
            warnings.append(f"Config: {w}")
    except Exception as e:
        issues.append(f"Configuration error: {e}")
        console.print(f"[red]✗[/red] Configuration")

    # Summary
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

