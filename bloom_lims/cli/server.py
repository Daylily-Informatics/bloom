"""Atlas-style server command group for BLOOM CLI."""

from __future__ import annotations

import click

from bloom_lims.cli.gui import gui as gui_command
from bloom_lims.cli.gui import stop as stop_command
from bloom_lims.cli.info import status as status_command
from bloom_lims.cli.utils import logs as logs_command


@click.group()
def server():
    """Server lifecycle commands."""


@server.command("start")
@click.option("--port", "-p", default=8912, type=int, help="Port to run on")
@click.option("--host", "-h", default="0.0.0.0", type=str, help="Host to bind to")
@click.option("--reload", "-r", is_flag=True, help="Enable auto-reload for development")
@click.option("--background/--foreground", "-b/-f", default=True, help="Run in background")
def start(port: int, host: str, reload: bool, background: bool):
    """Start the BLOOM GUI server."""
    gui_command.callback(port=port, host=host, reload=reload, background=background)


@server.command("stop")
def stop():
    """Stop the BLOOM GUI server."""
    stop_command.callback()


@server.command("status")
def status():
    """Show BLOOM runtime status."""
    status_command.callback()


@server.command("logs")
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
    """Show BLOOM server and TapDB logs."""
    logs_command.callback(lines=lines, follow=follow, service=service)
