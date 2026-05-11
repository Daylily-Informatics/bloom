"""TapDB-backed repository for Bloom user API tokens."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from daylily_tapdb import require_seeded_templates
from daylily_tapdb.factory import InstanceFactory
from daylily_tapdb.models.instance import generic_instance
from daylily_tapdb.templates import TemplateManager
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.auth.repositories.tapdb.identity import (
    ensure_public_id_property,
    normalize_public_id,
    resolve_public_id,
)
from bloom_lims.config import get_settings

TOKEN_TEMPLATE_CODE = "BBX/auth/user-api-token/1.0/"
TOKEN_USAGE_LOG_TEMPLATE_CODE = "BBX/auth/user-api-token-usage-log/1.0/"

TOKEN_PREFIX = "BBX"
TOKEN_USAGE_PREFIX = "BBX"
_UNSET = object()


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
class UserTokenStateRecord:
    id: str
    token_id: str
    object_version: int
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
    """Stores token identities/state/usage using generic TapDB objects."""

    def __init__(self, db: Session):
        self.db = db
        self.domain_code = str(get_settings().tapdb.domain_code).strip().upper()
        self.templates = TemplateManager()
        self.factory = InstanceFactory(
            self.templates,
            domain_code=self.domain_code,
        )
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
    ) -> tuple[UserTokenRecord, UserTokenStateRecord]:
        self._ensure_templates_bootstrapped()
        now = datetime.now(UTC)
        token_properties = {
            "user_id": str(user_id),
            "token_name": token_name,
            "token_prefix": token_prefix,
            "scope": scope,
            "object_version": 1,
            "token_hash": token_hash,
            "status": "ACTIVE",
            "expires_at": expires_at.isoformat(),
            "last_used_at": None,
            "revoked_at": None,
            "revoked_by": None,
            "revocation_reason": None,
            "note": note,
            "created_by": str(created_by) if created_by else None,
            "created_at": now.isoformat(),
            "updated_by": str(created_by) if created_by else None,
            "updated_at": now.isoformat(),
        }
        ensure_public_id_property(token_properties, "id", prefix="tok")
        token_instance = self.factory.create_instance(
            session=self.db,
            template_code=TOKEN_TEMPLATE_CODE,
            name=token_name,
            properties=token_properties,
        )
        self.db.commit()

        token = self._to_token(token_instance)
        state = self._to_state(token_instance)
        if token is None or state is None:
            raise ValueError("Failed to persist token")
        return token, state

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

    def get_token(
        self, token_id: str
    ) -> tuple[UserTokenRecord, UserTokenStateRecord] | None:
        self._ensure_templates_bootstrapped()
        token_instance = self._find_token_instance(token_id)
        if token_instance is None:
            return None
        token = self._to_token(token_instance)
        if token is None:
            return None
        state = self._to_state(token_instance)
        if state is None:
            return None
        return token, state

    def get_current_state(self, token_id: str) -> UserTokenStateRecord | None:
        self._ensure_templates_bootstrapped()
        token_instance = self._find_token_instance(token_id)
        if token_instance is None:
            return None
        return self._to_state(token_instance)

    def update_token_state(
        self,
        *,
        token_id: str,
        status: str | None = None,
        expires_at: datetime | None = None,
        last_used_at: datetime | None | object = _UNSET,
        revoked_at: datetime | None | object = _UNSET,
        revoked_by: str | None | object = _UNSET,
        revocation_reason: str | None | object = _UNSET,
        updated_by: str | None = None,
        note: str | None | object = _UNSET,
    ) -> UserTokenStateRecord:
        self._ensure_templates_bootstrapped()
        token_instance = self._find_token_instance(token_id)
        if token_instance is None:
            raise ValueError(f"Unknown token_id: {token_id}")

        props = self._props(token_instance)
        object_version = self._require_object_version(props, object_type="token")
        if status is not None:
            props["status"] = status
        if expires_at is not None:
            props["expires_at"] = expires_at.isoformat()
        if last_used_at is not _UNSET:
            props["last_used_at"] = (
                last_used_at.isoformat() if isinstance(last_used_at, datetime) else None
            )
        if revoked_at is not _UNSET:
            props["revoked_at"] = (
                revoked_at.isoformat() if isinstance(revoked_at, datetime) else None
            )
        if revoked_by is not _UNSET:
            props["revoked_by"] = str(revoked_by) if revoked_by else None
        if revocation_reason is not _UNSET:
            props["revocation_reason"] = revocation_reason
        if note is not _UNSET:
            props["note"] = note
        props["object_version"] = object_version + 1
        props["updated_by"] = str(updated_by) if updated_by else None
        props["updated_at"] = datetime.now(UTC).isoformat()
        self._write_props(token_instance, props)
        self.db.commit()
        record = self._to_state(token_instance)
        if record is None:
            raise ValueError("Failed to persist token state")
        return record

    def find_current_state_by_hash(
        self, token_hash: str
    ) -> UserTokenStateRecord | None:
        self._ensure_templates_bootstrapped()
        for token_instance in self._instances_for_template(TOKEN_TEMPLATE_CODE):
            state = self._to_state(token_instance)
            if state is None:
                continue
            if state.token_hash != token_hash:
                continue
            return state
        return None

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
        for usage_instance in self._instances_for_template(
            TOKEN_USAGE_LOG_TEMPLATE_CODE
        ):
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
            token_name=str(
                props.get("token_name") or token_instance.name or token_instance.euid
            ),
            token_prefix=str(props.get("token_prefix") or ""),
            scope=str(props.get("scope") or ""),
            created_at=_to_dt(props.get("created_at")) or token_instance.created_dt,
            euid=token_instance.euid,
        )

    def _to_state(
        self, token_instance: generic_instance
    ) -> UserTokenStateRecord | None:
        props = self._props(token_instance)
        token_id = resolve_public_id(token_instance, props, prefix="tok")
        expires_at = _to_dt(props.get("expires_at"))
        token_hash = str(props.get("token_hash") or "")
        status = str(props.get("status") or "")
        if not token_hash or not status or expires_at is None:
            return None
        try:
            object_version = int(props["object_version"])
        except (KeyError, TypeError, ValueError):
            return None
        return UserTokenStateRecord(
            id=token_id,
            token_id=token_id,
            object_version=object_version,
            token_hash=token_hash,
            status=status,
            expires_at=expires_at,
            last_used_at=_to_dt(props.get("last_used_at")),
            revoked_at=_to_dt(props.get("revoked_at")),
            revoked_by=normalize_public_id(props.get("revoked_by")),
            revocation_reason=props.get("revocation_reason"),
            note=props.get("note"),
            created_by=normalize_public_id(props.get("created_by")),
            created_at=_to_dt(props.get("created_at")) or token_instance.created_dt,
            euid=token_instance.euid,
        )

    def _to_usage(
        self, usage_instance: generic_instance
    ) -> UserTokenUsageRecord | None:
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
            request_timestamp=_to_dt(props.get("request_timestamp"))
            or usage_instance.created_dt,
            euid=usage_instance.euid,
        )

    def _instances_for_template(self, template_code: str) -> list[generic_instance]:
        category, type_name, subtype, version = _parse_template_code(template_code)
        stmt = (
            select(generic_instance)
            .where(
                generic_instance.domain_code == self.domain_code,
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
        require_seeded_templates(
            self.db,
            [
                (TOKEN_TEMPLATE_CODE, TOKEN_PREFIX),
                (TOKEN_USAGE_LOG_TEMPLATE_CODE, TOKEN_USAGE_PREFIX),
            ],
            app_name="Bloom",
            domain_code=self.domain_code,
            template_manager=self.templates,
        )
        self._templates_bootstrapped = True

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

    def _write_props(
        self, instance: generic_instance, properties: dict[str, Any]
    ) -> None:
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

    def _require_object_version(
        self, properties: dict[str, Any], *, object_type: str
    ) -> int:
        try:
            object_version = int(properties["object_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"{object_type} object is missing properties.object_version"
            ) from exc
        if object_version < 1:
            raise ValueError(
                f"{object_type} object has invalid properties.object_version"
            )
        return object_version
