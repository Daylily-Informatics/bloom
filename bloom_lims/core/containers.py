"""Deprecated container helpers rewritten to use graph edges, not JSON links."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bloom_lims.exceptions import DatabaseError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class ContainerPosition:
    """Represents a position within a container."""

    row: int
    column: int

    @classmethod
    def from_well(cls, well: str) -> "ContainerPosition":
        well = well.upper().strip()
        match = re.match(r"^([A-Z])(\\d+)$", well)
        if not match:
            raise ValidationError(f"Invalid well format: {well}", field="position")
        row = ord(match.group(1)) - ord("A")
        column = int(match.group(2)) - 1
        return cls(row=row, column=column)

    @classmethod
    def from_index(cls, index: int, num_columns: int) -> "ContainerPosition":
        return cls(row=index // num_columns, column=index % num_columns)

    def to_well(self) -> str:
        return f"{chr(ord('A') + self.row)}{self.column + 1}"

    def to_index(self, num_columns: int) -> int:
        return self.row * num_columns + self.column

    def __str__(self) -> str:
        return self.to_well()


def get_container_layout(container: Any) -> dict[str, Any]:
    if not container or not hasattr(container, "json_addl"):
        return {"rows": 1, "columns": 1, "type": "unknown"}

    payload = container.json_addl or {}
    layout = payload.get("layout", {}) if isinstance(payload, dict) else {}
    rows = int(layout.get("rows", 8) or 8)
    columns = int(layout.get("columns", 12) or 12)
    return {
        "rows": rows,
        "columns": columns,
        "type": container.subtype or container.type,
        "total_positions": rows * columns,
    }


def get_container_contents(
    session: Session,
    base,
    container_euid: str,
) -> list[dict[str, Any]]:
    logger.debug("Getting contents of container: %s", container_euid)
    container = _get_instance(session, base, container_euid)
    if container is None:
        raise NotFoundError(
            f"Container not found: {container_euid}",
            resource_type="container",
            resource_id=container_euid,
        )

    stmt = (
        select(base.classes.generic_instance_lineage)
        .where(
            base.classes.generic_instance_lineage.parent_instance_uid == container.uid,
            base.classes.generic_instance_lineage.relationship_type == "contains",
            base.classes.generic_instance_lineage.is_deleted.is_(False),
        )
        .order_by(base.classes.generic_instance_lineage.created_dt.asc())
    )
    rows = []
    for lineage in session.execute(stmt).scalars().all():
        child = getattr(lineage, "child_instance", None)
        if child is None or getattr(child, "is_deleted", False):
            continue
        payload = getattr(lineage, "json_addl", {}) or {}
        props = payload.get("properties") if isinstance(payload, dict) else {}
        rows.append(
            {
                "position": str((props or {}).get("position") or "").strip() or None,
                "euid": child.euid,
                "name": child.name,
                "type": child.type,
            }
        )
    return rows


def place_in_container(
    session: Session,
    base,
    container_euid: str,
    object_euid: str,
    position: str,
) -> bool:
    logger.debug("Placing %s in %s at %s", object_euid, container_euid, position)
    try:
        container = _get_instance(session, base, container_euid)
        if container is None:
            raise NotFoundError(
                f"Container not found: {container_euid}",
                resource_type="container",
                resource_id=container_euid,
            )
        obj = _get_instance(session, base, object_euid)
        if obj is None:
            raise NotFoundError(
                f"Object not found: {object_euid}",
                resource_type="object",
                resource_id=object_euid,
            )

        normalized_position = str(position or "").strip().upper()
        ContainerPosition.from_well(normalized_position)

        for entry in get_container_contents(session, base, container_euid):
            if entry.get("position") == normalized_position:
                raise ValidationError(
                    f"Position {normalized_position} is already occupied",
                    field="position",
                )

        lineage = base.classes.generic_instance_lineage(
            name=f"{container.name} :: {obj.name}",
            parent_type=(
                f"{container.category}:{container.type}:{container.subtype}:{container.version}"
            ),
            child_type=f"{obj.category}:{obj.type}:{obj.subtype}:{obj.version}",
            relationship_type="contains",
            parent_instance_uid=container.uid,
            child_instance_uid=obj.uid,
            category="generic",
            type="container",
            subtype="contains",
            version="1.0",
            polymorphic_discriminator="generic_instance_lineage",
            bstatus="active",
            json_addl={
                "properties": {
                    "position": normalized_position,
                    "placed_at": datetime.now(UTC).isoformat(),
                }
            },
        )
        session.add(lineage)
        session.flush()
        return True
    except (NotFoundError, ValidationError):
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error placing object in container: %s", exc)
        raise DatabaseError(f"Failed to place object in container: {exc}")


def remove_from_container(
    session: Session,
    base,
    container_euid: str,
    position: str,
) -> str | None:
    logger.debug("Removing object from %s at %s", container_euid, position)
    container = _get_instance(session, base, container_euid)
    if container is None:
        raise NotFoundError(
            f"Container not found: {container_euid}",
            resource_type="container",
            resource_id=container_euid,
        )

    normalized_position = str(position or "").strip().upper()
    stmt = (
        select(base.classes.generic_instance_lineage)
        .where(
            base.classes.generic_instance_lineage.parent_instance_uid == container.uid,
            base.classes.generic_instance_lineage.relationship_type == "contains",
            base.classes.generic_instance_lineage.is_deleted.is_(False),
        )
        .order_by(base.classes.generic_instance_lineage.created_dt.asc())
    )
    for lineage in session.execute(stmt).scalars().all():
        payload = getattr(lineage, "json_addl", {}) or {}
        props = payload.get("properties") if isinstance(payload, dict) else {}
        if str((props or {}).get("position") or "").strip().upper() != normalized_position:
            continue
        lineage.is_deleted = True
        session.flush()
        child = getattr(lineage, "child_instance", None)
        return getattr(child, "euid", None)
    return None


def _get_instance(session: Session, base, euid: str):
    return (
        session.query(base.classes.generic_instance)
        .filter(
            base.classes.generic_instance.euid == str(euid or "").strip().upper(),
            base.classes.generic_instance.is_deleted.is_(False),
        )
        .first()
    )


try:  # pragma: no cover - compatibility export only
    from bloom_lims.bobjs import BloomObj as _BloomObj

    BloomContainer = _BloomObj
except ImportError:  # pragma: no cover - defensive
    BloomContainer = None
