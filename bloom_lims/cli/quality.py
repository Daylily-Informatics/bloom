"""Atlas-style quality command group for the Bloom CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str]) -> None:
    raise SystemExit(
        subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            check=False,
        ).returncode
    )


@click.group()
def quality():
    """Code-quality and validation commands."""


@quality.command("check")
def check():
    """Run the standard Bloom quality gates."""
    commands = (
        [sys.executable, "-m", "ruff", "check", "bloom_lims", "tests"],
        [sys.executable, "-m", "bandit", "-c", "pyproject.toml", "-r", "bloom_lims"],
    )
    for cmd in commands:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
        if result.returncode != 0:
            raise SystemExit(result.returncode)


@quality.command(
    "ruff",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("ruff_args", nargs=-1, type=click.UNPROCESSED)
def ruff(ruff_args: tuple[str, ...]):
    """Run Ruff with optional extra arguments."""
    args = list(ruff_args) or ["check", "bloom_lims", "tests"]
    _run([sys.executable, "-m", "ruff", *args])


@quality.command(
    "bandit",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("bandit_args", nargs=-1, type=click.UNPROCESSED)
def bandit(bandit_args: tuple[str, ...]):
    """Run Bandit with optional extra arguments."""
    args = list(bandit_args) or ["-c", "pyproject.toml", "-r", "bloom_lims"]
    _run([sys.executable, "-m", "bandit", *args])
