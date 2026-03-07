"""TapDB-backed repository for Bloom user API tokens."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from daylily_tapdb.factory import InstanceFactory
from daylily_tapdb.models.instance import generic_instance
from daylily_tapdb.models.template import generic_template
from daylily_tapdb.templates import TemplateManager
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.auth.repositories.tapdb.identity import (
    ensure_public_id_property,
    normalize_public_id,
    resolve_public_id,
)

TOKEN_TEMPLATE_CODE = "bloom/auth/user-api-token/1.0/"
TOKEN_REVISION_TEMPLATE_CODE = "bloom/auth/user-api-token-revision/1.0/"
TOKEN_USAGE_LOG_TEMPLATE_CODE = "bloom/auth/user-api-token-usage-log/1.0/"

TOKEN_PREFIX = "BTP"
TOKEN_REVISION_PREFIX = "BTR"
TOKEN_USAGE_PREFIX = "BTG"


def _parse_template_code(template_code: str) -> tuple[str, str, str, str]:
    parts = template_code.strip("/").split("/")
    if len(parts) != 4:
        raise ValueError(f"Invalid template code: {template_code}")
    return parts[0], parts[1], parts[2], parts[3]


def _to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class UserTokenRecord:
    id: str
    user_id: str
    token_name: str
    token_prefix: str
    scope: str
    created_at: datetime | None
    euid: str | None = None


@dataclass(frozen=True)
class UserTokenRevisionRecord:
    id: str
    token_id: str
    revision_no: int
    token_hash: str
    status: str
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    revoked_by: str | None
    revocation_reason: str | None
    note: str | None
    created_by: str | None
    created_at: datetime | None
    euid: str | None = None


@dataclass(frozen=True)
class UserTokenUsageRecord:
    id: str
    token_id: str
    user_id: str
    endpoint: str
    http_method: str
    response_status: int
    ip_address: str | None
    user_agent: str | None
    request_metadata: dict[str, Any] | None
    request_timestamp: datetime | None
    euid: str | None = None


class TapdbUserAPITokenRepository:
    """Stores token identities/revisions/usage using generic TapDB objects."""

    def __init__(self, db: Session):
        self.db = db
        self.templates = TemplateManager()
        self.factory = InstanceFactory(self.templates)
        self._templates_bootstrapped = False

    def create_token(
        self,
        *,
        user_id: str,
        token_name: str,
        token_prefix: str,
        scope: str,
        token_hash: str,
        expires_at: datetime,
        created_by: str | None,
        note: str | None = None,
    ) -> tuple[UserTokenRecord, UserTokenRevisionRecord]:
        self._ensure_templates_bootstrapped()
        token_properties = {
            "user_id": str(user_id),
            "token_name": token_name,
            "token_prefix": token_prefix,
            "scope": scope,
            "created_by": str(created_by) if created_by else None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        token_id = ensure_public_id_property(token_properties, "id", prefix="tok")
        token_instance = self.factory.create_instance(
            session=self.db,
            template_code=TOKEN_TEMPLATE_CODE,
            name=token_name,
            properties=token_properties,
        )

        revision_properties = {
            "token_id": str(token_id),
            "revision_no": 1,
            "token_hash": token_hash,
            "status": "ACTIVE",
            "expires_at": expires_at.isoformat(),
            "last_used_at": None,
            "revoked_at": None,
            "revoked_by": None,
            "revocation_reason": None,
            "note": note,
            "created_by": str(created_by) if created_by else None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        ensure_public_id_property(revision_properties, "id", prefix="tokrev")
        revision_instance = self.factory.create_instance(
            session=self.db,
            template_code=TOKEN_REVISION_TEMPLATE_CODE,
            name=f"{token_name} revision 1",
            properties=revision_properties,
        )
        self.factory.link_instances(
            session=self.db,
            parent=token_instance,
            child=revision_instance,
            relationship_type="revision",
        )
        self.db.commit()

        token = self._to_token(token_instance)
        revision = self._to_revision(revision_instance)
        if token is None or revision is None:
            raise ValueError("Failed to persist token")
        return token, revision

    def list_tokens(
        self,
        *,
        user_id: str | None = None,
    ) -> list[UserTokenRecord]:
        self._ensure_templates_bootstrapped()
        tokens: list[UserTokenRecord] = []
        for token_instance in self._instances_for_template(TOKEN_TEMPLATE_CODE):
            token = self._to_token(token_instance)
            if token is None:
                continue
            if user_id is not None and token.user_id != user_id:
                continue
            tokens.append(token)
        tokens.sort(
            key=lambda row: row.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return tokens

    def get_token(self, token_id: str) -> tuple[UserTokenRecord, UserTokenRevisionRecord] | None:
        self._ensure_templates_bootstrapped()
        token_instance = self._find_token_instance(token_id)
        if token_instance is None:
            return None
        token = self._to_token(token_instance)
        if token is None:
            return None
        revision = self.get_latest_revision(token.id)
        if revision is None:
            return None
        return token, revision

    def get_latest_revision(self, token_id: str) -> UserTokenRevisionRecord | None:
        revisions: list[UserTokenRevisionRecord] = []
        for revision_instance in self._instances_for_template(TOKEN_REVISION_TEMPLATE_CODE):
            revision = self._to_revision(revision_instance)
            if revision is None:
                continue
            if revision.token_id != token_id:
                continue
            revisions.append(revision)
        if not revisions:
            return None
        revisions.sort(key=lambda row: row.revision_no, reverse=True)
        return revisions[0]

    def create_revision(
        self,
        *,
        token_id: str,
        revision_no: int,
        token_hash: str,
        status: str,
        expires_at: datetime,
        last_used_at: datetime | None,
        revoked_at: datetime | None,
        revoked_by: str | None,
        revocation_reason: str | None,
        created_by: str | None,
        note: str | None,
    ) -> UserTokenRevisionRecord:
        self._ensure_templates_bootstrapped()
        revision_properties = {
            "token_id": str(token_id),
            "revision_no": revision_no,
            "token_hash": token_hash,
            "status": status,
            "expires_at": expires_at.isoformat(),
            "last_used_at": last_used_at.isoformat() if last_used_at else None,
            "revoked_at": revoked_at.isoformat() if revoked_at else None,
            "revoked_by": str(revoked_by) if revoked_by else None,
            "revocation_reason": revocation_reason,
            "note": note,
            "created_by": str(created_by) if created_by else None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        ensure_public_id_property(revision_properties, "id", prefix="tokrev")
        revision_instance = self.factory.create_instance(
            session=self.db,
            template_code=TOKEN_REVISION_TEMPLATE_CODE,
            name=f"token-{token_id} revision {revision_no}",
            properties=revision_properties,
        )
        token_instance = self._find_token_instance(token_id)
        if token_instance is not None:
            self.factory.link_instances(
                session=self.db,
                parent=token_instance,
                child=revision_instance,
                relationship_type="revision",
            )
        self.db.commit()
        record = self._to_revision(revision_instance)
        if record is None:
            raise ValueError("Failed to persist token revision")
        return record

    def find_latest_revision_by_hash(self, token_hash: str) -> UserTokenRevisionRecord | None:
        revisions: list[UserTokenRevisionRecord] = []
        for revision_instance in self._instances_for_template(TOKEN_REVISION_TEMPLATE_CODE):
            revision = self._to_revision(revision_instance)
            if revision is None:
                continue
            if revision.token_hash != token_hash:
                continue
            revisions.append(revision)
        if not revisions:
            return None
        revisions.sort(key=lambda row: row.revision_no, reverse=True)
        return revisions[0]

    def log_usage(
        self,
        *,
        token_id: str,
        user_id: str,
        endpoint: str,
        http_method: str,
        response_status: int,
        ip_address: str | None,
        user_agent: str | None,
        request_metadata: dict[str, Any] | None,
    ) -> None:
        self._ensure_templates_bootstrapped()
        usage_properties = {
            "token_id": str(token_id),
            "user_id": str(user_id),
            "endpoint": endpoint,
            "http_method": http_method,
            "response_status": int(response_status),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "request_metadata": request_metadata,
            "request_timestamp": datetime.now(UTC).isoformat(),
        }
        ensure_public_id_property(usage_properties, "id", prefix="tokuse")
        usage_instance = self.factory.create_instance(
            session=self.db,
            template_code=TOKEN_USAGE_LOG_TEMPLATE_CODE,
            name=f"{http_method.upper()} {endpoint}",
            properties=usage_properties,
        )
        token_instance = self._find_token_instance(token_id)
        if token_instance is not None:
            self.factory.link_instances(
                session=self.db,
                parent=token_instance,
                child=usage_instance,
                relationship_type="usage",
            )
        self.db.commit()

    def get_usage_logs(
        self,
        *,
        token_id: str,
        limit: int = 100,
    ) -> list[UserTokenUsageRecord]:
        usage: list[UserTokenUsageRecord] = []
        for usage_instance in self._instances_for_template(TOKEN_USAGE_LOG_TEMPLATE_CODE):
            usage_record = self._to_usage(usage_instance)
            if usage_record is None:
                continue
            if usage_record.token_id != token_id:
                continue
            usage.append(usage_record)
        usage.sort(
            key=lambda row: row.request_timestamp or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return usage[:limit]

    def count_usage(self, *, token_id: str) -> int:
        return len(self.get_usage_logs(token_id=token_id, limit=1_000_000))

    def _find_token_instance(self, token_id: str) -> generic_instance | None:
        for token_instance in self._instances_for_template(TOKEN_TEMPLATE_CODE):
            props = self._props(token_instance)
            if resolve_public_id(token_instance, props, prefix="tok") == token_id:
                return token_instance
        return None

    def _to_token(self, token_instance: generic_instance) -> UserTokenRecord | None:
        props = self._props(token_instance)
        token_id = resolve_public_id(token_instance, props, prefix="tok")
        user_id = normalize_public_id(props.get("user_id"))
        if user_id is None:
            return None
        return UserTokenRecord(
            id=token_id,
            user_id=user_id,
            token_name=str(props.get("token_name") or token_instance.name or token_instance.euid),
            token_prefix=str(props.get("token_prefix") or ""),
            scope=str(props.get("scope") or ""),
            created_at=_to_dt(props.get("created_at")) or token_instance.created_dt,
            euid=token_instance.euid,
        )

    def _to_revision(self, revision_instance: generic_instance) -> UserTokenRevisionRecord | None:
        props = self._props(revision_instance)
        token_id = normalize_public_id(props.get("token_id"))
        revision_id = resolve_public_id(revision_instance, props, prefix="tokrev")
        expires_at = _to_dt(props.get("expires_at"))
        if token_id is None or expires_at is None:
            return None
        return UserTokenRevisionRecord(
            id=revision_id,
            token_id=token_id,
            revision_no=int(props.get("revision_no", 0)),
            token_hash=str(props.get("token_hash") or ""),
            status=str(props.get("status") or "UNKNOWN"),
            expires_at=expires_at,
            last_used_at=_to_dt(props.get("last_used_at")),
            revoked_at=_to_dt(props.get("revoked_at")),
            revoked_by=normalize_public_id(props.get("revoked_by")),
            revocation_reason=props.get("revocation_reason"),
            note=props.get("note"),
            created_by=normalize_public_id(props.get("created_by")),
            created_at=_to_dt(props.get("created_at")) or revision_instance.created_dt,
            euid=revision_instance.euid,
        )

    def _to_usage(self, usage_instance: generic_instance) -> UserTokenUsageRecord | None:
        props = self._props(usage_instance)
        usage_id = resolve_public_id(usage_instance, props, prefix="tokuse")
        token_id = normalize_public_id(props.get("token_id"))
        user_id = normalize_public_id(props.get("user_id"))
        if token_id is None or user_id is None:
            return None
        metadata = props.get("request_metadata")
        if metadata is not None and not isinstance(metadata, dict):
            metadata = None
        return UserTokenUsageRecord(
            id=usage_id,
            token_id=token_id,
            user_id=user_id,
            endpoint=str(props.get("endpoint") or ""),
            http_method=str(props.get("http_method") or ""),
            response_status=int(props.get("response_status", 0) or 0),
            ip_address=props.get("ip_address"),
            user_agent=props.get("user_agent"),
            request_metadata=metadata,
            request_timestamp=_to_dt(props.get("request_timestamp")) or usage_instance.created_dt,
            euid=usage_instance.euid,
        )

    def _instances_for_template(self, template_code: str) -> list[generic_instance]:
        category, type_name, subtype, version = _parse_template_code(template_code)
        stmt = (
            select(generic_instance)
            .where(
                generic_instance.category == category,
                generic_instance.type == type_name,
                generic_instance.subtype == subtype,
                generic_instance.version == version,
                generic_instance.is_deleted.is_(False),
            )
            .order_by(generic_instance.created_dt.desc())
        )
        return list(self.db.execute(stmt).scalars())

    def _ensure_templates_bootstrapped(self) -> None:
        if self._templates_bootstrapped:
            return
        self._ensure_template(
            template_code=TOKEN_TEMPLATE_CODE,
            template_name="Bloom User API Token",
            instance_prefix=TOKEN_PREFIX,
        )
        self._ensure_template(
            template_code=TOKEN_REVISION_TEMPLATE_CODE,
            template_name="Bloom User API Token Revision",
            instance_prefix=TOKEN_REVISION_PREFIX,
        )
        self._ensure_template(
            template_code=TOKEN_USAGE_LOG_TEMPLATE_CODE,
            template_name="Bloom User API Token Usage Log",
            instance_prefix=TOKEN_USAGE_PREFIX,
        )
        self._templates_bootstrapped = True
        self.db.flush()

    def _ensure_template(
        self,
        *,
        template_code: str,
        template_name: str,
        instance_prefix: str,
    ) -> generic_template:
        category, type_name, subtype, version = _parse_template_code(template_code)
        self._ensure_prefix_sequence(instance_prefix)
        stmt = (
            select(generic_template)
            .where(
                generic_template.category == category,
                generic_template.type == type_name,
                generic_template.subtype == subtype,
                generic_template.version == version,
            )
            .limit(1)
        )
        existing = self.db.execute(stmt).scalar_one_or_none()
        if existing is not None:
            if existing.is_deleted:
                existing.is_deleted = False
            return existing

        template = generic_template(
            name=template_name,
            polymorphic_discriminator="generic_template",
            category=category,
            type=type_name,
            subtype=subtype,
            version=version,
            instance_prefix=instance_prefix,
            instance_polymorphic_identity="generic_instance",
            json_addl={"managed_by": "bloom", "domain": "auth"},
            bstatus="active",
            is_singleton=False,
            is_deleted=False,
        )
        self.db.add(template)
        self.db.flush()
        self.templates.clear_cache()
        return template

    def _ensure_prefix_sequence(self, prefix: str) -> None:
        normalized = prefix.strip().upper()
        if not re.fullmatch(r"[A-HJ-KMNP-TV-Z]{2,3}", normalized):
            raise ValueError(f"Invalid TAPDB instance prefix: {prefix!r}")
        seq_name = f"{normalized.lower()}_instance_seq"
        self.db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))

    def _props(self, instance: generic_instance) -> dict[str, Any]:
        payload = instance.json_addl or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            properties = {}
            payload["properties"] = properties
            instance.json_addl = payload
        return properties

    def _write_props(self, instance: generic_instance, properties: dict[str, Any]) -> None:
        payload = instance.json_addl or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["properties"] = properties
        instance.json_addl = payload
        flag_modified(instance, "json_addl")
