"""Atlas-style user management proxies for the Bloom CLI."""

from __future__ import annotations

import subprocess

import click

from bloom_lims.cli.db import _current_env, _runtime_env, _tapdb_base_cmd


def _run_tapdb_user(args: list[str]) -> None:
    raise SystemExit(
        subprocess.run(
            _tapdb_base_cmd() + ["user", *args],
            env=_runtime_env(),
            check=False,
        ).returncode
    )


@click.group()
def users():
    """User management commands routed through TapDB."""


@users.command("list")
@click.option("--env", "env_name", default=None, help="TapDB environment name")
def list_users(env_name: str | None):
    """List application users in the active Bloom namespace."""
    _run_tapdb_user(["list", (env_name or _current_env())])


@users.command("add")
@click.option("--env", "env_name", default=None, help="TapDB environment name")
@click.option("--username", required=True, help="Username / login email")
@click.option("--email", default="", help="Email address")
@click.option("--name", default="", help="Display name")
@click.option("--role", default="user", help="Role name")
@click.option("--password", default="", help="Optional password")
def add_user(
    env_name: str | None,
    username: str,
    email: str,
    name: str,
    role: str,
    password: str,
):
    """Create a user in the active Bloom namespace."""
    args = [
        "add",
        (env_name or _current_env()),
        "--username",
        username,
        "--role",
        role,
    ]
    if email.strip():
        args.extend(["--email", email.strip()])
    if name.strip():
        args.extend(["--name", name.strip()])
    if password:
        args.extend(["--password", password])
    _run_tapdb_user(args)
