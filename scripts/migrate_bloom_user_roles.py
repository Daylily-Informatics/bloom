#!/usr/bin/env python3
"""Backfill Bloom TapDB user roles to canonical uppercase values."""

from __future__ import annotations

import argparse
import json

from bloom_lims.auth.rbac import (
    BLOOM_ADMIN_GROUP,
    BLOOM_READONLY_GROUP,
    BLOOM_READWRITE_GROUP,
    Role,
)
from bloom_lims.auth.repositories.tapdb.users import (
    list_users,
    normalize_persisted_role,
    set_user_role,
)
from bloom_lims.auth.services.groups import GroupService
from bloom_lims.db import BLOOMdb3

LEGACY_ROLE_GROUP_PRIORITY = (
    (BLOOM_ADMIN_GROUP.upper(), Role.ADMIN.value),
    (BLOOM_READWRITE_GROUP.upper(), Role.READ_WRITE.value),
    (BLOOM_READONLY_GROUP.upper(), Role.READ_ONLY.value),
)
LEGACY_ROLE_GROUP_CODES = (
    BLOOM_ADMIN_GROUP,
    BLOOM_READWRITE_GROUP,
    BLOOM_READONLY_GROUP,
)


def _infer_role_from_groups(groups: list[str]) -> str | None:
    group_set = {str(group or "").strip().upper() for group in groups if str(group or "").strip()}
    for group_name, role_name in LEGACY_ROLE_GROUP_PRIORITY:
        if group_name in group_set:
            return role_name
    return None


def migrate_roles(*, dry_run: bool = False) -> dict[str, object]:
    bdb = BLOOMdb3(app_username="bloom-role-migration")
    try:
        group_service = GroupService(bdb.session)
        group_service.ensure_system_groups()

        users = list_users(bdb.session, include_inactive=True)
        updates: list[dict[str, object]] = []
        removed_memberships: list[dict[str, object]] = []
        unresolved: list[dict[str, object]] = []

        for user in users:
            candidate_groups: list[str] = []
            stored_role = normalize_persisted_role(user.role, default=None)
            if stored_role is None:
                for candidate in (user.uid, user.username, user.email):
                    if not candidate:
                        continue
                    candidate_groups.extend(group_service.get_group_codes_for_user(str(candidate)))
                stored_role = _infer_role_from_groups(candidate_groups)
            if stored_role is None:
                unresolved.append({"uid": user.uid, "username": user.username, "email": user.email})
                continue

            current_role = str(user.role or "").strip()
            identifier = user.username or user.email or str(user.uid)
            if current_role != stored_role:
                updates.append({"identifier": identifier, "role": stored_role})
                if not dry_run and not set_user_role(bdb.session, identifier, stored_role):
                    unresolved.append({"uid": user.uid, "username": user.username, "email": user.email})
                    continue

            legacy_group_codes = {
                str(group or "").strip().upper() for group in candidate_groups if str(group or "").strip()
            }
            for group_code in LEGACY_ROLE_GROUP_CODES:
                if group_code.upper() not in legacy_group_codes:
                    continue
                removed_memberships.append({"identifier": identifier, "group_code": group_code})
                if not dry_run:
                    group_service.remove_user_from_group(
                        group_code=group_code,
                        user_id=str(user.uid),
                        removed_by=str(user.uid),
                    )

        if unresolved:
            raise RuntimeError(
                "Unable to resolve Bloom roles for: "
                + ", ".join(
                    str(item.get("username") or item.get("email") or item.get("uid")) for item in unresolved
                )
            )

        if not dry_run:
            bdb.session.commit()
        return {
            "updated": updates,
            "count": len(updates),
            "removed_memberships": removed_memberships,
            "removed_count": len(removed_memberships),
            "dry_run": dry_run,
        }
    except Exception:
        bdb.session.rollback()
        raise
    finally:
        bdb.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report planned updates without writing")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args()

    result = migrate_roles(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"updated={result['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
