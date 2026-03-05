"""Action execution API endpoint for schema-driven action forms."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from bloom_lims.api.v1.dependencies import APIUser, require_write
from bloom_lims.core.action_execution import (
    ActionExecutionError,
    execute_action_for_instance,
    normalize_action_execute_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/actions", tags=["Actions"])


@router.post("/execute")
async def execute_action(
    payload: dict[str, Any],
    user: APIUser = Depends(require_write),
):
    """Execute an object/workflow/workflow-step action using captured_data payload."""
    try:
        req = normalize_action_execute_payload(payload)
        result = execute_action_for_instance(
            req,
            app_username=user.email,
            actor_email=user.email,
            actor_user_id=user.user_id,
            user_preferences=None,
        )
        return result
    except ActionExecutionError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())
    except Exception as exc:  # defensive final handler
        logger.exception("Unexpected /api/v1/actions/execute error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Action execution failed",
                "error_fields": [],
            },
        )
