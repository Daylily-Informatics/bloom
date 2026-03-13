"""Atlas-style user management proxies for the Bloom CLI."""

from __future__ import annotations

import subprocess

import click

from bloom_lims.auth.rbac import API_ACCESS_GROUP, Role
from bloom_lims.auth.services.user_api_tokens import TokenCreateInput, UserAPITokenService
from bloom_lims.cli.db import _current_env, _runtime_env, _tapdb_base_cmd
from bloom_lims.db import BLOOMdb3
from daylily_tapdb.user_store import get_by_login_or_email


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


@users.command("issue-token")
@click.option("--username", required=True, help="Username / login email")
@click.option("--token-name", required=True, help="Display name for the token")
@click.option(
    "--scope",
    default="admin",
    type=click.Choice(["internal_ro", "internal_rw", "admin"], case_sensitive=False),
    show_default=True,
    help="Token scope",
)
@click.option(
    "--expires-in-days",
    default=30,
    type=int,
    show_default=True,
    help="Token validity period in days",
)
@click.option("--note", default="", help="Optional token note")
def issue_token(
    username: str,
    token_name: str,
    scope: str,
    expires_in_days: int,
    note: str,
):
    """Issue a user API token in the active Bloom namespace."""
    bdb = BLOOMdb3(app_username="cli-users")
    try:
        owner = get_by_login_or_email(bdb.session, username, include_inactive=True)
        if owner is None:
            raise click.ClickException(f"User not found: {username}")

        service = UserAPITokenService(bdb.session)
        service.groups.ensure_system_groups()
        created = service.create_token(
            owner_user_id=str(owner.uid),
            actor_user_id=str(owner.uid),
            actor_roles=[Role.ADMIN.value],
            actor_groups=[Role.ADMIN.value, API_ACCESS_GROUP],
            payload=TokenCreateInput(
                token_name=token_name.strip(),
                scope=scope.strip().lower(),
                expires_in_days=expires_in_days,
                note=note.strip() or None,
            ),
        )
        bdb.session.commit()
    except PermissionError as exc:
        bdb.session.rollback()
        raise click.ClickException(str(exc)) from exc
    finally:
        bdb.close()

    click.echo(f"token_id={created.token.id}")
    click.echo(f"token_prefix={created.token.token_prefix}")
    click.echo(f"scope={created.token.scope}")
    click.echo(f"plaintext_token={created.plaintext_token}")
