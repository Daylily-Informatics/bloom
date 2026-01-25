"""Database management commands for BLOOM CLI."""

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

console = Console()

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# PostgreSQL settings (match install_postgres.sh)
PGDATA = PROJECT_ROOT / "bloom_lims" / "database"
PGPORT = os.environ.get("PGPORT", "5445")
PGHOST = os.environ.get("PGHOST", "localhost")
PGDATABASE = os.environ.get("PGDATABASE", "bloom")


def _get_database_url() -> str:
    """Get or build DATABASE_URL."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("PGUSER", "bloom")
    return f"postgresql://{user}@{PGHOST}:{PGPORT}/{PGDATABASE}"


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


@click.group()
def db():
    """Database management commands."""
    pass


@db.command("start")
def db_start():
    """Start PostgreSQL server."""
    if not PGDATA.exists():
        console.print("[yellow]PostgreSQL data directory not found.[/yellow]")
        console.print("Run [cyan]source bloom_lims/env/install_postgres.sh[/cyan] to initialize.")
        raise SystemExit(1)

    if _is_pg_running():
        console.print(f"[green]✓[/green] PostgreSQL is already running on port {PGPORT}")
        return

    console.print(f"[cyan]Starting PostgreSQL on port {PGPORT}...[/cyan]")
    log_file = PGDATA / "postgresql.log"
    result = subprocess.run(
        ["pg_ctl", "-D", str(PGDATA), "-l", str(log_file), "-o", f"-p {PGPORT}", "start"],
        cwd=PROJECT_ROOT,
    )

    if result.returncode == 0:
        console.print(f"[green]✓[/green] PostgreSQL started")
        console.print(f"   DATABASE_URL=[cyan]{_get_database_url()}[/cyan]")
    else:
        console.print("[red]✗[/red] Failed to start PostgreSQL")
        raise SystemExit(1)


@db.command("stop")
def db_stop():
    """Stop PostgreSQL server."""
    if not PGDATA.exists():
        console.print(f"[red]PostgreSQL data directory not found at {PGDATA}[/red]")
        raise SystemExit(1)

    console.print("[cyan]Stopping PostgreSQL...[/cyan]")
    result = subprocess.run(
        ["pg_ctl", "-D", str(PGDATA), "stop", "-m", "fast"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        console.print("[green]✓[/green] PostgreSQL stopped")
    else:
        console.print("[yellow]⚠[/yellow] PostgreSQL was not running")


@db.command("status")
def db_status():
    """Show database status."""
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.config import get_settings

        settings = get_settings()
        console.print(f"[bold]Database Configuration:[/bold]")
        console.print(f"  Host: {settings.database.host}:{settings.database.port}")
        console.print(f"  Database: {settings.database.database}")
        console.print(f"  User: {settings.database.user}")
        console.print(f"  Pool Size: {settings.database.pool_size}")

        # Test connection
        with BLOOMdb3(echo_sql=False) as bdb:
            from sqlalchemy import text
            result = bdb.session.execute(text("SELECT 1")).fetchone()
            if result:
                console.print(f"\n[green]✓[/green] Database connection successful")

                # Get table counts
                for table in ['generic_template', 'generic_instance', 'generic_instance_lineage']:
                    count_result = bdb.session.execute(
                        text(f"SELECT COUNT(*) FROM {table}")
                    ).fetchone()
                    console.print(f"  {table}: {count_result[0]} rows")

    except Exception as e:
        console.print(f"[red]✗[/red] Database connection failed: {e}")
        raise SystemExit(1)


@db.command("migrate")
@click.option('--revision', default='head', help='Target revision (default: head)')
def db_migrate(revision):
    """Run database migrations."""
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, revision)
        console.print("[green]✓[/green] Migrations completed successfully")
    except Exception as e:
        console.print(f"[red]✗[/red] Migration failed: {e}")
        raise SystemExit(1)


@db.command("seed")
def db_seed():
    """Load seed data from template JSON files."""
    console.print("[cyan]Seeding database from templates...[/cyan]")
    seed_script = PROJECT_ROOT / "bloom_lims" / "env" / "seed_db_containersGeneric.py"
    
    if not seed_script.exists():
        console.print(f"[red]✗[/red] Seed script not found: {seed_script}")
        raise SystemExit(1)
    
    result = subprocess.run([sys.executable, str(seed_script)], cwd=PROJECT_ROOT)
    
    if result.returncode == 0:
        console.print("[green]✓[/green] Seed complete")
    else:
        console.print("[red]✗[/red] Seed failed")
        raise SystemExit(result.returncode)


@db.command("shell")
def db_shell():
    """Open psql shell connected to BLOOM database."""
    console.print(f"[cyan]Connecting to {PGDATABASE} on port {PGPORT}...[/cyan]")
    os.execvp("psql", ["psql", "-h", PGHOST, "-p", PGPORT, "-d", PGDATABASE])


@db.command("reset")
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation')
def db_reset(yes):
    """Drop and rebuild database (DESTRUCTIVE)."""
    if not yes:
        console.print("[yellow]⚠️  WARNING: This will DROP ALL DATA and reset the database![/yellow]")
        console.print("[yellow]This action cannot be undone.[/yellow]")
        console.print()
        if not click.confirm("Are you sure you want to continue?"):
            console.print("[dim]Aborted.[/dim]")
            return

    console.print("[cyan]Resetting database...[/cyan]")

    # Run the clear and rebuild script
    rebuild_script = PROJECT_ROOT / "bloom_lims" / "env" / "clear_and_rebuild_postgres.sh"

    if rebuild_script.exists():
        console.print("  [yellow]→[/yellow] Running clear_and_rebuild_postgres.sh...")
        result = subprocess.run(["bash", str(rebuild_script)], cwd=PROJECT_ROOT)
        if result.returncode == 0:
            console.print("[green]✓[/green] Database reset complete!")
        else:
            console.print("[red]✗[/red] Database reset failed")
            raise SystemExit(1)
    else:
        console.print(f"[red]✗[/red] Reset script not found: {rebuild_script}")
        raise SystemExit(1)

