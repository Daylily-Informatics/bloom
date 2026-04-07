"""Testing commands for BLOOM CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

import subprocess
import sys
from pathlib import Path

import typer

from bloom_lims.cli._registry_v2 import EXEMPT_LONG_RUNNING, register_group_commands

test_app = typer.Typer(help="Test execution commands", no_args_is_help=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@test_app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(ctx: typer.Context) -> None:
    """Run Bloom test suites via pytest."""
    args = list(ctx.args) or ["tests"]
    raise typer.Exit(
        subprocess.run(
            [sys.executable, "-m", "pytest", *args],
            cwd=PROJECT_ROOT,
            check=False,
        ).returncode
    )


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register the test command group."""
    _ = spec
    register_group_commands(
        registry,
        "test",
        "Test execution commands.",
        [
            ("run", run, EXEMPT_LONG_RUNNING),
        ],
    )
