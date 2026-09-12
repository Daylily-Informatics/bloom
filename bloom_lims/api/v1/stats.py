"""
BLOOM LIMS API v1 - Statistics Endpoints

Dashboard statistics, aggregations, and recent activity for the modern UI.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from bloom_lims.dashboard_queries import queue_summary, recent_instances
from bloom_lims.schemas import (
    DashboardResponseSchema,
    DashboardStatsSchema,
    RecentActivityItem,
    RecentActivitySchema,
)

from .dependencies import APIUser, require_api_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["Statistics"])


def get_bdb(username: str = "anonymous"):
    """Get database connection."""
    from bloom_lims.tapdb_adapter import BLOOMdb3

    return BLOOMdb3(app_username=username)


@router.get("/dashboard", response_model=DashboardResponseSchema)
async def get_dashboard_stats(user: APIUser = Depends(require_api_auth)):
    """
    Get dashboard statistics and recent activity.

    Returns aggregated counts for queue runtime, workflows, equipment, reagents,
    and recent activity across all object types.
    """
    try:
        with get_bdb(user.email) as bdb:
            counts = queue_summary(bdb)
            stats = DashboardStatsSchema(
                queue_runtime_total=counts["queue_runtime_total"],
                queue_runtime_in_progress=counts["queue_runtime_in_progress"],
                queue_runtime_complete=counts["queue_runtime_complete"],
                queue_runtime_exception=counts["queue_runtime_exception"],
                workflows_total=counts["workflows_total"],
                workflows_active=counts["workflows_active"],
            )
            eq_class = bdb.Base.classes.equipment_instance
            stats.equipment_total = (
                bdb.session.query(eq_class).filter_by(is_deleted=False).count()
            )
            stats.equipment_active = stats.equipment_total
            content_class = bdb.Base.classes.content_instance
            stats.reagents_total = (
                bdb.session.query(content_class)
                .filter(
                    content_class.is_deleted.is_(False),
                    content_class.subtype.like("%reagent%"),
                )
                .count()
            )
            stats.samples_total = (
                bdb.session.query(content_class).filter_by(is_deleted=False).count()
            )
            container_class = bdb.Base.classes.container_instance
            stats.containers_total = (
                bdb.session.query(container_class).filter_by(is_deleted=False).count()
            )
            recent_activity = RecentActivitySchema(
                recent_queue_runtime=[
                    RecentActivityItem(
                        euid=row.euid,
                        name=row.name,
                        type=row.type or "queue_runtime",
                        subtype=row.subtype,
                        status=row.bstatus,
                        created_dt=row.created_dt,
                    )
                    for row in recent_instances(bdb, beta_kinds=counts["queue_kinds"])
                ],
                recent_workflows=[
                    RecentActivityItem(
                        euid=row.euid,
                        name=row.name,
                        type=row.type or "queue_runtime",
                        subtype=row.subtype,
                        status=row.bstatus,
                        created_dt=row.created_dt,
                    )
                    for row in recent_instances(
                        bdb, beta_kinds=counts["work_item_kinds"]
                    )
                ],
            )
        return DashboardResponseSchema(
            stats=stats,
            recent_activity=recent_activity,
            generated_at=datetime.now(UTC),
        )
    except Exception as exc:
        logger.exception("Error getting dashboard stats")
        raise HTTPException(
            status_code=500, detail="Unable to load dashboard statistics"
        ) from exc
