"""
BLOOM LIMS API v1 - Statistics Endpoints

Dashboard statistics, aggregations, and recent activity for the modern UI.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from bloom_lims.schemas import (
    DashboardStatsSchema,
    RecentActivityItem,
    RecentActivitySchema,
    DashboardResponseSchema,
)
from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["Statistics"])


def _props(instance: Any) -> Dict[str, Any]:
    payload = instance.json_addl if isinstance(instance.json_addl, dict) else {}
    props = payload.get("properties", {})
    return props if isinstance(props, dict) else {}


def _beta_kind(instance: Any) -> str:
    return str(_props(instance).get("beta_kind") or "").strip()


def get_bdb(username: str = "anonymous"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3

    return BLOOMdb3(app_username=username)


@router.get("/dashboard", response_model=DashboardResponseSchema)
async def get_dashboard_stats(user: APIUser = Depends(require_api_auth)):
    """
    Get dashboard statistics and recent activity.

    Returns aggregated counts for assays, workflows, equipment, reagents,
    and recent activity across all object types.
    """
    try:
        bdb = get_bdb(user.email)

        # Gather statistics
        stats = DashboardStatsSchema()
        generic_rows: list[Any] = []

        try:
            generic_rows = (
                bdb.session.query(bdb.Base.classes.generic_instance)
                .filter_by(is_deleted=False)
                .all()
            )
            queue_definitions = [
                row for row in generic_rows if _beta_kind(row) == "queue_definition"
            ]
            work_items = [
                row for row in generic_rows if _beta_kind(row) == "beta_work_item"
            ]
            open_work_items = [
                row
                for row in work_items
                if str(getattr(row, "bstatus", "") or "").strip().lower() in {"open", "active"}
            ]

            stats.assays_total = len(queue_definitions)
            stats.workflows_total = len(work_items)
            stats.workflows_active = len(open_work_items)

            # Equipment counts
            eq_class = bdb.Base.classes.equipment_instance
            stats.equipment_total = (
                bdb.session.query(eq_class).filter_by(is_deleted=False).count()
            )
            stats.equipment_active = stats.equipment_total

            # Reagent/Content counts
            content_class = bdb.Base.classes.content_instance
            stats.reagents_total = (
                bdb.session.query(content_class)
                .filter(
                    content_class.is_deleted == False,
                    content_class.subtype.like("%reagent%"),
                )
                .count()
            )
            stats.samples_total = (
                bdb.session.query(content_class).filter_by(is_deleted=False).count()
            )

            # Container counts
            container_class = bdb.Base.classes.container_instance
            stats.containers_total = (
                bdb.session.query(container_class).filter_by(is_deleted=False).count()
            )

        except Exception as e:
            logger.warning(f"Error gathering stats: {e}")

        # Gather recent activity
        recent_activity = RecentActivitySchema()

        try:
            recent_assays = sorted(
                [row for row in generic_rows if _beta_kind(row) == "queue_definition"],
                key=lambda row: row.created_dt or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )[:5]
            recent_activity.recent_assays = [
                RecentActivityItem(
                    euid=a.euid,
                    name=a.name,
                    type=a.type or "queue_runtime",
                    subtype=a.subtype,
                    status=a.bstatus,
                    created_dt=a.created_dt,
                )
                for a in recent_assays
            ]

            recent_workflows = sorted(
                [row for row in generic_rows if _beta_kind(row) == "beta_work_item"],
                key=lambda row: row.created_dt or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )[:5]
            recent_activity.recent_workflows = [
                RecentActivityItem(
                    euid=w.euid,
                    name=w.name,
                    type=w.type or "queue_runtime",
                    subtype=w.subtype,
                    status=w.bstatus,
                    created_dt=w.created_dt,
                )
                for w in recent_workflows
            ]

        except Exception as e:
            logger.warning(f"Error gathering recent activity: {e}")

        return DashboardResponseSchema(
            stats=stats,
            recent_activity=recent_activity,
            generated_at=datetime.now(UTC),
        )

    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
