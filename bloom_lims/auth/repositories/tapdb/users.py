"""TapDB-backed helpers for Bloom user identity and role storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from bloom_lims.auth.rbac import Role, normalize_roles


@dataclass(frozen=True)
class TapdbUserRecord:
    uid: int
    username: str
    email: str | None
    display_name: str | None
    role: str | None
    is_active: bool
    euid: str | None = None


_USER_SELECT_SQL = """
    SELECT
        gi.uid,
        gi.euid,
        NULLIF(gi.json_addl->>'login_identifier', '') AS login_identifier,
        NULLIF(gi.json_addl->>'email', '') AS email,
        NULLIF(gi.json_addl->>'display_name', '') AS display_name,
        NULLIF(gi.json_addl->>'role', '') AS role,
        CASE
            WHEN COALESCE(gi.is_deleted, FALSE) THEN FALSE
            WHEN gi.bstatus IS NOT NULL AND lower(CAST(gi.bstatus AS text)) IN ('inactive', 'disabled', 'deleted') THEN FALSE
            WHEN COALESCE(gi.json_addl->>'is_active', '') = '' THEN TRUE
            ELSE lower(COALESCE(gi.json_addl->>'is_active', 'true')) IN ('true', '1', 'yes', 'on')
        END AS is_active
    FROM generic_instance gi
    WHERE gi.polymorphic_discriminator = 'actor_instance'
      AND gi.category = 'generic'
      AND gi.type = 'actor'
      AND gi.subtype = 'system_user'
      AND COALESCE(gi.is_deleted, FALSE) = FALSE
