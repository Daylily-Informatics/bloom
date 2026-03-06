from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3
from bloom_lims.gui.deps import _require_graph_admin, _resolve_auth_email, _resolve_auth_role, require_auth
from bloom_lims.gui.jinja import templates


router = APIRouter()


DAG_OUTPUT_DIR = Path("./dags").resolve()
LEGACY_DAG_OUTPUT_DIR = Path(".").resolve()
DAG_FILE_GLOB = "dag_*.json"
DAG_MAX_FILES = 200
DAG_MAX_AGE_DAYS = 14


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
    legacy_start: str | None,
    legacy_depth: int | None,
) -> tuple[str, int]:
    resolved_start = (start_euid or legacy_start or "AY1").strip() or "AY1"

    try:
        resolved_depth = int(depth if depth is not None else legacy_depth if legacy_depth is not None else 4)
    except (TypeError, ValueError):
        resolved_depth = 4

    resolved_depth = max(1, min(resolved_depth, 10))
    return resolved_start, resolved_depth


def _resolve_dag_path(path_str: str) -> Path:
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    if candidate.exists():
        return candidate

    # Backward compatibility: older sessions may still point at ./dag_*.json.
    if candidate.name.startswith("dag_") and candidate.suffix == ".json":
        dags_candidate = DAG_OUTPUT_DIR / candidate.name
        if dags_candidate.exists():
            return dags_candidate
    return candidate


def _cleanup_dag_files(base_dir: Path) -> int:
    try:
        if not base_dir.exists():
            return 0

        dag_files = sorted(
            base_dir.glob(DAG_FILE_GLOB),
            key=lambda file_path: file_path.stat().st_mtime,
            reverse=True,
        )

        now = datetime.now()
        cutoff = now - timedelta(days=DAG_MAX_AGE_DAYS)
        deleted = 0
        for index, dag_file in enumerate(dag_files):
            try:
                mtime = datetime.fromtimestamp(dag_file.stat().st_mtime)
            except OSError:
                continue

            should_delete = index >= DAG_MAX_FILES or mtime < cutoff
            if should_delete:
                try:
                    dag_file.unlink(missing_ok=True)
                    deleted += 1
                except OSError:
                    logging.warning("Failed to delete stale DAG file: %s", dag_file)
        return deleted
    except OSError:
        logging.warning("Failed to scan DAG cleanup directory: %s", base_dir)
        return 0


def _build_graph_elements_for_start(bobj: BloomObj, start_euid: str, depth: int) -> tuple[list, list]:
    instance_result = {}
    lineage_result = {}

    for row in bobj.fetch_graph_data_by_node_depth(start_euid, depth):
        node_euid = row[0]
        if node_euid not in [None, "", "None"]:
            instance_result[node_euid] = {
                "euid": row[0],
                "name": row[2],
                "type": row[3],
                "category": row[4],
                "subtype": row[5],
                "version": row[6],
            }

        lineage_euid = row[8]
        if lineage_euid not in [None, "", "None"]:
            lineage_result[lineage_euid] = {
                "parent_euid": row[9],
                "child_euid": row[10],
                "lineage_euid": lineage_euid,
                "relationship_type": row[11] or "generic",
            }

    nodes = []
    for key in sorted(instance_result.keys()):
        node = instance_result[key]
        color = _graph_node_color(node["category"], node["type"], node["subtype"])
        nodes.append(
            {
                "data": {
                    "id": str(node["euid"]),
                    "euid": str(node["euid"]),
                    "name": node["name"] or str(node["euid"]),
                    "type": node["type"],
                    "obj_type": node["type"],
                    "category": node["category"],
                    "subtype": node["subtype"],
                    "version": node["version"],
                    "color": color,
                }
            }
        )

    edges = []
    for key in sorted(lineage_result.keys()):
        edge = lineage_result[key]
        edges.append(
            {
                "data": {
                    "id": str(edge["lineage_euid"]),
                    # Directionality in graph view: child -> parent
                    "source": str(edge["child_euid"]),
                    "target": str(edge["parent_euid"]),
                    "relationship_type": str(edge["relationship_type"]),
                }
            }
        )

    return nodes, edges


