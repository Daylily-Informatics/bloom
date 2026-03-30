"""Extra config subcommands for the Bloom CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

from bloom_lims.config import (
    apply_runtime_environment,
    assert_tapdb_version,
    get_settings,
    get_template_config_path,
    get_user_config_path,
    validate_settings,
)
from bloom_lims.db import BLOOMdb3
from bloom_lims.domain.base import BloomObj
from bloom_lims.schema_drift import (
    run_schema_drift_check,
    write_schema_drift_report,
)

console = Console()
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _tapdb_schema_drift_check(env_name: str) -> tuple[int, dict[str, object], str]:
    """Run the TapDB schema drift check in report-only mode."""
    result = run_schema_drift_check(env_name)
    returncode = {"clean": 0, "drift": 1, "check_failed": 2}.get(str(result.get("status") or ""), 2)
    payload = result.get("report")
    return returncode, payload if isinstance(payload, dict) else {}, str(result.get("stderr") or "")


def _schema_drift_summary(payload: dict[str, object]) -> str:
    counts = payload.get("counts")
    if isinstance(counts, dict):
        expected = counts.get("expected")
        live = counts.get("live")
        return f"expected={expected} live={live}"
    return "drift report available"


def _shell() -> None:
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
        code.interact(
            local={
                "BLOOMdb3": BLOOMdb3,
                "BloomObj": BloomObj,
                "bdb": bdb,
                "bobj": bobj,
                "settings": settings,
            }
        )


def _status() -> None:
    """Show environment and configuration information."""
    settings = get_settings()
    config_file = get_user_config_path()
    template_file = get_template_config_path()

    console.print()
    console.print("[bold blue]Configuration Sources[/bold blue]")
    if config_file.exists():
        console.print(f"  [green]●[/green] User config: {config_file}")
    else:
        console.print(f"  [dim]○[/dim] User config: {config_file} (not found)")
    console.print(f"  [green]●[/green] Template: {template_file}")
    console.print()

    table = Table(title="Effective Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    rows = [
        ("environment", settings.environment),
        ("tapdb.env", settings.tapdb.env),
        ("tapdb.database_name", settings.tapdb.database_name),
        ("aws.profile", settings.aws.profile),
        ("aws.region", settings.aws.region),
        (
            "auth.cognito_user_pool_id",
            settings.auth.cognito_user_pool_id or "[dim]not set[/dim]",
        ),
        (
            "auth.cognito_client_id",
            settings.auth.cognito_client_id or "[dim]not set[/dim]",
        ),
        ("auth.cognito_domain", settings.auth.cognito_domain or "[dim]not set[/dim]"),
        ("atlas.base_url", settings.atlas.base_url or "[dim]not set[/dim]"),
        ("dewey.enabled", str(settings.dewey.enabled)),
    ]

    for key, value in rows:
        table.add_row(key, value)

    console.print(table)


def _doctor() -> None:
    """Verify environment, dependencies, and configuration."""
    console.print("[bold]BLOOM Doctor - Environment Check[/bold]")
    console.print()

    issues: list[str] = []
    warnings: list[str] = []

    py_version = sys.version_info
    if py_version >= (3, 12):
        console.print(f"[green]✓[/green] Python {py_version.major}.{py_version.minor}")
    else:
        issues.append(
            f"Python 3.12+ required, found {py_version.major}.{py_version.minor}"
        )
        console.print(
            f"[red]✗[/red] Python {py_version.major}.{py_version.minor} (3.12+ required)"
        )

    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    if conda_env == "BLOOM":
        console.print("[green]✓[/green] Conda environment: BLOOM")
    else:
        warnings.append(f"Not in BLOOM conda environment (current: {conda_env})")
        console.print(
            f"[yellow]⚠[/yellow] Conda environment: {conda_env or 'none'} (expected: BLOOM)"
        )

    for module_name in ["bloom_lims.db", "bloom_lims.config", "daylily_tapdb"]:
        try:
            __import__(module_name)
            console.print(f"[green]✓[/green] Import: {module_name}")
        except ImportError as exc:
            issues.append(f"Cannot import {module_name}: {exc}")
            console.print(f"[red]✗[/red] Import: {module_name}")

    try:
        tapdb_version = assert_tapdb_version()
        console.print(f"[green]✓[/green] daylily-tapdb version: {tapdb_version}")
    except Exception as exc:
        issues.append(str(exc))
        console.print(f"[red]✗[/red] daylily-tapdb version check failed: {exc}")

    env_name = apply_runtime_environment(get_settings()).env
    drift_result = run_schema_drift_check(env_name)
    write_schema_drift_report(drift_result)
    drift_returncode = {"clean": 0, "drift": 1, "check_failed": 2}.get(
        str(drift_result.get("status") or ""),
        2,
    )
    drift_payload = drift_result.get("report")
    if not isinstance(drift_payload, dict):
        drift_payload = {}
    drift_stderr = str(drift_result.get("stderr") or "")
    if drift_returncode == 0:
        console.print("[green]✓[/green] TapDB connectivity and schema drift report")
    elif drift_returncode == 1:
        summary = _schema_drift_summary(drift_payload)
        console.print(f"[yellow]⚠[/yellow] TapDB schema drift detected (report only): {summary}")
        warnings.append(f"TapDB schema drift detected ({summary})")
    else:
        issues.append("TapDB schema drift check failed")
        console.print("[red]✗[/red] TapDB schema drift check failed")
        if drift_stderr:
            warnings.append(drift_stderr)

    warnings.extend(f"Config: {warning}" for warning in validate_settings())

    console.print()
    if issues:
        console.print(f"[red]Found {len(issues)} issue(s):[/red]")
        for issue in issues:
            console.print(f"  [red]•[/red] {issue}")
    if warnings:
        console.print(f"[yellow]Found {len(warnings)} warning(s):[/yellow]")
        for warning in warnings:
            console.print(f"  [yellow]•[/yellow] {warning}")
    if not issues and not warnings:
        console.print("[green]✓ All checks passed![/green]")

    if issues:
        raise SystemExit(1)


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register extra config subcommands."""
    registry.add_command(
        "config", "shell", _shell, "Open interactive Python shell with BLOOM loaded"
    )
    registry.add_command(
        "config",
        "doctor",
        _doctor,
        "Verify environment, dependencies, and configuration",
    )
    registry.add_command(
        "config", "status", _status, "Show environment and configuration status"
    )
