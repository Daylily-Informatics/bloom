"""
BLOOM LIMS API v1 - Statistics Endpoints

Dashboard statistics, aggregations, and recent activity for the modern UI.
"""

import logging
from datetime import datetime
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

        try:
            # Workflow/Assay counts
            wf_class = bdb.Base.classes.workflow_instance
            stats.workflows_total = (
                bdb.session.query(wf_class).filter_by(is_deleted=False).count()
            )
            stats.assays_total = (
                bdb.session.query(wf_class)
                .filter_by(is_deleted=False, is_singleton=True)
                .count()
            )
            stats.workflows_active = stats.workflows_total

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
                    content_class.b_sub_type.like("%reagent%"),
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
            wf_class = bdb.Base.classes.workflow_instance

            # Recent assays (singleton workflows)
            recent_assays = (
                bdb.session.query(wf_class)
                .filter_by(is_deleted=False, is_singleton=True)
                .order_by(wf_class.created_dt.desc())
                .limit(5)
                .all()
            )
            recent_activity.recent_assays = [
                RecentActivityItem(
                    euid=a.euid,
                    name=a.name,
                    b_type=a.btype or "workflow",
                    b_sub_type=a.b_sub_type,
                    status=a.bstatus,
                    created_dt=a.created_dt,
                )
                for a in recent_assays
            ]

            # Recent workflows
            recent_workflows = (
                bdb.session.query(wf_class)
                .filter_by(is_deleted=False)
                .order_by(wf_class.created_dt.desc())
                .limit(5)
                .all()
            )
            recent_activity.recent_workflows = [
                RecentActivityItem(
                    euid=w.euid,
                    name=w.name,
                    b_type=w.btype or "workflow",
                    b_sub_type=w.b_sub_type,
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
            generated_at=datetime.utcnow(),
        )

    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

