"""Bloom-specific user commands.

Generic user CRUD is owned by the TapDB CLI.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import typer
from daylily_tapdb.user_store import get_by_login_or_email

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

from bloom_lims.auth.rbac import API_ACCESS_GROUP, Role
from bloom_lims.auth.services.user_api_tokens import (
    TokenCreateInput,
    UserAPITokenService,
)
from bloom_lims.cli._registry_v2 import EXEMPT_MUTATING, register_group_commands
from bloom_lims.db import BLOOMdb3

users_app = typer.Typer(help="Bloom-specific user commands.", no_args_is_help=True)


class TokenScope(str, Enum):
    internal_ro = "internal_ro"
    internal_rw = "internal_rw"
    admin = "admin"


@users_app.command("issue-token")
def issue_token(
    username: str = typer.Option(..., "--username", help="Username / login email"),
    token_name: str = typer.Option(
        ..., "--token-name", help="Display name for the token"
    ),
    scope: TokenScope = typer.Option(TokenScope.admin, "--scope", help="Token scope"),
    expires_in_days: int = typer.Option(
        30,
        "--expires-in-days",
        help="Token validity period in days",
    ),
    note: str = typer.Option("", "--note", help="Optional token note"),
) -> None:
    """Issue a user API token in the active Bloom namespace."""
    bdb = BLOOMdb3(app_username="cli-users")
    try:
        owner = get_by_login_or_email(bdb.session, username, include_inactive=True)
        if owner is None:
            typer.echo(f"User not found: {username}", err=True)
            raise typer.Exit(1)

        service = UserAPITokenService(bdb.session)
        service.groups.ensure_system_groups()
        created = service.create_token(
            owner_user_id=str(owner.uid),
            actor_user_id=str(owner.uid),
            actor_roles=[Role.ADMIN.value],
            actor_groups=[Role.ADMIN.value, API_ACCESS_GROUP],
            payload=TokenCreateInput(
                token_name=token_name.strip(),
                scope=scope.value,
                expires_in_days=expires_in_days,
                note=note.strip() or None,
            ),
        )
        bdb.session.commit()
    except PermissionError as exc:
        bdb.session.rollback()
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        bdb.close()

    typer.echo(f"token_id={created.token.id}")
    typer.echo(f"token_prefix={created.token.token_prefix}")
    typer.echo(f"scope={created.token.scope}")
    typer.echo(f"plaintext_token={created.plaintext_token}")


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register the users command group."""
    _ = spec
    register_group_commands(
        registry,
        "users",
        "User management commands.",
        [
            ("issue-token", issue_token, EXEMPT_MUTATING),
        ],
    )
