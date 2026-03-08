"""Atlas-style integrations group for the Bloom CLI."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from bloom_lims.config import get_settings

console = Console()


@click.group()
def integrations():
    """External integration commands."""


@integrations.group()
def atlas():
    """Atlas integration configuration and diagnostics."""


@atlas.command("show")
def show_atlas_config():
    """Display the effective Atlas integration configuration."""
    settings = get_settings()
    table = Table(title="Bloom -> Atlas Integration")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("base_url", settings.atlas.base_url or "")
    table.add_row("organization_id", settings.atlas.organization_id or "")
    table.add_row("events_path", settings.atlas.events_path)
    table.add_row("timeout_seconds", str(settings.atlas.timeout_seconds))
    table.add_row("cache_ttl_seconds", str(settings.atlas.cache_ttl_seconds))
    table.add_row("verify_ssl", str(settings.atlas.verify_ssl))
    console.print(table)


@atlas.command("doctor")
def doctor_atlas_integration():
    """Report whether Atlas integration settings are usable."""
    settings = get_settings()
    missing: list[str] = []
    if not str(settings.atlas.base_url or "").strip():
        missing.append("atlas.base_url")
    if not str(settings.atlas.token or "").strip():
        missing.append("atlas.token")
    if missing:
        console.print(
            "[yellow]Atlas integration is partially configured.[/yellow] Missing: "
            + ", ".join(missing)
        )
        raise SystemExit(1)
    console.print("[green]✓[/green] Atlas integration config is present")
