"""Manual Atlas bridge APIs for query/status integration flows."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from bloom_lims.api.v1.dependencies import APIUser, require_external_atlas_api_enabled
from bloom_lims.auth.rbac import Permission
from bloom_lims.integrations.atlas.service import AtlasDependencyError, AtlasService
from bloom_lims.schemas.atlas_bridge import (
    AtlasTestStatusEventRequest,
    AtlasTestStatusEventResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external/atlas", tags=["External Atlas"])


def require_external_write(user: APIUser = Depends(require_external_atlas_api_enabled)) -> APIUser:
    if not user.has_permission(Permission.BLOOM_WRITE):
        raise HTTPException(status_code=403, detail="Write permission required")
    return user


@router.post(
    "/tests/{test_euid}/status-events",
    response_model=AtlasTestStatusEventResponse,
)
async def push_test_status_event(
    test_euid: str,
    payload: AtlasTestStatusEventRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    _ = user
    service = AtlasService()
    try:
        result = service.push_test_status_event(
            test_euid=test_euid,
            payload=payload.model_dump(mode="json"),
            idempotency_key=idempotency_key,
        )
        return AtlasTestStatusEventResponse(**result.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AtlasDependencyError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed pushing Atlas test status event")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
