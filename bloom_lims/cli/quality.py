"""Quality commands for BLOOM CLI."""

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

quality_app = typer.Typer(
    help="Code-quality and validation commands", no_args_is_help=True
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str]) -> None:
    raise typer.Exit(
        subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            check=False,
        ).returncode
    )


@quality_app.command("check")
def check() -> None:
    """Run the standard Bloom quality gates."""
    commands = (
        [sys.executable, "-m", "ruff", "check", "bloom_lims", "tests"],
        [sys.executable, "-m", "bandit", "-c", "pyproject.toml", "-r", "bloom_lims"],
    )
    for cmd in commands:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
        if result.returncode != 0:
            raise typer.Exit(result.returncode)


@quality_app.command(
    "ruff",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def ruff(ctx: typer.Context) -> None:
    """Run Ruff with optional extra arguments."""
    args = list(ctx.args) or ["check", "bloom_lims", "tests"]
    _run([sys.executable, "-m", "ruff", *args])


@quality_app.command(
    "bandit",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def bandit(ctx: typer.Context) -> None:
    """Run Bandit with optional extra arguments."""
    args = list(ctx.args) or ["-c", "pyproject.toml", "-r", "bloom_lims"]
    _run([sys.executable, "-m", "bandit", *args])


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register the quality command group."""
    _ = spec
    register_group_commands(
        registry,
        "quality",
        "Code-quality commands.",
        [
            ("check", check, EXEMPT_LONG_RUNNING),
            ("ruff", ruff, EXEMPT_LONG_RUNNING),
            ("bandit", bandit, EXEMPT_LONG_RUNNING),
        ],
    )
