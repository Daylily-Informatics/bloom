"""External integration commands for the Bloom CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING
import os
import stat
import tempfile
from pathlib import Path
from uuid import UUID

import yaml

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

import typer
from rich.console import Console
from rich.table import Table

from bloom_lims.cli._registry_v2 import EXEMPT, EXEMPT_MUTATING, register_group_commands
from bloom_lims.config import AtlasSettings, get_settings

integrations_app = typer.Typer(
    help="External integration commands.", no_args_is_help=True
)
atlas_app = typer.Typer(
    help="Atlas integration configuration and diagnostics.", no_args_is_help=True
)
console = Console()


@atlas_app.command("configure-business-client")
def configure_business_client(
    config: Path = typer.Option(..., "--config", help="Existing absolute Bloom YAML path"),
    base_url: str = typer.Option(..., "--base-url"),
    organization_id: str = typer.Option(..., "--organization-id"),
    token_file: Path = typer.Option(..., "--token-file", help="Private file containing the existing Atlas integration token"),
):
    """Set only Atlas business-client settings, preserving native DAG and other config."""
    if not config.is_absolute() or not token_file.is_absolute():
        raise typer.BadParameter("Configuration and token paths must be absolute")
    if config.is_symlink() or token_file.is_symlink():
        raise typer.BadParameter("Use regular configuration and token files, not symlinks")
    info = token_file.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise typer.BadParameter("Token file must be a private regular file (0600 or 0400)")
    token = token_file.read_text().strip()
    if not token or any(c.isspace() for c in token):
        raise typer.BadParameter("Token file must contain exactly one token")
    org = str(UUID(organization_id))
    original = config.read_bytes()
    config_stat = config.stat()
    content = yaml.safe_load(original)
    if not isinstance(content, dict):
        raise typer.BadParameter("Existing configuration must be a YAML mapping")
    prior = content.get("atlas", {})
    if not isinstance(prior, dict):
        raise typer.BadParameter("Existing atlas configuration must be a mapping")
    candidate = {**prior, "base_url": base_url, "organization_id": org, "token": token}
    try:
        AtlasSettings.model_validate(candidate)
    except Exception:
        # Pydantic errors may echo secret inputs; never render them.
        raise typer.BadParameter("Atlas configuration is invalid; check URL and organization UUID") from None
    content["atlas"] = candidate
    fd, temporary = tempfile.mkstemp(prefix=".bloom-atlas-", dir=config.parent)
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, config_stat.st_uid, config_stat.st_gid)
        with os.fdopen(fd, "w") as stream:
            yaml.safe_dump(content, stream, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        if config.read_bytes() != original:
            raise typer.BadParameter("Configuration changed during edit; reload it before retrying")
        os.replace(temporary, config)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    console.print("Atlas business-client configuration saved. Restart the selected Bloom service to load it.")


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
    _ = spec
    registry.add_group("integrations", help_text="External integration commands.")
    register_group_commands(
        registry,
        "integrations/atlas",
        "Atlas integration configuration and diagnostics.",
        [
            ("show", show_atlas_config, EXEMPT),
            ("doctor", doctor_atlas_integration, EXEMPT),
            ("configure-business-client", configure_business_client, EXEMPT_MUTATING),
        ],
    )
