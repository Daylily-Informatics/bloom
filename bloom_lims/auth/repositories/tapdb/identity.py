"""Shared ID helpers for TapDB-backed auth repositories."""

from __future__ import annotations

import re
import secrets
from typing import Any

from daylily_tapdb.models.instance import generic_instance


def _normalize_prefix(prefix: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(prefix or "").strip().lower())
    return normalized or "auth"


def normalize_public_id(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    return candidate


def generate_public_id(*, prefix: str = "auth") -> str:
    created = f"{_normalize_prefix(prefix)}_{secrets.token_hex(16)}"
    return created


def ensure_public_id_property(
    properties: dict[str, Any],
    key: str = "id",
    *,
    prefix: str = "auth",
) -> str:
    resolved = normalize_public_id(properties.get(key))
    if resolved is not None:
        properties[key] = resolved
        return resolved
    created = generate_public_id(prefix=prefix)
    properties[key] = created
    return created


def resolve_public_id(
    instance: generic_instance,
    properties: dict[str, Any],
    *,
    key: str = "id",
    aliases: tuple[str, ...] = (),
    prefix: str = "auth",
) -> str:
    for candidate in (key, *aliases, "id", "public_id"):
        resolved = normalize_public_id(properties.get(candidate))
        if resolved is not None:
            return resolved
    raise ValueError(
        f"TapDB auth instance {getattr(instance, 'euid', None)!r} is missing explicit public id"
    )
