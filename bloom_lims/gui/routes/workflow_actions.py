from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from bloom_lims.core.action_execution import (
    ActionExecutionError,
    execute_action_for_instance,
    normalize_action_execute_payload,
)
from bloom_lims.gui.deps import require_auth


router = APIRouter()


@router.post("/workflow_step_action")
async def workflow_step_action(request: Request, _auth=Depends(require_auth)):
    try:
        payload = await request.json()
        req = normalize_action_execute_payload(payload)
        user_data = request.session.get("user_data", {})
        actor_email = user_data.get("email", "bloomui-user")
        actor_user_id = user_data.get("cognito_sub") or user_data.get("sub")

        result = execute_action_for_instance(
            req,
            app_username=actor_email,
            actor_email=actor_email,
            actor_user_id=actor_user_id,
            user_preferences=user_data,
        )
        return JSONResponse(status_code=200, content=result)
    except ActionExecutionError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())
    except Exception as exc:
        error_id = str(uuid.uuid4())
        logging.exception("Unexpected /workflow_step_action error id=%s: %s", error_id, exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Action execution failed (error_id={error_id})",
                "error_fields": [],
                "error_id": error_id,
            },
        )

