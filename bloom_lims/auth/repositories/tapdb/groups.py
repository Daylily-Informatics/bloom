"""TapDB-backed repository for Bloom auth groups/memberships."""

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


GROUP_TEMPLATE_CODE = "bloom/auth/user-group/1.0/"
GROUP_REVISION_TEMPLATE_CODE = "bloom/auth/user-group-revision/1.0/"
GROUP_MEMBERSHIP_TEMPLATE_CODE = "bloom/auth/user-group-membership/1.0/"

GROUP_PREFIX = "BGP"
GROUP_REVISION_PREFIX = "BGR"
GROUP_MEMBERSHIP_PREFIX = "BGM"


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
class GroupRecord:
    id: str
    group_code: str
    name: str
    description: str | None
    is_system_group: bool
    is_active: bool
    revision_no: int
    created_at: datetime | None
    euid: str | None = None


@dataclass(frozen=True)
class GroupMembershipRecord:
    id: str
    group_id: str
    group_code: str
    user_id: str
    is_active: bool
    joined_at: datetime | None
    added_by: str | None
    deactivated_at: datetime | None
    deactivated_by: str | None
    euid: str | None = None


class TapdbGroupRepository:
    """Group persistence using generic TapDB templates/instances."""

    def __init__(self, db: Session):
        self.db = db
        self.templates = TemplateManager()
        self.factory = InstanceFactory(self.templates)
        self._templates_bootstrapped = False

    def ensure_system_groups(self, group_codes: list[str]) -> None:
        self._ensure_templates_bootstrapped()
        for group_code in group_codes:
            normalized = str(group_code).strip().upper()
            if not normalized:
                continue
            if self.get_group_by_code(normalized) is None:
                self._create_group(
                    group_code=normalized,
                    name=normalized.replace("_", " ").title(),
                    description=f"System group: {normalized}",
                    is_system_group=True,
                    created_by=None,
                )
        self.db.commit()

    def list_groups(self, include_inactive: bool = False) -> list[GroupRecord]:
        self._ensure_templates_bootstrapped()
        groups: list[GroupRecord] = []
        for group_instance in self._instances_for_template(GROUP_TEMPLATE_CODE):
            group = self._to_group(group_instance)
            if group is None:
                continue
            if not include_inactive and not group.is_active:
                continue
            groups.append(group)
        groups.sort(key=lambda row: (row.group_code, row.revision_no))
        return groups

    def get_group_by_code(self, group_code: str) -> GroupRecord | None:
        self._ensure_templates_bootstrapped()
        lookup = str(group_code).strip().upper()
        if not lookup:
            return None
        for group_instance in self._instances_for_template(GROUP_TEMPLATE_CODE):
            props = self._props(group_instance)
            if str(props.get("group_code", "")).strip().upper() != lookup:
                continue
            group = self._to_group(group_instance)
            if group is None:
                continue
            return group
        return None

    def get_user_group_codes(self, user_id: str) -> list[str]:
        group_lookup = {group.id: group.group_code for group in self.list_groups(include_inactive=False)}
        memberships = self._list_memberships(user_id=user_id, include_inactive=False)
        codes: list[str] = []
        for membership in memberships:
            group_code = group_lookup.get(membership.group_id)
            if group_code and group_code not in codes:
                codes.append(group_code)
        return sorted(codes)

    def list_group_members(self, group_code: str) -> list[GroupMembershipRecord]:
        group = self.get_group_by_code(group_code)
        if group is None:
            return []
        members = self._list_memberships(group_id=group.id, include_inactive=True)
        members.sort(
            key=lambda row: (row.joined_at or datetime.min.replace(tzinfo=UTC)),
            reverse=True,
        )
        return members

    def add_user_to_group(
        self,
        *,
        group_code: str,
        user_id: str,
        added_by: str | None,
    ) -> GroupMembershipRecord:
        self._ensure_templates_bootstrapped()
        group = self.get_group_by_code(group_code)
        if group is None:
            raise ValueError(f"Unknown group_code: {group_code}")

        existing = self._find_membership(group_id=group.id, user_id=user_id)
        if existing is not None:
            props = self._props(existing)
            if not bool(props.get("is_active", True)):
                props["is_active"] = True
                props["deactivated_at"] = None
                props["deactivated_by"] = None
                self._write_props(existing, props)
                self.db.commit()
            restored = self._to_membership(existing, group_code=group.group_code)
            if restored is None:
                raise ValueError("Failed to reactivate membership")
            return restored

        membership_properties = {
            "group_id": str(group.id),
            "group_code": group.group_code,
            "user_id": str(user_id),
            "is_active": True,
            "joined_at": datetime.now(UTC).isoformat(),
            "added_by": str(added_by) if added_by else None,
            "deactivated_at": None,
            "deactivated_by": None,
        }
        ensure_public_id_property(membership_properties, "id", prefix="gmem")
        membership_instance = self.factory.create_instance(
            session=self.db,
            template_code=GROUP_MEMBERSHIP_TEMPLATE_CODE,
            name=f"{group.group_code} member {user_id}",
            properties=membership_properties,
        )

        group_instance = self._find_group_instance(group.id)
        if group_instance is not None:
            self.factory.link_instances(
                session=self.db,
                parent=group_instance,
                child=membership_instance,
                relationship_type="membership",
            )

        self.db.commit()
        result = self._to_membership(membership_instance, group_code=group.group_code)
        if result is None:
            raise ValueError("Failed to create membership")
        return result

    def remove_user_from_group(
        self,
        *,
        group_code: str,
        user_id: str,
        removed_by: str | None,
    ) -> GroupMembershipRecord | None:
        group = self.get_group_by_code(group_code)
        if group is None:
            return None
        membership_instance = self._find_membership(group_id=group.id, user_id=user_id)
        if membership_instance is None:
            return None
        props = self._props(membership_instance)
        if not bool(props.get("is_active", True)):
            return self._to_membership(membership_instance, group_code=group.group_code)
        props["is_active"] = False
        props["deactivated_at"] = datetime.now(UTC).isoformat()
        props["deactivated_by"] = str(removed_by) if removed_by else None
        self._write_props(membership_instance, props)
        self.db.commit()
        return self._to_membership(membership_instance, group_code=group.group_code)

    def _list_memberships(
        self,
        *,
        group_id: str | None = None,
        user_id: str | None = None,
        include_inactive: bool,
    ) -> list[GroupMembershipRecord]:
        memberships: list[GroupMembershipRecord] = []
        for membership_instance in self._instances_for_template(GROUP_MEMBERSHIP_TEMPLATE_CODE):
            record = self._to_membership(membership_instance)
            if record is None:
                continue
            if group_id and record.group_id != group_id:
                continue
            if user_id and record.user_id != user_id:
                continue
            if not include_inactive and not record.is_active:
                continue
            memberships.append(record)
        return memberships

    def _find_membership(
        self,
        *,
        group_id: str,
        user_id: str,
    ) -> generic_instance | None:
        for membership_instance in self._instances_for_template(GROUP_MEMBERSHIP_TEMPLATE_CODE):
            props = self._props(membership_instance)
            if normalize_public_id(props.get("group_id")) != group_id:
                continue
            if normalize_public_id(props.get("user_id")) != user_id:
                continue
            return membership_instance
        return None

    def _find_group_instance(self, group_id: str) -> generic_instance | None:
        for group_instance in self._instances_for_template(GROUP_TEMPLATE_CODE):
            props = self._props(group_instance)
            if resolve_public_id(group_instance, props, prefix="grp") == group_id:
                return group_instance
        return None

    def _create_group(
        self,
        *,
        group_code: str,
        name: str,
        description: str | None,
        is_system_group: bool,
        created_by: str | None,
    ) -> GroupRecord:
        group_properties = {
            "group_code": group_code,
            "is_system_group": bool(is_system_group),
            "is_active": True,
            "created_by": str(created_by) if created_by else None,
        }
        group_public_id = ensure_public_id_property(group_properties, "id", prefix="grp")

        group_instance = self.factory.create_instance(
            session=self.db,
            template_code=GROUP_TEMPLATE_CODE,
            name=name,
            properties=group_properties,
        )

        revision_properties = {
            "group_id": str(group_public_id),
            "revision_no": 1,
            "name": name,
            "description": description,
            "is_active": True,
            "is_system_group": bool(is_system_group),
            "created_by": str(created_by) if created_by else None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        ensure_public_id_property(revision_properties, "id", prefix="grev")
        revision_instance = self.factory.create_instance(
            session=self.db,
            template_code=GROUP_REVISION_TEMPLATE_CODE,
            name=f"{group_code} revision 1",
            properties=revision_properties,
        )
        self.factory.link_instances(
            session=self.db,
            parent=group_instance,
            child=revision_instance,
            relationship_type="revision",
        )

        group = self._to_group(group_instance)
        if group is None:
            raise ValueError("Failed to create group")
        return group

    def _to_group(self, group_instance: generic_instance) -> GroupRecord | None:
        props = self._props(group_instance)
        group_code = str(props.get("group_code", "")).strip().upper()
        if not group_code:
            return None
        group_id = resolve_public_id(group_instance, props, prefix="grp")
        revision = self._latest_revision_for_group(group_id)
        revision_props = self._props(revision) if revision is not None else {}
        return GroupRecord(
            id=group_id,
            group_code=group_code,
            name=str(revision_props.get("name") or group_instance.name or group_code),
            description=revision_props.get("description"),
            is_system_group=bool(revision_props.get("is_system_group", props.get("is_system_group", False))),
            is_active=bool(revision_props.get("is_active", props.get("is_active", True))),
            revision_no=int(revision_props.get("revision_no", 1)),
            created_at=_to_dt(revision_props.get("created_at")) or group_instance.created_dt,
            euid=group_instance.euid,
        )

    def _to_membership(
        self,
        membership_instance: generic_instance,
        *,
        group_code: str | None = None,
    ) -> GroupMembershipRecord | None:
        props = self._props(membership_instance)
        membership_id = resolve_public_id(membership_instance, props, prefix="gmem")
        group_id = normalize_public_id(props.get("group_id"))
        user_id = normalize_public_id(props.get("user_id"))
        if group_id is None or user_id is None:
            return None
        normalized_group_code = str(props.get("group_code") or group_code or "").strip().upper()
        if not normalized_group_code:
            group_instance = self._find_group_instance(group_id)
            if group_instance is not None:
                normalized_group_code = str(self._props(group_instance).get("group_code", "")).strip().upper()
        return GroupMembershipRecord(
            id=membership_id,
            group_id=group_id,
            group_code=normalized_group_code,
            user_id=user_id,
            is_active=bool(props.get("is_active", True)),
            joined_at=_to_dt(props.get("joined_at")) or membership_instance.created_dt,
            added_by=normalize_public_id(props.get("added_by")),
            deactivated_at=_to_dt(props.get("deactivated_at")),
            deactivated_by=normalize_public_id(props.get("deactivated_by")),
            euid=membership_instance.euid,
        )

    def _latest_revision_for_group(self, group_id: str) -> generic_instance | None:
        revisions: list[generic_instance] = []
        for revision_instance in self._instances_for_template(GROUP_REVISION_TEMPLATE_CODE):
            props = self._props(revision_instance)
            if normalize_public_id(props.get("group_id")) != group_id:
                continue
            revisions.append(revision_instance)
        if not revisions:
            return None
        revisions.sort(key=lambda row: int(self._props(row).get("revision_no", 0)), reverse=True)
        return revisions[0]

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
            template_code=GROUP_TEMPLATE_CODE,
            template_name="Bloom User Group",
            instance_prefix=GROUP_PREFIX,
        )
        self._ensure_template(
            template_code=GROUP_REVISION_TEMPLATE_CODE,
            template_name="Bloom User Group Revision",
            instance_prefix=GROUP_REVISION_PREFIX,
        )
        self._ensure_template(
            template_code=GROUP_MEMBERSHIP_TEMPLATE_CODE,
            template_name="Bloom User Group Membership",
            instance_prefix=GROUP_MEMBERSHIP_PREFIX,
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
