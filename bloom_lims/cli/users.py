"""Bloom-specific user commands."""

from __future__ import annotations

from enum import Enum
import json
from typing import TYPE_CHECKING

import typer
from daylily_tapdb.user_store import create_or_get, get_by_login_or_email

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

from bloom_lims.auth.rbac import API_ACCESS_GROUP, Role
from bloom_lims.auth.repositories.tapdb.users import (
    normalize_persisted_role,
    set_user_role,
)
from bloom_lims.auth.services.groups import GroupService, SYSTEM_GROUP_CODES
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


@users_app.command("provision-local")
def provision_local(
    username: str = typer.Option(..., "--username", help="Username / login email"),
    email: str = typer.Option("", "--email", help="Optional email override"),
    name: str = typer.Option(..., "--name", help="Display name"),
    role: str = typer.Option("admin", "--role", help="Role: admin or user"),
    group: list[str] = typer.Option([], "--group", help="Repeatable local Bloom group code"),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Provision or update a local Bloom user and Bloom-local group membership."""
    normalized_username = str(username).strip().lower()
    normalized_email = str(email or username).strip().lower()
    normalized_name = str(name).strip() or normalized_username
    normalized_role = normalize_persisted_role(role, default="ADMIN") or "ADMIN"
    requested_groups = []
    seen_groups: set[str] = set()
    for raw_group in group:
        group_code = str(raw_group).strip().upper()
        if not group_code or group_code in seen_groups:
            continue
        requested_groups.append(group_code)
        seen_groups.add(group_code)

    unsupported = sorted(set(requested_groups) - set(SYSTEM_GROUP_CODES))
    if unsupported:
        typer.echo(
            "Unsupported Bloom local groups: " + ", ".join(unsupported),
            err=True,
        )
        raise typer.Exit(1)

    bdb = BLOOMdb3(app_username="cli-users")
    try:
        user, _created = create_or_get(
            bdb.session,
            login_identifier=normalized_username,
            email=normalized_email,
            display_name=normalized_name,
            role="admin" if normalized_role == "ADMIN" else "user",
            cognito_username=normalized_email,
        )
        if not set_user_role(bdb.session, user.uid, normalized_role):
            raise RuntimeError("Failed to persist canonical role")

        group_service = GroupService(bdb.session)
        group_service.ensure_system_groups()
        existing_groups = set(group_service.get_group_codes_for_user(str(user.uid)))
        for group_code in requested_groups:
            if group_code in existing_groups:
                continue
            group_service.add_user_to_group(
                group_code=group_code,
                user_id=str(user.uid),
                added_by=str(user.uid),
            )
        bdb.session.commit()
    except Exception as exc:
        bdb.session.rollback()
        typer.echo(f"Provision failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        bdb.close()

    payload = {
        "uid": user.uid,
        "euid": getattr(user, "euid", None),
        "username": getattr(user, "username", normalized_username),
        "email": getattr(user, "email", normalized_email),
        "role": normalized_role,
        "groups": requested_groups,
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(json.dumps(payload, sort_keys=True))


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
            ("provision-local", provision_local, EXEMPT_MUTATING),
            ("issue-token", issue_token, EXEMPT_MUTATING),
        ],
    )