"""


def _normalize_identifier(value: str | int | None) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        raise ValueError("user identifier is required")
    return candidate


def _normalize_stored_role(
    role_value: Any, *, default: str | None = None
) -> str | None:
    def _coerce(value: Any) -> str | None:
        candidate = str(value or "").strip()
        if not candidate:
            return None
        legacy = {
            "admin": Role.ADMIN.value,
            "user": Role.READ_WRITE.value,
            "readonly": Role.READ_ONLY.value,
            "read_only": Role.READ_ONLY.value,
            "readwrite": Role.READ_WRITE.value,
            "read_write": Role.READ_WRITE.value,
        }
        mapped = legacy.get(candidate.lower())
        if mapped is not None:
            return mapped
        values = normalize_roles([candidate], fallback=None)
        return values[0] if values else None

    normalized = _coerce(role_value)
    if normalized is not None:
        return normalized
    if default is None:
        return None
    return _coerce(default)


def _row_to_user(row: dict[str, Any]) -> TapdbUserRecord:
    return TapdbUserRecord(
        uid=int(row["uid"]),
        username=str(row.get("login_identifier") or "").strip().lower(),
        email=str(row.get("email") or "").strip().lower() or None,
        display_name=str(row.get("display_name") or "").strip() or None,
        role=str(row.get("role") or "").strip() or None,
        is_active=bool(row.get("is_active")),
        euid=str(row.get("euid") or "").strip() or None,
    )


def list_users(
    session: Session, *, include_inactive: bool = False
) -> list[TapdbUserRecord]:
    sql = _USER_SELECT_SQL
    if not include_inactive:
        sql += "\n      AND CASE\n            WHEN COALESCE(gi.is_deleted, FALSE) THEN FALSE\n            WHEN gi.bstatus IS NOT NULL AND lower(CAST(gi.bstatus AS text)) IN ('inactive', 'disabled', 'deleted') THEN FALSE\n            WHEN COALESCE(gi.json_addl->>'is_active', '') = '' THEN TRUE\n            ELSE lower(COALESCE(gi.json_addl->>'is_active', 'true')) IN ('true', '1', 'yes', 'on')\n        END = TRUE"
    sql += "\n    ORDER BY gi.uid ASC"
    rows = session.execute(text(sql)).mappings().all()
    return [_row_to_user(dict(row)) for row in rows]


def get_user_by_uid(
    session: Session,
    user_uid: int | str,
    *,
    include_inactive: bool = False,
) -> TapdbUserRecord | None:
    sql = _USER_SELECT_SQL + "\n      AND gi.uid = :uid"
    if not include_inactive:
        sql += "\n      AND CASE\n            WHEN COALESCE(gi.is_deleted, FALSE) THEN FALSE\n            WHEN gi.bstatus IS NOT NULL AND lower(CAST(gi.bstatus AS text)) IN ('inactive', 'disabled', 'deleted') THEN FALSE\n            WHEN COALESCE(gi.json_addl->>'is_active', '') = '' THEN TRUE\n            ELSE lower(COALESCE(gi.json_addl->>'is_active', 'true')) IN ('true', '1', 'yes', 'on')\n        END = TRUE"
    sql += "\n    LIMIT 1"
    row = session.execute(text(sql), {"uid": int(user_uid)}).mappings().first()
    if not row:
        return None
    return _row_to_user(dict(row))


def get_user_by_login_or_email(
    session: Session,
    identifier: str,
    *,
    include_inactive: bool = False,
) -> TapdbUserRecord | None:
    normalized = _normalize_identifier(identifier)
    sql = _USER_SELECT_SQL
    if not include_inactive:
        sql += "\n      AND CASE\n            WHEN COALESCE(gi.is_deleted, FALSE) THEN FALSE\n            WHEN gi.bstatus IS NOT NULL AND lower(CAST(gi.bstatus AS text)) IN ('inactive', 'disabled', 'deleted') THEN FALSE\n            WHEN COALESCE(gi.json_addl->>'is_active', '') = '' THEN TRUE\n            ELSE lower(COALESCE(gi.json_addl->>'is_active', 'true')) IN ('true', '1', 'yes', 'on')\n        END = TRUE"
    sql += """
      AND (
            lower(COALESCE(gi.json_addl->>'login_identifier', '')) = :identifier
         OR lower(COALESCE(gi.json_addl->>'email', '')) = :identifier
      )
      LIMIT 1
    """
    row = session.execute(text(sql), {"identifier": normalized}).mappings().first()
    if not row:
        return None
    return _row_to_user(dict(row))


def resolve_user_record(
    session: Session,
    identifier: str | int | None,
    *,
    include_inactive: bool = False,
) -> TapdbUserRecord | None:
    candidate = str(identifier or "").strip()
    if not candidate:
        return None

    if candidate.isdigit():
        by_uid = get_user_by_uid(session, candidate, include_inactive=include_inactive)
        if by_uid is not None:
            return by_uid

    return get_user_by_login_or_email(
        session, candidate, include_inactive=include_inactive
    )


def normalize_persisted_role(
    role_value: Any, *, default: str | None = Role.READ_WRITE.value
) -> str | None:
    return _normalize_stored_role(role_value, default=default)


def set_user_role(session: Session, identifier: str | int, role: str) -> bool:
    normalized_role = _normalize_stored_role(role, default=None)
    if normalized_role is None:
        raise ValueError(f"invalid role: {role!r}")
    candidate = str(identifier or "").strip()
    if not candidate:
        raise ValueError("user identifier is required")

    if candidate.isdigit():
        row = session.execute(
            text(
                """
                UPDATE generic_instance gi
                SET json_addl = jsonb_set(
                        COALESCE(gi.json_addl, '{}'::jsonb),
                        '{role}',
                        to_jsonb(CAST(:role AS text)),
                        TRUE
                    ),
                    modified_dt = NOW()
                WHERE gi.polymorphic_discriminator = 'actor_instance'
                  AND gi.category = 'generic'
                  AND gi.type = 'actor'
                  AND gi.subtype = 'system_user'
                  AND COALESCE(gi.is_deleted, FALSE) = FALSE
                  AND gi.uid = :uid
                RETURNING gi.uid
                """
            ),
            {"uid": int(candidate), "role": normalized_role},
        ).fetchone()
        return row is not None

    normalized_identifier = candidate.lower()
    row = session.execute(
        text(
            """
            UPDATE generic_instance gi
            SET json_addl = jsonb_set(
                    COALESCE(gi.json_addl, '{}'::jsonb),
                    '{role}',
                    to_jsonb(CAST(:role AS text)),
                    TRUE
                ),
                modified_dt = NOW()
            WHERE gi.polymorphic_discriminator = 'actor_instance'
              AND gi.category = 'generic'
              AND gi.type = 'actor'
              AND gi.subtype = 'system_user'
              AND COALESCE(gi.is_deleted, FALSE) = FALSE
              AND (
                    lower(COALESCE(gi.json_addl->>'login_identifier', '')) = :identifier
                 OR lower(COALESCE(gi.json_addl->>'email', '')) = :identifier
              )
            RETURNING gi.uid
            """
        ),
        {"identifier": normalized_identifier, "role": normalized_role},
    ).fetchone()
    return row is not None