@router.get("/dagg", response_class=HTMLResponse)
async def dagg(request: Request, _auth=Depends(require_auth)):
    content = templates.get_template("legacy/dag.html").render()
    return HTMLResponse(content=content)


@router.get("/dindex2", response_class=HTMLResponse)
async def dindex2(
    request: Request,
    globalFilterLevel: int = Query(default=6),
    globalZoom: float = Query(default=0),
    globalStartNodeEUID: str | None = Query(default=None),
    start_euid: str | None = Query(default=None),
    depth: int | None = Query(default=None, ge=1, le=10),
    auth=Depends(require_auth),
):
    resolved_start_euid, resolved_depth = _normalize_graph_request_params(
        start_euid=start_euid,
        depth=depth,
        legacy_start=globalStartNodeEUID,
        legacy_depth=globalFilterLevel,
    )
    user_data = auth if isinstance(auth, dict) else request.session.get("user_data", {})
    user_role = _resolve_auth_role(auth, request)

    template = templates.get_template("modern/dag_explorer.html")
    context = {
        "request": request,
        "globalFilterLevel": resolved_depth,
        "globalZoom": globalZoom,
        "globalStartNodeEUID": resolved_start_euid,
        "start_euid": resolved_start_euid,
        "depth": resolved_depth,
        "is_admin": user_role == "admin",
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
        legacy_start=None,
        legacy_depth=None,
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
    instance_cls = bobj.Base.classes.generic_instance

    try:
        obj = bobj.get_by_euid(euid)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Object not found: {euid}")

    object_kind = "instance"
    if isinstance(obj, bobj.Base.classes.generic_template):
        object_kind = "template"
    elif isinstance(obj, bobj.Base.classes.generic_instance_lineage):
        object_kind = "lineage"

    payload = {
        "uuid": str(obj.uuid),
        "euid": obj.euid,
        "name": obj.name,
        "type": object_kind,
        "obj_type": getattr(obj, "type", ""),
        "category": getattr(obj, "category", ""),
        "subtype": getattr(obj, "subtype", ""),
        "version": getattr(obj, "version", ""),
        "bstatus": getattr(obj, "bstatus", ""),
        "json_addl": getattr(obj, "json_addl", {}) or {},
        "created_dt": obj.created_dt.isoformat() if getattr(obj, "created_dt", None) else None,
        "modified_dt": obj.modified_dt.isoformat() if getattr(obj, "modified_dt", None) else None,
    }

    if object_kind == "lineage":
        parent_obj = (
            bobj.session.query(instance_cls)
            .filter(instance_cls.uuid == obj.parent_instance_uuid)
            .first()
        )
        child_obj = (
            bobj.session.query(instance_cls)
            .filter(instance_cls.uuid == obj.child_instance_uuid)
            .first()
        )
        payload["relationship_type"] = getattr(obj, "relationship_type", "generic") or "generic"
        payload["source"] = child_obj.euid if child_obj else None
        payload["target"] = parent_obj.euid if parent_obj else None

    return payload


@router.get("/get_dagv2")
async def get_dagv2(
    request: Request, _euid="AY1", _depth=6, _auth=Depends(require_auth)
):
    logging.warning("Deprecated endpoint /get_dagv2 used; prefer GET /api/graph/data")
    dag_fn = request.session.get("user_data", {}).get("dag_fnv2", "")
    dag_data = {"elements": {"nodes": [], "edges": []}}
    if dag_fn:
        dag_path = _resolve_dag_path(dag_fn)
        if dag_path.exists():
            request.session.setdefault("user_data", {})["dag_fnv2"] = str(dag_path)
            with dag_path.open("r", encoding="utf-8") as f:
                dag_data = json.load(f)
        elif os.path.exists(dag_fn):
            with open(dag_fn, "r") as f:
                dag_data = json.load(f)
    return dag_data


@router.post("/update_dag")
async def update_dag(request: Request, _auth=Depends(require_auth)):
    input_json = await request.json()

    DAG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"dag_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.json"
    dag_path = DAG_OUTPUT_DIR / filename
    with dag_path.open("w", encoding="utf-8") as f:
        json.dump(input_json, f)

    request.session.setdefault("user_data", {})["dag_fnv2"] = str(dag_path)

    deleted_dags = _cleanup_dag_files(DAG_OUTPUT_DIR)
    deleted_legacy = 0
    if LEGACY_DAG_OUTPUT_DIR != DAG_OUTPUT_DIR:
        deleted_legacy = _cleanup_dag_files(LEGACY_DAG_OUTPUT_DIR)

    return {
        "status": "success",
        "filename": filename,
        "path": str(dag_path),
        "deleted_dag_files": deleted_dags + deleted_legacy,
    }


@router.post("/add_new_edge")
async def add_new_edge(request: Request, _auth=Depends(require_auth)):
    logging.warning("Deprecated endpoint /add_new_edge used; prefer POST /api/lineage")
    input_data = await request.json()
    parent_euid = input_data["parent_uuid"]
    child_euid = input_data["child_uuid"]
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    new_edge = bobj.create_generic_instance_lineage_by_euids(parent_euid, child_euid)
    bobj.session.flush()
    bobj.session.commit()
    return {"euid": str(new_edge.euid), "deprecated": True}


@router.post("/delete_node")
async def delete_node(request: Request, _auth=Depends(require_auth)):
    logging.warning("Deprecated endpoint /delete_node used; prefer DELETE /api/object/{euid}")
    input_data = await request.json()
    node_euid = input_data["euid"]
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    bobj.delete(euid=node_euid)
    bobj.session.flush()
    bobj.session.commit()

    return {
        "status": "success",
        "message": "Node and associated lineage records deleted successfully.",
        "deprecated": True,
    }


@router.post("/delete_edge")
async def delete_edge(request: Request, _auth=Depends(require_auth)):
    logging.warning("Deprecated endpoint /delete_edge used; prefer DELETE /api/object/{euid}")
    input_data = await request.json()
    edge_euid = input_data["euid"]

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    try:
        edge = bobdb.get_by_euid(edge_euid)
        bobdb.delete(edge)
        bobdb.session.flush()
        bobdb.session.commit()
        return {
            "status": "success",
            "message": "Edge deleted successfully.",
            "deprecated": True,
        }
    except Exception as exc:
        try:
            bobdb_deleted = BloomObj(
                BLOOMdb3(app_username=request.session["user_data"]["email"]),
                is_deleted=True,
            )
            edge = bobdb_deleted.get_by_euid(edge_euid)
            if edge and edge.is_deleted:
                return {
                    "status": "success",
                    "message": f"Edge {edge_euid} was already soft-deleted",
                    "deprecated": True,
                }
        except Exception:
            pass
        logging.error("Error deleting edge %s: %s", edge_euid, exc)
        raise HTTPException(status_code=404, detail=f"Edge not found: {edge_euid}")


@router.get("/get_node_info")
async def get_node_info(request: Request, euid, _auth=Depends(require_auth)):
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    node_dat = bobj.get_by_euid(euid)

    if node_dat:
        return {
            "uuid": str(node_dat.uuid),
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
            lineage_cls.parent_instance_uuid == parent_obj.uuid,
            lineage_cls.child_instance_uuid == child_obj.uuid,
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
        return {"success": True, "euid": str(new_lineage.euid), "uuid": str(new_lineage.uuid)}
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
        bobj.delete(obj)
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
