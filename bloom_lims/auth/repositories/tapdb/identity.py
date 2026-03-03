"""Shared ID helpers for TapDB-backed auth repositories."""

from __future__ import annotations

import uuid
from typing import Any

from daylily_tapdb.models.instance import generic_instance

_PUBLIC_ID_NAMESPACE = uuid.UUID("ee74fef0-c7c5-4c7b-a2bc-2f8f7c10f8b0")


def parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def ensure_uuid_property(properties: dict[str, Any], key: str = "id") -> uuid.UUID:
    parsed = parse_uuid(properties.get(key))
    if parsed is not None:
        properties[key] = str(parsed)
        return parsed
    created = uuid.uuid4()
    properties[key] = str(created)
    return created


def fallback_public_id(instance: generic_instance) -> uuid.UUID:
    seed = (
        f"{instance.euid or ''}|"
        f"{instance.category}/{instance.type}/{instance.subtype}/{instance.version}|"
        f"{instance.uuid}"
    )
    return uuid.uuid5(_PUBLIC_ID_NAMESPACE, seed)


def resolve_public_id(
    instance: generic_instance,
    properties: dict[str, Any],
    *,
    key: str = "id",
    aliases: tuple[str, ...] = (),
) -> uuid.UUID:
    for candidate in (key, *aliases, "id", "public_id", "uuid"):
        parsed = parse_uuid(properties.get(candidate))
        if parsed is not None:
            return parsed
    return fallback_public_id(instance)

