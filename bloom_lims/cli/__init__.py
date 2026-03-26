"""
BLOOM LIMS Command Line Interface

Click-based CLI with tab completion support.

Usage:
    bloom --help              Show all available commands
    bloom db status           Show database status
    bloom gui                 Start the BLOOM web UI
    bloom config              Show current configuration
"""

import sys

import click
from rich.console import Console

from bloom_lims.cli.config_cmd import config, config_validate
from bloom_lims.cli.db import db
from bloom_lims.cli.gui import gui, stop
from bloom_lims.cli.info import doctor, info, status, version
from bloom_lims.cli.integrations import integrations
from bloom_lims.cli.quality import quality
from bloom_lims.cli.server import server
from bloom_lims.cli.test import test
from bloom_lims.cli.users import users
from bloom_lims.cli.utils import logs, shell

console = Console()


def _get_version() -> str:
    """Get version from _version module."""
    try:
        from bloom_lims._version import get_version
        return get_version()
    except ImportError:
        return "dev"


@click.group(invoke_without_command=True)
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose output')
@click.option('--version', 'show_version', is_flag=True, help='Show version and exit')
@click.pass_context
def cli(ctx, verbose, show_version):
    """BLOOM LIMS - Laboratory Information Management System CLI."""
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose

    if show_version:
        console.print(f"bloom [cyan]{_get_version()}[/cyan]")
        ctx.exit(0)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# Register command groups
cli.add_command(db)
cli.add_command(gui)
cli.add_command(stop)
cli.add_command(info)
cli.add_command(status)
cli.add_command(doctor)
cli.add_command(version)
cli.add_command(config)
cli.add_command(config_validate)
cli.add_command(server)
cli.add_command(test)
cli.add_command(quality)
cli.add_command(users)
cli.add_command(integrations)
cli.add_command(shell)
cli.add_command(logs)


def main():
    """Main entry point for BLOOM CLI."""
    cli()


if __name__ == "__main__":
    sys.exit(main())
