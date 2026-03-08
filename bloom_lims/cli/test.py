"""Atlas-style test command group for the Bloom CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@click.group()
def test():
    """Test execution commands."""


@test.command(
    "run",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def run(pytest_args: tuple[str, ...]):
    """Run Bloom test suites via pytest."""
    args = list(pytest_args) or ["tests"]
    raise SystemExit(
        subprocess.run(
            [sys.executable, "-m", "pytest", *args],
            cwd=PROJECT_ROOT,
            check=False,
        ).returncode
    )
