"""Utility commands for BLOOM CLI."""

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
PGDATA = PROJECT_ROOT / "bloom_lims" / "database"


@click.command()
def shell():
    """Open interactive Python shell with BLOOM loaded."""
    console.print("[cyan]Starting BLOOM interactive shell...[/cyan]")
    console.print()
    
    # Create startup script
    startup_code = '''
import sys
sys.path.insert(0, ".")

from bloom_lims.db import BLOOMdb3
from bloom_lims.config import get_settings
from bloom_lims.bobjs.core import BloomObj

print("\\n[BLOOM Shell] Objects available:")
print("  bdb      - BLOOMdb3 instance")
print("  bobj     - BloomObj instance")
print("  settings - BLOOM settings")
print()

bdb = BLOOMdb3()
bobj = BloomObj(bdb)
settings = get_settings()
'''
    
    # Use IPython if available, otherwise standard Python
    try:
        import IPython
        IPython.start_ipython(argv=[], user_ns={
            'BLOOMdb3': __import__('bloom_lims.db', fromlist=['BLOOMdb3']).BLOOMdb3,
            'BloomObj': __import__('bloom_lims.bobjs.core', fromlist=['BloomObj']).BloomObj,
            'get_settings': __import__('bloom_lims.config', fromlist=['get_settings']).get_settings,
        })
    except ImportError:
        # Fall back to standard Python REPL
        import code
        exec(startup_code)
        code.interact(local=locals())


@click.command()
@click.option('--lines', '-n', default=50, type=int, help='Number of lines to show')
@click.option('--follow', '-f', is_flag=True, help='Follow log output')
@click.option('--service', '-s', type=click.Choice(['postgres', 'all']), default='all', 
              help='Service to show logs for')
def logs(lines, follow, service):
    """View BLOOM service logs."""
    log_files = []
    
    if service in ['postgres', 'all']:
        pg_log = PGDATA / "postgresql.log"
        if pg_log.exists():
            log_files.append(('PostgreSQL', pg_log))
    
    if not log_files:
        console.print("[yellow]No log files found.[/yellow]")
        console.print()
        console.print("Logs are available for:")
        console.print("  • PostgreSQL: [cyan]bloom_lims/database/postgresql.log[/cyan]")
        return
    
    for name, log_file in log_files:
        console.print(f"[bold]{name} Logs[/bold]: {log_file}")
        console.print()
        
        if follow:
            console.print("[dim](Press Ctrl+C to stop)[/dim]")
            console.print()
            try:
                subprocess.run(["tail", "-f", "-n", str(lines), str(log_file)])
            except KeyboardInterrupt:
                console.print()
        else:
            subprocess.run(["tail", "-n", str(lines), str(log_file)])

