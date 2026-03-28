"""External integration commands for the Bloom CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

import typer
from rich.console import Console
from rich.table import Table

from bloom_lims.config import get_settings

integrations_app = typer.Typer(
    help="External integration commands.", no_args_is_help=True
)
atlas_app = typer.Typer(
    help="Atlas integration configuration and diagnostics.", no_args_is_help=True
)
console = Console()


@atlas_app.command("show")
def show_atlas_config() -> None:
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


@atlas_app.command("doctor")
def doctor_atlas_integration() -> None:
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
        raise typer.Exit(1)
    console.print("[green]✓[/green] Atlas integration config is present")


integrations_app.add_typer(atlas_app, name="atlas")


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register the integrations command group."""
    registry.add_typer_app(
        None, integrations_app, "integrations", "External integration commands."
    )
