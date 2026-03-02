"""Utility commands for BLOOM CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from bloom_lims.config import apply_runtime_environment, get_settings
from bloom_lims.db import BLOOMdb3
from bloom_lims.domain.base import BloomObj

console = Console()
PROJECT_ROOT = Path(__file__).parent.parent.parent
SERVER_LOG_DIR = Path.home() / ".bloom" / "logs"
TAPDB_LOG_DIR = Path.home() / ".config" / "tapdb" / "logs"


@click.command()
def shell():
    """Open interactive Python shell with BLOOM loaded."""
    console.print("[cyan]Starting BLOOM interactive shell...[/cyan]")
    try:
        import IPython

        bdb = BLOOMdb3()
        bobj = BloomObj(bdb)
        settings = get_settings()
        IPython.start_ipython(
            argv=[],
            user_ns={
                "BLOOMdb3": BLOOMdb3,
                "BloomObj": BloomObj,
                "bdb": bdb,
                "bobj": bobj,
                "settings": settings,
            },
        )
    except ImportError:
        import code

        bdb = BLOOMdb3()
        bobj = BloomObj(bdb)
        settings = get_settings()
        code.interact(local={"BLOOMdb3": BLOOMdb3, "BloomObj": BloomObj, "bdb": bdb, "bobj": bobj, "settings": settings})


@click.command()
@click.option("--lines", "-n", default=50, type=int, help="Number of lines to show")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option(
    "--service",
    "-s",
    type=click.Choice(["server", "tapdb", "all"]),
    default="all",
    help="Service to show logs for",
)
def logs(lines: int, follow: bool, service: str):
    """View BLOOM and tapdb operation logs."""
    log_files: list[tuple[str, Path]] = []

    if service in ["server", "all"] and SERVER_LOG_DIR.exists():
        server_logs = sorted(SERVER_LOG_DIR.glob("server_*.log"), reverse=True)
        if server_logs:
            log_files.append(("Server", server_logs[0]))

    if service in ["tapdb", "all"]:
        tapdb_log = TAPDB_LOG_DIR / "db_operations.log"
        if tapdb_log.exists():
            log_files.append(("TapDB", tapdb_log))

    if not log_files:
        console.print("[yellow]No log files found.[/yellow]")
        console.print("  • Server: [cyan]~/.bloom/logs/server_*.log[/cyan]")
        console.print("  • TapDB: [cyan]~/.config/tapdb/logs/db_operations.log[/cyan]")
        return

    for name, log_file in log_files:
        console.print(f"[bold]{name} Logs[/bold]: {log_file}")
        console.print()
        if follow:
            console.print("[dim](Press Ctrl+C to stop)[/dim]")
            try:
                subprocess.run(["tail", "-f", "-n", str(lines), str(log_file)])
            except KeyboardInterrupt:
                console.print()
        else:
            subprocess.run(["tail", "-n", str(lines), str(log_file)])
