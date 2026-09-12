#!/usr/bin/env python3
"""Create the bounded Bloom-owned read-only identity used by Kahlo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _write_new(path: Path, value: str) -> None:
    if not path.is_absolute() or path.resolve() != path or not path.parent.is_dir():
        raise ValueError("output must be a canonical path in an existing directory")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _replace(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + f".final-{os.getpid()}")
    _write_new(temporary, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> int:
    from daylily_tapdb.cli.context import set_cli_context
    from daylily_tapdb.cli.db_config import get_db_config
    from daylily_tapdb.runtime_principal import operator_connection
    from daylily_tapdb.security_context import (
        TapdbTransactionContext,
        apply_transaction_context,
        assert_operator_role,
    )
    from daylily_tapdb.user_store import create_or_get
    from daylily_tapdb.templates.loader import (
        find_tapdb_core_config_dir,
        load_template_configs,
        seed_templates,
    )
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from bloom_lims.auth.rbac import API_ACCESS_GROUP, BLOOM_READONLY_GROUP, Role
    from bloom_lims.config import get_settings
    from bloom_lims.auth.repositories.tapdb.groups import TapdbGroupRepository
    from bloom_lims.auth.repositories.tapdb.users import resolve_user_record, set_user_role
    from bloom_lims.auth.services.groups import GroupService
    from bloom_lims.auth.services.user_api_tokens import (
        TOKEN_STATUS_ACTIVE,
        TokenCreateInput,
        UserAPITokenService,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--secret-output", type=Path, required=True)
    parser.add_argument("--prior-attempt-receipt", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)

    username = "kahlo-bloom-reader@service.lsmc.bio"
    display_name = "Kahlo Bloom Read Only"
    scope = "internal_ro"
    group_codes = [BLOOM_READONLY_GROUP, API_ACCESS_GROUP]
    canonical_group_codes = sorted(code.strip().upper() for code in group_codes)
    with args.prior_attempt_receipt.open(encoding="utf-8") as handle:
        prior_attempt = json.load(handle)
    if prior_attempt.get("status") != "reserved":
        raise RuntimeError("prior failed attempt receipt is not reserved")
    prior_attempt_sha256 = _sha256(args.prior_attempt_receipt)
    reservation = {
        "schema_version": "bloom-kahlo-reader-reservation/v1",
        "status": "reserved",
        "username": username,
        "scope": scope,
        "prior_attempt_receipt": str(args.prior_attempt_receipt),
        "prior_attempt_sha256": prior_attempt_sha256,
    }
    _write_new(args.receipt, json.dumps(reservation, indent=2, sort_keys=True) + "\n")

    cfg = get_db_config(
        config_path=args.operator_config,
        client_id="bloom",
        database_name="bloom-day",
    )
    set_cli_context(
        config_path=args.operator_config,
        client_id="bloom",
        database_name="bloom-day",
    )
    get_settings()
    context = TapdbTransactionContext(
        config_identity=str(args.operator_config),
        schema_name=cfg["schema_name"],
        domain_code="M",
        owner_repo_name="bloom",
        tenant_id=cfg.get("tenant_id") or None,
        actor="bloom-migration-kahlo-reader",
        allow_global_rows=True,
    )

    plaintext = None
    core_dir = find_tapdb_core_config_dir().resolve()
    actor_templates = [
        item
        for item in load_template_configs(core_dir)
        if (
            item.get("category"),
            item.get("type"),
            item.get("subtype"),
            item.get("version"),
        )
        == ("actor", "user", "system", "1.0")
    ]
    if len(actor_templates) != 1 or actor_templates[0].get("instance_prefix") != "SYS":
        raise RuntimeError("installed TapDB lacks the exact packaged actor template")

    with operator_connection(
        cfg, isolation_level="REPEATABLE READ", read_only=False
    ) as connection:
        assert_operator_role(
            connection,
            schema_name=cfg["schema_name"],
            operator_user=cfg["operator_user"],
        )

        with Session(bind=connection, expire_on_commit=False) as session:
            apply_transaction_context(session, context, assert_runtime_role=False)
            template_rows_before = session.execute(
                text(
                    "SELECT * FROM generic_template "
                    "WHERE category = 'actor' AND type = 'user' "
                    "AND subtype = 'system' AND version = '1.0' "
                    "AND domain_code = 'M' ORDER BY uid"
                )
            ).mappings().all()
            core_rows_before = [
                dict(row)
                for row in template_rows_before
                if row["issuer_app_code"] == "daylily-tapdb"
            ]
            bloom_rows_before = [
                dict(row)
                for row in template_rows_before
                if row["issuer_app_code"] == "bloom"
            ]
            if len(core_rows_before) != 1 or bloom_rows_before:
                raise RuntimeError("actor template preflight differs from reviewed state")
            summary = seed_templates(
                session,
                actor_templates,
                overwrite=False,
                core_config_dir=core_dir,
                domain_code="M",
                owner_repo_name="bloom",
                domain_registry_path=Path(cfg["domain_registry_path"]),
                prefix_registry_path=Path(cfg["prefix_ownership_registry_path"]),
            )
            if summary.inserted != 1 or summary.updated != 0 or summary.skipped != 0:
                raise RuntimeError("actor template seed was not exactly one additive insert")
            template_rows_after = session.execute(
                text(
                    "SELECT * FROM generic_template "
                    "WHERE category = 'actor' AND type = 'user' "
                    "AND subtype = 'system' AND version = '1.0' "
                    "AND domain_code = 'M' ORDER BY uid"
                )
            ).mappings().all()
            core_rows_after = [
                dict(row)
                for row in template_rows_after
                if row["issuer_app_code"] == "daylily-tapdb"
            ]
            bloom_rows_after = [
                dict(row)
                for row in template_rows_after
                if row["issuer_app_code"] == "bloom"
            ]
            if core_rows_after != core_rows_before or len(bloom_rows_after) != 1:
                raise RuntimeError("actor template seed changed core history or scope")
            actor_template_uid = int(bloom_rows_after[0]["uid"])
            actor_template_euid = str(bloom_rows_after[0]["euid"])
            user, created = create_or_get(
                session,
                login_identifier=username,
                email=username,
                display_name=display_name,
                role="user",
                cognito_username=username,
            )
            if not set_user_role(session, user.uid, Role.READ_ONLY.value):
                raise RuntimeError("failed to bind canonical read-only role")
            session.commit()
            user_uid = int(user.uid)
            user_euid = str(user.euid)

        with Session(bind=connection, expire_on_commit=False) as session:
            apply_transaction_context(session, context, assert_runtime_role=False)
            GroupService(session).ensure_system_groups()

        for group_code in group_codes:
            with Session(bind=connection, expire_on_commit=False) as session:
                apply_transaction_context(session, context, assert_runtime_role=False)
                TapdbGroupRepository(session).add_user_to_group(
                    group_code=group_code,
                    user_id=str(user_uid),
                    added_by=str(user_uid),
                )

        with Session(bind=connection, expire_on_commit=False) as session:
            apply_transaction_context(session, context, assert_runtime_role=False)
            resolved = resolve_user_record(session, str(user_uid), include_inactive=True)
            groups = TapdbGroupRepository(session).get_user_group_codes(
                user_id=str(user_uid)
            )
            if resolved is None or resolved.role != Role.READ_ONLY.value:
                raise RuntimeError("created user is not canonically read-only")
            if sorted(groups) != canonical_group_codes:
                raise RuntimeError(f"unexpected service groups: {groups}")
            owner = session.execute(
                text(
                    "SELECT issuer_app_code FROM generic_instance "
                    "WHERE uid = :uid AND euid = :euid"
                ),
                {"uid": user_uid, "euid": user_euid},
            ).scalar_one()
            if owner != "bloom":
                raise RuntimeError(f"service user owner is not Bloom: {owner!r}")

        with Session(bind=connection, expire_on_commit=False) as session:
            apply_transaction_context(session, context, assert_runtime_role=False)
            token_service = UserAPITokenService(session)
            token_service.groups.ensure_system_groups()
            apply_transaction_context(session, context, assert_runtime_role=False)
            if scope not in token_service.allowed_scopes_for_roles(
                [Role.READ_ONLY.value]
            ):
                raise RuntimeError("read-only owner cannot issue internal_ro token")
            plaintext = token_service.generate_plaintext_token()
            _write_new(args.secret_output, plaintext + "\n")
            expires_at = datetime.now(UTC) + timedelta(days=90)
            token, revision = token_service.repo.create_token(
                user_id=str(user_uid),
                token_name="Kahlo Bloom DAG reader",
                token_prefix=token_service.display_prefix(plaintext),
                scope=scope,
                token_hash=token_service.hash_token(plaintext),
                expires_at=expires_at,
                created_by=str(user_uid),
                note="Bloom 10.0.1 migration: Kahlo read-only DAG access",
            )
            if revision.status != TOKEN_STATUS_ACTIVE or token.scope != scope:
                raise RuntimeError("native token state is not active/internal_ro")

        target_row = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        target = {
            "physical_database": str(target_row[0]),
            "schema_name": cfg["schema_name"],
            "operator_user": str(target_row[1]),
        }

    result = {
        "schema_version": "bloom-kahlo-reader-result/v1",
        "status": "applied",
        "prior_attempt_receipt": str(args.prior_attempt_receipt),
        "prior_attempt_sha256": prior_attempt_sha256,
        "target": target,
        "actor_template": {
            "uid": actor_template_uid,
            "euid": actor_template_euid,
            "issuer_app_code": "bloom",
            "category": "actor",
            "type": "user",
            "subtype": "system",
            "version": "1.0",
            "inserted": True,
            "core_template_unchanged": True,
        },
        "user": {
            "uid": user_uid,
            "euid": user_euid,
            "issuer_app_code": "bloom",
            "role": Role.READ_ONLY.value,
            "groups": canonical_group_codes,
            "created": created,
        },
        "token": {
            "id": token.id,
            "euid": token.euid,
            "revision_id": revision.id,
            "revision_euid": revision.euid,
            "revision_no": revision.revision_no,
            "scope": token.scope,
            "status": revision.status,
            "expires_at": revision.expires_at.isoformat(),
            "plaintext_sha256": hashlib.sha256(plaintext.encode()).hexdigest(),
        },
    }
    _replace(args.receipt, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "user_uid": user_uid,
                "user_euid": user_euid,
                "role": Role.READ_ONLY.value,
                "groups": canonical_group_codes,
                "scope": token.scope,
                "expires_at": revision.expires_at.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
