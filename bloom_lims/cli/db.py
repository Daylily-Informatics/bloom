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


@db.command("init")
@click.option('--force', '-f', is_flag=True, help='Force re-initialization (removes existing data)')
def db_init(force):
    """Initialize PostgreSQL database from scratch.

    This runs the full installation script which:
    - Initializes PostgreSQL data directory
    - Creates the bloom database and role
    - Applies TapDB schema
    - Applies BLOOM prefix sequences
    - Seeds the database with templates
    """
    install_script = PROJECT_ROOT / "bloom_lims" / "env" / "install_postgres.sh"

    if not install_script.exists():
        console.print(f"[red]✗[/red] Install script not found: {install_script}")
        raise SystemExit(1)

    # Check if database already exists
    if PGDATA.exists():
        if not force:
            console.print(f"[yellow]⚠[/yellow] PostgreSQL data directory already exists at:")
            console.print(f"   {PGDATA}")
            console.print()
            console.print("Options:")
            console.print("  • Use [cyan]bloom db init --force[/cyan] to remove and reinitialize")
            console.print("  • Use [cyan]bloom db reset[/cyan] to clear data but keep the database")
            console.print("  • Use [cyan]bloom db start[/cyan] if the database is already set up")
            raise SystemExit(1)
        else:
            console.print("[yellow]⚠[/yellow] Removing existing database...")
            # Stop PostgreSQL if running
            if _is_pg_running():
                subprocess.run(
                    ["pg_ctl", "-D", str(PGDATA), "stop", "-m", "fast"],
                    capture_output=True,
                )
            # Remove data directory
            import shutil
            shutil.rmtree(PGDATA)
            console.print("[green]✓[/green] Existing database removed")

    console.print("[cyan]Initializing PostgreSQL database...[/cyan]")
    console.print()

    # Run the install script with 'skip' argument (skips conda env creation)
    # We need to source it in a bash shell
    result = subprocess.run(
        ["bash", "-c", f"source {install_script} skip"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PGDATA": str(PGDATA)},
    )

    if result.returncode == 0:
        console.print()
        console.print("[green]✓[/green] Database initialization complete!")
        console.print()
        console.print("Next steps:")
        console.print("  • [cyan]bloom db status[/cyan]  - Verify database connection")
        console.print("  • [cyan]bloom gui[/cyan]        - Start the web UI")
    else:
        console.print()
        console.print("[red]✗[/red] Database initialization failed")
        console.print("Check the output above for errors.")
        raise SystemExit(1)


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
    seed_script = PROJECT_ROOT / "seed_db_containersGeneric.py"

    if not seed_script.exists():
        console.print(f"[red]✗[/red] Seed script not found: {seed_script}")
        raise SystemExit(1)

    # Seed actions first (required by other templates)
    config_dir = PROJECT_ROOT / "bloom_lims" / "config"
    action_files = sorted(config_dir.glob("*/action/*.json"))
    other_files = sorted([f for f in config_dir.glob("*/*.json")
                          if "/action/" not in str(f) and f.name != "metadata.json"])

    console.print(f"  Seeding {len(action_files)} action templates...")
    for json_file in action_files:
        result = subprocess.run(
            [sys.executable, str(seed_script), str(json_file)],
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            console.print(f"[red]✗[/red] Failed to seed: {json_file.name}")
            raise SystemExit(result.returncode)

    console.print(f"  Seeding {len(other_files)} other templates...")
    for json_file in other_files:
        result = subprocess.run(
            [sys.executable, str(seed_script), str(json_file)],
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            console.print(f"[red]✗[/red] Failed to seed: {json_file.name}")
            raise SystemExit(result.returncode)

    console.print("[green]✓[/green] Seed complete")


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

    # Run the clear and rebuild script (located in project root)
    rebuild_script = PROJECT_ROOT / "clear_and_rebuild_postgres.sh"

    if rebuild_script.exists():
        console.print("  [yellow]→[/yellow] Running clear_and_rebuild_postgres.sh...")
        # Pass --yes flag if user confirmed
        cmd = ["bash", str(rebuild_script)]
        if yes:
            cmd.append("--yes")
        result = subprocess.run(cmd, cwd=PROJECT_ROOT)
        if result.returncode == 0:
            console.print("[green]✓[/green] Database reset complete!")
        else:
            console.print("[red]✗[/red] Database reset failed")
            raise SystemExit(1)
    else:
        console.print(f"[red]✗[/red] Reset script not found: {rebuild_script}")
        raise SystemExit(1)

