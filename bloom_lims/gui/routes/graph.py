from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3
from bloom_lims.graph_support import (
    build_graph_elements_for_start as _shared_build_graph_elements_for_start,
    build_graph_object_payload,
    namespace_external_graph,
    normalize_graph_request_params as _shared_normalize_graph_request_params,
    resolve_external_ref_by_index,
)
from bloom_lims.gui.deps import _require_graph_admin, _resolve_auth_email, _resolve_auth_role, require_auth
from bloom_lims.gui.jinja import templates
from bloom_lims.integrations.atlas.client import AtlasClientError
from bloom_lims.integrations.atlas.service import AtlasDependencyError, AtlasService


router = APIRouter()


DAGS_DIRECTORY = "dags"


def _build_dag_filename(timestamp: datetime | None = None) -> str:
    dag_timestamp = (timestamp or datetime.now(UTC)).strftime("%Y%m%d%H%M%S")
    return os.path.join(DAGS_DIRECTORY, f"dag_{dag_timestamp}.json")


GRAPH_CATEGORY_COLORS = {
    "workflow": "#00FF7F",
    "workflow_step": "#ADFF2F",
    "container": "#8B00FF",
    "content": "#00BFFF",
    "equipment": "#FF4500",
    "data": "#FFD700",
    "actor": "#FF69B4",
    "action": "#FF8C00",
    "test_requisition": "#FFA500",
    "health_event": "#DC143C",
    "file": "#00FF00",
    "subject": "#9370DB",
    "object_set": "#FF6347",
    "generic": "#FF1493",
}

GRAPH_SUBTYPE_COLORS = {
    "well": "#70658C",
    "file_set": "#228080",
}


def _graph_node_color(category: str, obj_type: str, subtype: str) -> str:
    if obj_type in GRAPH_SUBTYPE_COLORS:
        return GRAPH_SUBTYPE_COLORS[obj_type]
    if subtype in GRAPH_SUBTYPE_COLORS:
        return GRAPH_SUBTYPE_COLORS[subtype]
    return GRAPH_CATEGORY_COLORS.get(category, "#888888")


def _normalize_graph_request_params(
    start_euid: str | None,
    depth: int | None,
) -> tuple[str, int]:
    return _shared_normalize_graph_request_params(start_euid, depth)


def _build_graph_elements_for_start(bobj: BloomObj, start_euid: str, depth: int) -> tuple[list, list]:
    return _shared_build_graph_elements_for_start(bobj, start_euid, depth)


@router.get("/dagg", response_class=HTMLResponse)
async def dagg(request: Request, _auth=Depends(require_auth)):
    return RedirectResponse(url="/dindex2", status_code=303)


@router.get("/dindex2", response_class=HTMLResponse)
async def dindex2(
    request: Request,
    globalZoom: float = Query(default=0),
    start_euid: str | None = Query(default=None),
    depth: int | None = Query(default=None, ge=1, le=10),
    merge_ref: int | None = Query(default=None, ge=0),
    auth=Depends(require_auth),
):
    resolved_start_euid, resolved_depth = _normalize_graph_request_params(
        start_euid=start_euid,
        depth=depth,
    )
    user_data = auth if isinstance(auth, dict) else request.session.get("user_data", {})
    user_role = _resolve_auth_role(auth, request)

    template = templates.get_template("modern/dag_explorer.html")
    context = {
        "request": request,
        "globalZoom": globalZoom,
        "start_euid": resolved_start_euid,
        "depth": resolved_depth,
        "merge_ref": merge_ref,
        "is_admin": user_role == "ADMIN",
        "udat": user_data,
    }
    return HTMLResponse(content=template.render(**context))


