"""Small, current database projections for the Bloom dashboards."""

from __future__ import annotations

from sqlalchemy import func


def queue_summary(bdb) -> dict:
    """Count active objects without transferring their metadata into Python."""
    model = bdb.Base.classes.generic_instance
    kind = model.json_addl["properties"]["beta_kind"].as_string()
    groups = (
        bdb.session.query(kind, model.bstatus, func.count(model.uid))
        .filter(model.is_deleted.is_(False))
        .group_by(kind, model.bstatus)
        .all()
    )
    result = {
        "objects_total": 0,
        "queue_runtime_total": 0,
        "queue_runtime_in_progress": 0,
        "queue_runtime_complete": 0,
        "queue_runtime_exception": 0,
        "workflows_total": 0,
        "workflows_active": 0,
        "queue_kinds": [],
        "work_item_kinds": [],
    }
    for raw_kind, raw_status, count in groups:
        result["objects_total"] += count
        kind_value = str(raw_kind or "").strip()
        status = str(raw_status or "").strip().lower()
        if kind_value == "queue_definition":
            if raw_kind not in result["queue_kinds"]:
                result["queue_kinds"].append(raw_kind)
            result["queue_runtime_total"] += count
            if status in {"active", "open", "in_progress"}:
                result["queue_runtime_in_progress"] += count
            elif status in {"complete", "completed"}:
                result["queue_runtime_complete"] += count
            elif status in {"exception", "failed", "error"}:
                result["queue_runtime_exception"] += count
        elif kind_value == "beta_work_item":
            if raw_kind not in result["work_item_kinds"]:
                result["work_item_kinds"].append(raw_kind)
            result["workflows_total"] += count
            if status in {"open", "active"}:
                result["workflows_active"] += count
    return result


def recent_instances(bdb, *, beta_kinds: list | None = None) -> list:
    """Return only the five displayed rows and their displayed columns."""
    if beta_kinds == []:
        return []
    model = bdb.Base.classes.generic_instance
    query = bdb.session.query(
        model.uid,
        model.euid,
        model.name,
        model.category,
        model.type,
        model.subtype,
        model.bstatus,
        model.created_dt,
    ).filter(model.is_deleted.is_(False))
    if beta_kinds is not None:
        query = query.filter(
            model.json_addl["properties"]["beta_kind"].as_string().in_(beta_kinds)
        )
    ordering = [model.created_dt.desc()]
    if beta_kinds is not None:
        ordering = [model.created_dt.desc().nullslast(), model.uid.asc()]
    return query.order_by(*ordering).limit(5).all()
