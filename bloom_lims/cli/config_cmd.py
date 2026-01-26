"""Configuration commands for BLOOM CLI."""

import os
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.syntax import Syntax

console = Console()


@click.command()
@click.option('--edit', '-e', is_flag=True, help='Open config file in $EDITOR')
@click.option('--path', '-p', is_flag=True, help='Show config file path only')
@click.option('--template', '-t', is_flag=True, help='Show template config instead')
def config(edit, path, template):
    """Show or edit BLOOM configuration."""
    from bloom_lims.config import (
        get_settings, 
        get_user_config_path, 
        get_template_config_path,
        ensure_user_config_exists,
    )
    
    if template:
        config_path = get_template_config_path()
    else:
        config_path = get_user_config_path()
    
    if path:
        console.print(str(config_path))
        return
    
    if edit:
        # Ensure user config exists before editing
        if not template:
            ensure_user_config_exists()
            config_path = get_user_config_path()
        
        editor = os.environ.get("EDITOR", "vi")
        console.print(f"[cyan]Opening {config_path} in {editor}...[/cyan]")
        subprocess.run([editor, str(config_path)])
        return
    
    # Show current config
    if config_path.exists():
        console.print(f"[bold]Configuration: {config_path}[/bold]")
        console.print()
        
        with open(config_path) as f:
            content = f.read()
        
        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
        console.print(syntax)
    else:
        console.print(f"[yellow]Config file not found: {config_path}[/yellow]")
        console.print()
        console.print("Create one with: [cyan]bloom config --edit[/cyan]")
        console.print("Or copy the template:")
        console.print(f"  [cyan]cp {get_template_config_path()} {get_user_config_path()}[/cyan]")

