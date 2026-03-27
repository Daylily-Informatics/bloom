"""Deprecated lineage helpers rewritten around graph edges.

These helpers no longer persist lineage membership trees inside
``json_addl``. Relationship truth is stored only in TapDB lineage rows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bloom_lims.exceptions import DatabaseError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)


class BloomLineageMixin:
    """Compatibility mixin for legacy callers.

    Depth is no longer cached in ``json_addl``. Legacy callers only get a
    conservative derived view.
    """

    @property
    def lineage_depth(self) -> int:
        try:
            lineages = getattr(self, "child_of_lineages", None)
            if lineages is None:
                return 0
            return 0 if lineages.count() == 0 else 1
        except Exception:  # pragma: no cover - defensive
            return 0

    @property
    def is_lineage_root(self) -> bool:
        return self.lineage_depth == 0


def create_lineage(
    session: Session,
    base,
    name: str,
    lineage_type: str,
    root_object: Any | None = None,
    json_addl: dict[str, Any] | None = None,
    **kwargs,
) -> Any:
    logger.debug("Creating lineage edge: name=%s type=%s", name, lineage_type)
    if not name or not lineage_type:
        raise ValidationError("name and lineage_type are required")

    parent = root_object or kwargs.get("parent_object")
    child = kwargs.get("child_object")
    if parent is None and kwargs.get("parent_euid"):
        parent = _get_instance(session, base, kwargs["parent_euid"])
    if child is None and kwargs.get("child_euid"):
        child = _get_instance(session, base, kwargs["child_euid"])
    if parent is None or child is None:
        raise ValidationError(
            "Legacy lineage tree creation is retired; supply parent and child objects",
            field="lineage",
        )

    try:
        lineage = base.classes.generic_instance_lineage(
            name=name,
            parent_type=f"{parent.category}:{parent.type}:{parent.subtype}:{parent.version}",
            child_type=f"{child.category}:{child.type}:{child.subtype}:{child.version}",
            relationship_type=str(lineage_type).strip().lower(),
            parent_instance_uid=parent.uid,
            child_instance_uid=child.uid,
            category="generic",
            type="lineage",
            subtype=str(lineage_type).strip().lower(),
            version="1.0",
            polymorphic_discriminator="generic_instance_lineage",
            bstatus="active",
            json_addl={
                "properties": {
                    **(json_addl or {}),
                    "created_at": datetime.now(UTC).isoformat(),
                }
            },
        )
        session.add(lineage)
        session.flush()
        return lineage
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error creating lineage: %s", exc)
        raise DatabaseError(f"Failed to create lineage: {exc}", operation="insert")


def get_lineage_by_euid(
    session: Session,
    base,
    euid: str,
) -> Any | None:
    if not euid:
        return None
    try:
        return (
            session.query(base.classes.generic_instance_lineage)
            .filter(
                base.classes.generic_instance_lineage.euid == str(euid).upper(),
                base.classes.generic_instance_lineage.is_deleted.is_(False),
            )
            .first()
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error looking up lineage %s: %s", euid, exc)
        return None


def add_to_lineage(
    session: Session,
    base,
    lineage_euid: str,
    object_euid: str,
    parent_euid: str | None = None,
) -> bool:
    logger.debug("Adding %s via lineage template %s", object_euid, lineage_euid)
    lineage = get_lineage_by_euid(session, base, lineage_euid)
    if lineage is None:
        raise NotFoundError(
            f"Lineage not found: {lineage_euid}",
            resource_type="lineage",
            resource_id=lineage_euid,
        )
    parent = _get_instance(session, base, parent_euid) if parent_euid else lineage.parent_instance
    child = _get_instance(session, base, object_euid)
    if parent is None or child is None:
        raise NotFoundError(
            "Parent or child object not found for lineage add",
            resource_type="lineage",
            resource_id=lineage_euid,
        )
    create_lineage(
        session,
        base,
        name=f"{parent.euid}->{child.euid}",
        lineage_type=lineage.relationship_type,
        root_object=parent,
        child_object=child,
        json_addl={},
    )
    return True


def get_lineage_tree(
    session: Session,
    base,
    lineage_euid: str,
) -> dict[str, Any]:
    lineage = get_lineage_by_euid(session, base, lineage_euid)
    if lineage is None:
        raise NotFoundError(
            f"Lineage not found: {lineage_euid}",
            resource_type="lineage",
            resource_id=lineage_euid,
        )
    parent = getattr(lineage, "parent_instance", None)
    child = getattr(lineage, "child_instance", None)
    return {
        "euid": lineage.euid,
        "name": lineage.name,
        "type": lineage.relationship_type,
        "parent": getattr(parent, "euid", None),
        "child": getattr(child, "euid", None),
        "properties": ((lineage.json_addl or {}).get("properties") or {}),
    }


def get_object_lineage(
    session: Session,
    base,
    object_euid: str,
) -> dict[str, Any] | None:
    obj = _get_instance(session, base, object_euid)
    if obj is None:
        return None

    parents_stmt = (
        select(base.classes.generic_instance_lineage)
        .where(
            base.classes.generic_instance_lineage.child_instance_uid == obj.uid,
            base.classes.generic_instance_lineage.is_deleted.is_(False),
        )
        .order_by(base.classes.generic_instance_lineage.created_dt.asc())
    )
    children_stmt = (
        select(base.classes.generic_instance_lineage)
        .where(
            base.classes.generic_instance_lineage.parent_instance_uid == obj.uid,
            base.classes.generic_instance_lineage.is_deleted.is_(False),
        )
        .order_by(base.classes.generic_instance_lineage.created_dt.asc())
    )
    return {
        "euid": obj.euid,
        "parents": [
            {
                "lineage_euid": row.euid,
                "relationship_type": row.relationship_type,
                "parent_euid": getattr(row.parent_instance, "euid", None),
            }
            for row in session.execute(parents_stmt).scalars().all()
        ],
        "children": [
            {
                "lineage_euid": row.euid,
                "relationship_type": row.relationship_type,
                "child_euid": getattr(row.child_instance, "euid", None),
            }
            for row in session.execute(children_stmt).scalars().all()
        ],
    }


def _get_instance(session: Session, base, euid: str | None):
    if not euid:
        return None
    return (
        session.query(base.classes.generic_instance)
        .filter(
            base.classes.generic_instance.euid == str(euid).strip().upper(),
            base.classes.generic_instance.is_deleted.is_(False),
        )
        .first()
    )


try:  # pragma: no cover - compatibility export only
    from bloom_lims.bobjs import BloomObj as _BloomObj

    BloomLineage = _BloomObj
except ImportError:  # pragma: no cover - defensive
    BloomLineage = None
