"""Token-authenticated graph read endpoints for cross-system integrations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from bloom_lims.api.v1.dependencies import APIUser, require_api_auth
from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3
from bloom_lims.graph_support import (
    build_graph_elements_for_start,
    build_graph_object_payload,
    normalize_graph_request_params,
)


router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/data")
async def get_graph_data(
    start_euid: str | None = Query(default=None),
    depth: int = Query(default=4, ge=1, le=10),
    user: APIUser = Depends(require_api_auth),
):
    resolved_start_euid, resolved_depth = normalize_graph_request_params(start_euid, depth)
    try:
        bobj = BloomObj(BLOOMdb3(app_username=user.email))
        nodes, edges = build_graph_elements_for_start(bobj, resolved_start_euid, resolved_depth)
        return {
            "elements": {"nodes": nodes, "edges": edges},
            "meta": {"start_euid": resolved_start_euid, "depth": resolved_depth},
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load graph data: {exc}") from exc


@router.get("/object/{euid}")
async def get_graph_object(
    euid: str,
    user: APIUser = Depends(require_api_auth),
):
    try:
        bobj = BloomObj(BLOOMdb3(app_username=user.email))
        return build_graph_object_payload(bobj, euid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Object not found: {euid}") from exc
