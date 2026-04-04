#!/usr/bin/env python3
"""Provision or update a local Bloom user and group membership."""

from __future__ import annotations

import argparse
import json

from daylily_tapdb.user_store import create_or_get

from bloom_lims.auth.repositories.tapdb.users import (
    normalize_persisted_role,
    set_user_role,
)
from bloom_lims.auth.services.groups import GroupService
from bloom_lims.db import BLOOMdb3


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a local Bloom user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", default="admin")
    parser.add_argument("--group", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    username = str(args.username).strip().lower()
    email = str(args.email or args.username).strip().lower()
    role = normalize_persisted_role(args.role, default="ADMIN") or "ADMIN"
    groups = [str(group).strip().upper() for group in args.group if str(group).strip()]

    bdb = BLOOMdb3(app_username="local-provision")
    try:
        user, _created = create_or_get(
            bdb.session,
            login_identifier=username,
            email=email,
            display_name=args.name.strip(),
            role="admin" if role == "ADMIN" else "user",
            cognito_username=email,
        )
        if not set_user_role(bdb.session, username, role):
            raise RuntimeError("Failed to persist canonical role")
        group_service = GroupService(bdb.session)
        group_service.ensure_system_groups()
        for group_code in groups:
            group_service.add_user_to_group(
                group_code=group_code,
                user_id=str(user.uid),
                added_by=str(user.uid),
            )
        bdb.session.commit()
        payload = {
            "uid": user.uid,
            "euid": user.euid,
            "username": user.username,
            "email": user.email,
            "role": role,
            "groups": groups,
        }
    except Exception as exc:
        bdb.session.rollback()
        print(f"Provision failed: {exc}")
        return 1
    finally:
        bdb.close()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
