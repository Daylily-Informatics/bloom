"""TapDB-backed repository for Bloom tool API users."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from daylily_tapdb.factory import InstanceFactory
from daylily_tapdb.models.instance import generic_instance
from daylily_tapdb.models.template import generic_template
from daylily_tapdb.templates import TemplateManager
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bloom_lims.auth.repositories.tapdb.identity import ensure_uuid_property, parse_uuid, resolve_public_id

TOOL_API_USER_TEMPLATE_CODE = "bloom/auth/tool-api-user/1.0/"

# TAPDB instance prefixes exclude I/O/U; use a valid prefix for tool users.
TOOL_API_USER_PREFIX = "BTT"

_EXTERNAL_SYSTEM_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")


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


def normalize_external_system_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("external_system_key is required")
    if not _EXTERNAL_SYSTEM_KEY_PATTERN.fullmatch(normalized):
        raise ValueError(
            "external_system_key must match [a-z0-9][a-z0-9._:-]* and be <= 128 chars"
        )
    return normalized


@dataclass(frozen=True)
class ToolAPIUserRecord:
    id: uuid.UUID
    display_name: str
    external_system_key: str
    description: str | None
    role: str
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime | None
    metadata: dict[str, Any] | None
    euid: str | None = None


class TapdbToolAPIUserRepository:
    """Tool API user persistence using generic TapDB templates/instances."""

    def __init__(self, db: Session):
        self.db = db
        self.templates = TemplateManager()
        self.factory = InstanceFactory(self.templates)
        self._templates_bootstrapped = False

    def create_tool_user(
        self,
        *,
        display_name: str,
        external_system_key: str,
        description: str | None,
        role: str,
        created_by: uuid.UUID | None,
        metadata: dict[str, Any] | None,
    ) -> ToolAPIUserRecord:
        self._ensure_templates_bootstrapped()

        normalized_key = normalize_external_system_key(external_system_key)
        if self.get_tool_user_by_external_system_key(normalized_key) is not None:
            raise ValueError(f"Tool API user with external_system_key '{normalized_key}' already exists")

        cleaned_name = str(display_name or "").strip()
        if not cleaned_name:
            raise ValueError("display_name is required")

        properties = {
            "id": str(uuid.uuid4()),
            "display_name": cleaned_name,
            "external_system_key": normalized_key,
            "description": str(description).strip() if description else None,
            "role": str(role or "").strip(),
            "is_active": True,
            "created_by": str(created_by) if created_by else None,
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": metadata if isinstance(metadata, dict) else None,
        }
        ensure_uuid_property(properties, "id")

        instance = self.factory.create_instance(
            session=self.db,
            template_code=TOOL_API_USER_TEMPLATE_CODE,
            name=cleaned_name,
            properties=properties,
        )
        self.db.commit()

        record = self._to_tool_user(instance)
        if record is None:
            raise ValueError("Failed to create tool API user")
        return record

    def list_tool_users(self, *, include_inactive: bool = False) -> list[ToolAPIUserRecord]:
        self._ensure_templates_bootstrapped()
        users: list[ToolAPIUserRecord] = []
        for instance in self._instances_for_template(TOOL_API_USER_TEMPLATE_CODE):
            user = self._to_tool_user(instance)
            if user is None:
                continue
            if not include_inactive and not user.is_active:
                continue
            users.append(user)
        users.sort(
            key=lambda row: (
                row.display_name.lower(),
                row.created_at or datetime.min.replace(tzinfo=UTC),
            )
        )
        return users

    def get_tool_user(self, user_id: uuid.UUID) -> ToolAPIUserRecord | None:
        self._ensure_templates_bootstrapped()
        for instance in self._instances_for_template(TOOL_API_USER_TEMPLATE_CODE):
            props = self._props(instance)
            if resolve_public_id(instance, props) != user_id:
                continue
            return self._to_tool_user(instance)
        return None

    def get_tool_user_by_external_system_key(self, external_system_key: str) -> ToolAPIUserRecord | None:
        self._ensure_templates_bootstrapped()
        normalized = normalize_external_system_key(external_system_key)
        for instance in self._instances_for_template(TOOL_API_USER_TEMPLATE_CODE):
            props = self._props(instance)
            key_value = str(props.get("external_system_key") or "").strip().lower()
            if not key_value:
                continue
            if key_value != normalized:
                continue
            return self._to_tool_user(instance)
        return None

    def _to_tool_user(self, instance: generic_instance) -> ToolAPIUserRecord | None:
        props = self._props(instance)
        user_id = resolve_public_id(instance, props)
        display_name = str(props.get("display_name") or instance.name or "").strip()
        external_system_key = str(props.get("external_system_key") or "").strip().lower()
        role = str(props.get("role") or "").strip()
        if not display_name or not external_system_key or not role:
            return None

        metadata = props.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            metadata = None

        return ToolAPIUserRecord(
            id=user_id,
            display_name=display_name,
            external_system_key=external_system_key,
            description=props.get("description"),
            role=role,
            is_active=bool(props.get("is_active", True)),
            created_by=parse_uuid(props.get("created_by")),
            created_at=_to_dt(props.get("created_at")) or instance.created_dt,
            metadata=metadata,
            euid=instance.euid,
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
            template_code=TOOL_API_USER_TEMPLATE_CODE,
            template_name="Bloom Tool API User",
            instance_prefix=TOOL_API_USER_PREFIX,
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