@router.get("/api/graph/data")
async def api_graph_data(
    request: Request,
    start_euid: str | None = Query(default=None),
    depth: int = Query(default=4, ge=1, le=10),
    auth=Depends(require_auth),
):
    resolved_start_euid, resolved_depth = _normalize_graph_request_params(
        start_euid=start_euid,
        depth=depth,
    )
    user_email = _resolve_auth_email(auth, request)
    logging.info(
        "Graph data request start_euid=%s depth=%s user=%s",
        resolved_start_euid,
        resolved_depth,
        user_email,
    )

    try:
        bobj = BloomObj(BLOOMdb3(app_username=user_email))
        nodes, edges = _build_graph_elements_for_start(bobj, resolved_start_euid, resolved_depth)
        return {
            "elements": {"nodes": nodes, "edges": edges},
            "meta": {"start_euid": resolved_start_euid, "depth": resolved_depth},
        }
    except Exception as exc:
        logging.error(
            "Graph data request failed start_euid=%s depth=%s user=%s error=%s",
            resolved_start_euid,
            resolved_depth,
            user_email,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to load graph data")


@router.get("/api/object/{euid}")
async def api_graph_object_detail(
    request: Request,
    euid: str,
    auth=Depends(require_auth),
):
    user_email = _resolve_auth_email(auth, request)
    bobj = BloomObj(BLOOMdb3(app_username=user_email))

    try:
        return build_graph_object_payload(bobj, euid)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Object not found: {euid}")


@router.get("/api/graph/external")
async def api_external_graph(
    request: Request,
    source_euid: str,
    ref_index: int = Query(..., ge=0),
    depth: int = Query(default=4, ge=1, le=10),
    auth=Depends(require_auth),
):
    user_email = _resolve_auth_email(auth, request)
    bobj = BloomObj(BLOOMdb3(app_username=user_email))
    try:
        source_obj = bobj.get_by_euid(source_euid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Object not found: {source_euid}") from exc

    try:
        ref = resolve_external_ref_by_index(source_obj, ref_index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ref.graph_expandable:
        raise HTTPException(status_code=424, detail=ref.reason or "External graph unavailable")

    try:
        payload = AtlasService().client.get_graph_data(
            start_euid=ref.root_euid,
            depth=depth,
            tenant_id=ref.tenant_id,
        )
    except (AtlasDependencyError, AtlasClientError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return namespace_external_graph(
        payload,
        ref=ref,
        ref_index=ref_index,
        source_euid=source_euid,
    )


@router.get("/api/graph/external/object")
async def api_external_graph_object(
    request: Request,
    source_euid: str,
    ref_index: int = Query(..., ge=0),
    euid: str = Query(...),
    auth=Depends(require_auth),
):
    user_email = _resolve_auth_email(auth, request)
    bobj = BloomObj(BLOOMdb3(app_username=user_email))
    try:
        source_obj = bobj.get_by_euid(source_euid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Object not found: {source_euid}") from exc

    try:
        ref = resolve_external_ref_by_index(source_obj, ref_index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ref.graph_expandable:
        raise HTTPException(status_code=424, detail=ref.reason or "External object unavailable")

    try:
        return AtlasService().client.get_graph_object_detail(euid=euid, tenant_id=ref.tenant_id)
    except (AtlasDependencyError, AtlasClientError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/get_node_info")
async def get_node_info(request: Request, euid, _auth=Depends(require_auth)):
    user_email = _resolve_auth_email(_auth, request)
    bobj = BloomObj(BLOOMdb3(app_username=user_email))
    node_dat = bobj.get_by_euid(euid)

    if node_dat:
        return {
            "name": node_dat.name,
            "type": node_dat.type,
            "euid": node_dat.euid,
            "subtype": node_dat.subtype,
            "status": node_dat.bstatus,
            "json_addl": json.dumps(node_dat.json_addl),
        }
    return {"error": "Node not found"}


@router.get("/get_node_property")
async def get_node_property(request: Request, euid: str, key: str):
    bo = BloomObj(BLOOMdb3(app_username=""))

    try:
        boi = bo.get_by_euid(euid)
        if boi is None:
            return JSONResponse({"error": "Node not found"}, status_code=404)

        property_value = boi.json_addl.get("properties", {}).get(key, "Property Not Found")
        return JSONResponse({key: property_value})
    except Exception as exc:
        logging.error("Error retrieving node property: %s", exc)
        return JSONResponse(
            {"error": f"Error retrieving node property: {exc}"}, status_code=500
        )


@router.post("/api/lineage")
async def api_create_lineage(
    request: Request,
    auth=Depends(require_auth),
):
    _require_graph_admin(auth, request)
    data = await request.json()

    parent_euid = (data.get("parent_euid") or "").strip()
    child_euid = (data.get("child_euid") or "").strip()
    relationship_type = (data.get("relationship_type") or "generic").strip() or "generic"

    if not parent_euid or not child_euid:
        raise HTTPException(status_code=400, detail="parent_euid and child_euid are required")
    if parent_euid == child_euid:
        raise HTTPException(status_code=400, detail="parent_euid and child_euid must differ")

    user_email = _resolve_auth_email(auth, request)
    bobj = BloomObj(BLOOMdb3(app_username=user_email))
    instance_cls = bobj.Base.classes.generic_instance
    lineage_cls = bobj.Base.classes.generic_instance_lineage

    parent_obj = (
        bobj.session.query(instance_cls)
        .filter(instance_cls.euid == parent_euid, instance_cls.is_deleted == False)
        .first()
    )
    child_obj = (
        bobj.session.query(instance_cls)
        .filter(instance_cls.euid == child_euid, instance_cls.is_deleted == False)
        .first()
    )
    if parent_obj is None:
        raise HTTPException(status_code=404, detail=f"Parent not found: {parent_euid}")
    if child_obj is None:
        raise HTTPException(status_code=404, detail=f"Child not found: {child_euid}")

    existing = (
        bobj.session.query(lineage_cls)
        .filter(
            lineage_cls.parent_instance_uid == parent_obj.uid,
            lineage_cls.child_instance_uid == child_obj.uid,
            lineage_cls.relationship_type == relationship_type,
            lineage_cls.is_deleted == False,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Lineage already exists: {child_euid} -> {parent_euid} ({relationship_type})",
        )

    try:
        new_lineage = bobj.create_generic_instance_lineage_by_euids(
            parent_instance_euid=parent_euid,
            child_instance_euid=child_euid,
            relationship_type=relationship_type,
        )
        bobj.session.flush()
        bobj.session.commit()
        logging.info(
            "Graph lineage created euid=%s parent=%s child=%s rel=%s user=%s",
            new_lineage.euid,
            parent_euid,
            child_euid,
            relationship_type,
            user_email,
        )
        return {"success": True, "euid": str(new_lineage.euid)}
    except HTTPException:
        raise
    except Exception as exc:
        bobj.session.rollback()
        logging.error(
            "Graph lineage create failed parent=%s child=%s rel=%s user=%s error=%s",
            parent_euid,
            child_euid,
            relationship_type,
            user_email,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to create lineage")


@router.delete("/api/object/{euid}")
async def api_delete_object(
    request: Request,
    euid: str,
    hard_delete: bool = False,
    auth=Depends(require_auth),
):
    _require_graph_admin(auth, request)
    user_email = _resolve_auth_email(auth, request)
    bobj = BloomObj(BLOOMdb3(app_username=user_email))
    try:
        obj = bobj.get_by_euid(euid)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Object not found: {euid}")

    try:
        bobj.delete_obj(obj)
        bobj.session.flush()
        bobj.session.commit()
        logging.info(
            "Graph object deleted euid=%s hard_delete_requested=%s user=%s",
            euid,
            hard_delete,
            user_email,
        )
        return {
            "success": True,
            "message": f"Object {euid} soft-deleted",
            "hard_delete_applied": False,
        }
    except Exception as exc:
        bobj.session.rollback()
        logging.error("Failed to delete object %s: %s", euid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete object")
