from __future__ import annotations

"""
Operational and miscellaneous GUI endpoints.
"""

import csv
import difflib
import json
import logging
import os
import random
import shutil
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import matplotlib.pyplot as plt
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from auth.cognito.client import CognitoConfigurationError
from bloom_lims.bobjs import BloomFile, BloomFileReference, BloomFileSet, BloomObj
from bloom_lims.bvars import BloomVars
from bloom_lims.db import BLOOMdb3
from bloom_lims.core.action_execution import (
    ActionExecutionError,
    execute_action_for_instance,
    normalize_action_execute_payload,
)
from bloom_lims.gui.actions import hydrate_dynamic_action_groups as _hydrate_dynamic_action_groups
from bloom_lims.gui.deps import (
    _get_request_cognito_auth,
    get_allowed_domains,
    get_user_preferences,
    normalize_display_timezone,
    persist_display_timezone,
    require_auth,
)
from bloom_lims.gui.errors import MissingCognitoEnvVarsException
from bloom_lims.gui.jinja import templates
from bloom_lims.graph_support import resolve_external_refs_for_object


router = APIRouter()

BVARS = BloomVars()
BASE_DIR = Path("./served_data").resolve()

class FormField(BaseModel):
    name: str
    type: str
    label: str
    required: bool = False
    multiple: bool = False
    options: List[str] = []


def _session_role(request: Request) -> str:
    user_data = request.session.get("user_data", {})
    return str(user_data.get("role", "user")).strip().lower()


def _is_admin_session(request: Request) -> bool:
    return _session_role(request) == "admin"


def _admin_forbidden_response(request: Request):
    accepts = request.headers.get("accept", "").lower()
    if "application/json" in accepts:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return RedirectResponse(url="/user_home?admin_required=1", status_code=303)


def _zebra_command_status() -> tuple[str, str]:
    """Return zebra service status and command output summary."""
    zday_path = shutil.which("zday")
    if not zday_path:
        return "unknown", "zday command not available"

    try:
        status_result = subprocess.run(
            [zday_path, "gui", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return "unknown", str(exc)

    combined = f"{status_result.stdout or ''}\n{status_result.stderr or ''}".strip()
    lower = combined.lower()
    if "not running" in lower:
        return "stopped", combined
    if "running" in lower:
        return "running", combined
    return "unknown", combined


def _try_start_zebra_background() -> tuple[str, str]:
    """Attempt to start zebra service in non-blocking mode."""
    zday_path = shutil.which("zday")
    if zday_path:
        start_result = subprocess.run(
            [zday_path, "gui", "start", "--background", "--port", "8118"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if start_result.returncode != 0:
            err = (start_result.stderr or start_result.stdout or "").strip()
            return "start_failed", err or "zday gui start returned non-zero exit code"

        for _ in range(5):
            status, details = _zebra_command_status()
            if status == "running":
                return "started", details
            time.sleep(0.4)
        return "launch_failed", "zebra service start command completed but running status was not observed"

    legacy_path = shutil.which("zday_start")
    if not legacy_path:
        return "command_not_found", "Neither zday nor zday_start command is available"

    try:
        subprocess.Popen(  # noqa: S603,S607
            [legacy_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return "started", "zday_start launched in background"
    except Exception as exc:  # pragma: no cover - defensive
        return "launch_failed", str(exc)


def get_well_color(quant_value):
    # Transition from purple to white
    if quant_value <= 0.5:
        r = int(128 + 127 * (quant_value / 0.5))  # From 128 to 255
        g = int(0 + 255 * (quant_value / 0.5))  # From 0 to 255
        b = int(128 + 127 * (quant_value / 0.5))  # From 128 to 255
    # Transition from white to green
    else:
        r = int(255 - 255 * ((quant_value - 0.5) / 0.5))  # From 255 to 0
        g = 255
        b = int(255 - 255 * ((quant_value - 0.5) / 0.5))  # From 255 to 0

    return f"rgb({r}, {g}, {b})"


def get_relationship_data(obj):
    """Get relationship data for an object (parent/child lineages, templates, etc.)."""
    relationship_data = {}
    for relationship in obj.__mapper__.relationships:
        if relationship.uselist:  # If it's a list of items
            relationship_data[relationship.key] = [
                {
                    "child_instance_euid": (
                        rel_obj.child_instance.euid
                        if hasattr(rel_obj, "child_instance")
                        else []
                    ),
                    "parent_instance_euid": (
                        rel_obj.parent_instance.euid
                        if hasattr(rel_obj, "parent_instance")
                        else []
                    ),
                    "euid": rel_obj.euid,
                    "polymorphic_discriminator": rel_obj.polymorphic_discriminator,
                    "category": rel_obj.category,
                    "type": rel_obj.type,
                    "subtype": rel_obj.subtype,
                    "version": rel_obj.version,
                }
                for rel_obj in getattr(obj, relationship.key)
            ]
        else:  # If it's a single item
            rel_obj = getattr(obj, relationship.key)
            relationship_data[relationship.key] = [
                (
                    {
                        "child_instance_euid": (
                            rel_obj.child_instance.euid
                            if hasattr(rel_obj, "child_instance")
                            else []
                        ),
                        "parent_instance_euid": (
                            rel_obj.parent_instance.euid
                            if hasattr(rel_obj, "parent_instance")
                            else []
                        ),
                        "euid": rel_obj.euid,
                        "polymorphic_discriminator": rel_obj.polymorphic_discriminator,
                        "category": rel_obj.category,
                        "type": rel_obj.type,
                        "subtype": rel_obj.subtype,
                        "version": rel_obj.version,
                    }
                    if rel_obj
                    else {}
                )
            ]
    return relationship_data


def highlight_json_changes(old_json_str, new_json_str):
    try:
        old_json = json.loads(old_json_str)
        new_json = json.loads(new_json_str)
    except json.JSONDecodeError:
        return old_json_str, new_json_str

    old_json_formatted = json.dumps(old_json, indent=2)
    new_json_formatted = json.dumps(new_json, indent=2)

    diff = difflib.ndiff(old_json_formatted.splitlines(), new_json_formatted.splitlines())

    old_json_highlighted = []
    new_json_highlighted = []

    for line in diff:
        if line.startswith("- "):
            old_json_highlighted.append(f'<span class="deleted">{line[2:]}</span>')
        elif line.startswith("+ "):
            new_json_highlighted.append(f'<span class="added">{line[2:]}</span>')
        elif line.startswith("  "):
            old_json_highlighted.append(line[2:])
            new_json_highlighted.append(line[2:])

    return "\n".join(old_json_highlighted), "\n".join(new_json_highlighted)


@router.get("/index2", response_class=HTMLResponse)
async def index2(request: Request, _=Depends(require_auth)):
    return RedirectResponse(url="/", status_code=303)


@router.get("/lims", response_class=HTMLResponse)
async def lims(request: Request, _=Depends(require_auth)):
    return RedirectResponse(url="/", status_code=303)


@router.get("/calculate_cogs_children")
async def Acalculate_cogs_children(euid, request: Request, _auth=Depends(require_auth)):
    try:
        bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        cogs_value = round(bobdb.get_cost_of_euid_children(euid), 2)
        return json.dumps({"success": True, "cogs_value": cogs_value})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)})


@router.get("/calculate_cogs_parents")
async def calculate_cogs_parents(euid, request: Request, _auth=Depends(require_auth)):
    try:
        bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        cogs_value = round(bobdb.get_cogs_to_produce_euid(euid), 2)
        return json.dumps({"success": True, "cogs_value": cogs_value})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)})


@router.get("/set_filter")
async def set_filter(request: Request, _auth=Depends(require_auth), curr_val="off"):
    if curr_val == "off":
        request.session["user_data"]["wf_filter"] = "on"
    else:
        request.session["user_data"]["wf_filter"] = "off"


@router.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, _auth=Depends(require_auth), dest="na"):
    if not _is_admin_session(request):
        return _admin_forbidden_response(request)

    dest_section = {"section": dest}

    user_data = request.session.get("user_data", {})

    bobdb = BloomObj(
        BLOOMdb3(app_username=request.session["user_data"]["email"]),
        cfg_printers=True,
        cfg_fedex=True,
    )

    if "print_lab" in user_data:
        bobdb.get_lab_printers(user_data["print_lab"])

    csss = ["/static/modern/css/bloom_modern.css"]

    printer_info = {
        "print_lab": bobdb.printer_labs,
        "printer_name": bobdb.site_printers,
        "label_zpl_style": bobdb.zpl_label_styles,
        "style_css": csss,
    }
    printer_info["style_css"] = csss

    from bloom_lims._version import get_version

    bloom_version = get_version()

    import importlib.metadata

    dependency_info = {}

    try:
        zebra_version = importlib.metadata.version("zebra_day")
        dependency_info["zebra_day"] = {
            "version": zebra_version,
            "admin_url": "https://localhost:8118/",
            "description": "Zebra printer fleet management and ZPL label printing",
            "status": "available",
        }
    except importlib.metadata.PackageNotFoundError:
        dependency_info["zebra_day"] = {
            "version": "Not installed",
            "admin_url": None,
            "description": "Zebra printer fleet management and ZPL label printing",
            "status": "missing",
        }

    try:
        carrier_version = importlib.metadata.version("daylily-carrier-tracking")
        dependency_info["carrier_tracking"] = {
            "version": carrier_version,
            "description": "FedEx and multi-carrier package tracking",
            "status": "available",
        }
    except importlib.metadata.PackageNotFoundError:
        dependency_info["carrier_tracking"] = {
            "version": "Not installed",
            "description": "FedEx and multi-carrier package tracking",
            "status": "missing",
        }

    try:
        tapdb_version = importlib.metadata.version("daylily-tapdb")
        dependency_info["tapdb"] = {
            "version": tapdb_version,
            "description": "Templated Abstract Polymorphic Database library",
            "status": "available",
        }
    except importlib.metadata.PackageNotFoundError:
        dependency_info["tapdb"] = {
            "version": "editable install",
            "description": "Templated Abstract Polymorphic Database library",
            "status": "available",
        }

    cognito_info = {}
    try:
        cognito = _get_request_cognito_auth(request)
        cognito_info = {
            "region": cognito.config.region,
            "user_pool_id": cognito.config.user_pool_id,
            "client_id": cognito.config.client_id[:8] + "...",
            "domain": cognito.config.domain,
            "status": "configured",
        }
    except Exception:
        cognito_info = {
            "status": "not_configured",
            "message": "Cognito auth not configured",
        }

    db_info = {
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": os.environ.get("POSTGRES_PORT", "5445"),
        "database": os.environ.get("POSTGRES_DB", "bloom_lims"),
        "user": os.environ.get("POSTGRES_USER", "bloom_user"),
    }
    atlas_webhook_secret = ""
    try:
        from bloom_lims.config import get_settings

        atlas_webhook_secret = str(get_settings().atlas.webhook_secret or "")
    except Exception:
        atlas_webhook_secret = ""

    from bloom_lims.tapdb_metrics import build_metrics_page_context

    tapdb_metrics_summary = build_metrics_page_context(
        os.environ.get("TAPDB_ENV", "dev"), limit=1000
    )

    template = templates.get_template("modern/admin.html")
    context = {
        "request": request,
        "udat": user_data,
        "user_data": user_data,
        "printer_info": printer_info,
        "dest_section": dest_section,
        "bloom_version": bloom_version,
        "dependency_info": dependency_info,
        "cognito_info": cognito_info,
        "db_info": db_info,
        "atlas_webhook_secret": atlas_webhook_secret,
        "atlas_webhook_secret_configured": bool(atlas_webhook_secret.strip()),
        "tapdb_metrics_summary": tapdb_metrics_summary,
        "saved": request.query_params.get("saved") == "1",
        "zebra_started": request.query_params.get("zebra_started") == "1",
        "zebra_running": request.query_params.get("zebra_running") == "1",
        "zebra_error": request.query_params.get("zebra_error", ""),
    }
    return HTMLResponse(content=template.render(context))


@router.get("/admin/metrics", response_class=HTMLResponse)
async def admin_metrics(request: Request, _auth=Depends(require_auth), limit: int = 5000):
    if not _is_admin_session(request):
        return _admin_forbidden_response(request)

    from bloom_lims.tapdb_metrics import build_metrics_page_context

    user_data = request.session.get("user_data", {})
    metrics_ctx = build_metrics_page_context(
        os.environ.get("TAPDB_ENV", "dev"), limit=limit
    )

    template = templates.get_template("modern/admin_metrics.html")
    context = {"request": request, "udat": user_data, "user_data": user_data, **metrics_ctx}
    return HTMLResponse(content=template.render(context))


@router.get("/admin/observability", response_class=HTMLResponse)
async def admin_observability(request: Request, _auth=Depends(require_auth), limit: int = 25):
    if not _is_admin_session(request):
        return _admin_forbidden_response(request)

    user_data = request.session.get("user_data", {})
    store = request.app.state.observability
    obs_projection, obs_snapshot = store.obs_services_snapshot()
    api_projection, api_families = store.api_health()
    endpoint_projection, endpoint_payload = store.endpoint_health(offset=0, limit=limit)
    db_projection, db_payload = store.db_health()
    auth_projection, auth_payload = store.auth_health()

    template = templates.get_template("modern/admin_observability.html")
    context = {
        "request": request,
        "udat": user_data,
        "user_data": user_data,
        "obs_projection": obs_projection.model_dump(),
        "obs_snapshot": obs_snapshot,
        "api_projection": api_projection.model_dump(),
        "api_families": api_families,
        "endpoint_projection": endpoint_projection.model_dump(),
        "endpoint_payload": endpoint_payload,
        "db_projection": db_projection.model_dump(),
        "db_payload": db_payload,
        "auth_projection": auth_projection.model_dump(),
        "auth_payload": auth_payload,
    }
    return HTMLResponse(content=template.render(context))


@router.post("/admin")
async def admin_update_preferences(request: Request, _auth=Depends(require_auth)):
    if not _is_admin_session(request):
        return _admin_forbidden_response(request)

    """Update admin preference form values and redirect back to admin page."""
    form = await request.form()
    editable_keys = ("print_lab", "printer_name", "label_zpl_style", "style_css")

    auth_email = ""
    if isinstance(_auth, dict):
        auth_email = _auth.get("email", "")
    if "user_data" not in request.session:
        request.session["user_data"] = get_user_preferences(auth_email)

    updated_keys = []
    for key in editable_keys:
        value = form.get(key)
        if value is not None and str(value).strip() != "":
            request.session["user_data"][key] = str(value)
            updated_keys.append(key)

    accepts = request.headers.get("accept", "").lower()
    if "application/json" in accepts:
        return {"status": "success", "updated_keys": updated_keys}

    return RedirectResponse(url="/admin?saved=1", status_code=303)


@router.post("/admin/zebra/start")
async def admin_start_zebra_service(request: Request, _auth=Depends(require_auth)):
    if not _is_admin_session(request):
        return _admin_forbidden_response(request)

    """Launch zebra_day service using non-blocking CLI commands."""
    accepts = request.headers.get("accept", "").lower()
    status_before, _ = _zebra_command_status()
    if status_before == "running":
        if "application/json" in accepts:
            return {
                "status": "success",
                "state": "already_running",
                "message": "zebra_day service is already running",
            }
        return RedirectResponse(url="/admin?zebra_running=1", status_code=303)

    start_state, details = _try_start_zebra_background()
    if start_state in {"command_not_found", "launch_failed", "start_failed"}:
        logging.error("Failed to start zebra_day service (%s): %s", start_state, details)
        if "application/json" in accepts:
            return JSONResponse(
                status_code=503 if start_state == "command_not_found" else 500,
                content={"status": "error", "detail": details, "error_code": start_state},
            )
        return RedirectResponse(url=f"/admin?zebra_error={start_state}", status_code=303)

    if "application/json" in accepts:
        return {
            "status": "success",
            "state": "started",
            "message": "zebra_day service start requested in background mode",
        }
    return RedirectResponse(url="/admin?zebra_started=1", status_code=303)


@router.post("/update_preference")
async def update_preference(request: Request, auth: dict = Depends(require_auth)):
    auth_email = ""
    if isinstance(auth, dict):
        auth_email = str(auth.get("email") or "")
    if not auth_email:
        auth_email = str(request.session.get("user_data", {}).get("email") or "")

    if not auth_email:
        return {"status": "error", "message": "Authentication failed or user data missing"}

    data = await request.json()
    key = data.get("key")
    value = data.get("value")

    if not key:
        return {"status": "error", "message": "Missing 'key' in request"}

    if "user_data" not in request.session:
        request.session["user_data"] = get_user_preferences(auth_email)

    if key == "display_timezone":
        normalized_tz = normalize_display_timezone(str(value or ""))
        persist_display_timezone(auth_email, normalized_tz)
        request.session["user_data"]["display_timezone"] = normalized_tz
    else:
        request.session["user_data"][key] = value
    return {"status": "success", "message": "User preference updated"}


@router.get("/queue_details", response_class=HTMLResponse)
async def queue_details(
    request: Request, queue_euid, page=1, _auth=Depends(require_auth)
):
    page = int(page)
    if page < 1:
        page = 1
    per_page = 500
    user_logged_in = True if "user_data" in request.session else False
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    queue = bobdb.get_by_euid(queue_euid)
    qm = []
    for i in queue.parent_of_lineages:
        if not i.is_deleted:
            qm.append(i.child_instance)
    queue_details = queue.sort_by_euid(qm)
    queue_details_list = queue_details[(page - 1) * per_page : page * per_page]
    pagination = {"next": page + 1, "prev": page - 1, "euid": queue_euid}
    user_data = request.session.get("user_data", {})

    queue.items = queue_details_list

    template = templates.get_template("modern/queue_details.html")
    context = {
        "request": request,
        "udat": user_data,
        "queue": queue,
        "pagination": pagination,
    }
    return HTMLResponse(content=template.render(context))


@router.post("/generic_templates")
async def generic_templates(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    the_templates = (
        bobdb.session.query(bobdb.Base.classes.generic_template)
        .filter_by(is_deleted=False)
        .all()
    )

    grouped_templates = {}
    for temp in the_templates:
        if temp.category not in grouped_templates:
            grouped_templates[temp.category] = []
        grouped_templates[temp.category].append(temp)
    return HTMLResponse(grouped_templates)


@router.post("/update_accordion_state")
async def update_accordion_state(request: Request, _auth=Depends(require_auth)):
    data = await request.json()
    step_euid = data.get("step_euid") or data.get("euid")
    state = data.get("state")
    if not step_euid:
        raise HTTPException(status_code=400, detail="Missing step_euid")
    request.session[step_euid] = state
    return {"status": "success"}


@router.post("/update_obj_json_addl_properties", response_class=HTMLResponse)
async def update_obj_json_addl_properties(
    request: Request,
    obj_euid: str = Form(None),
    _auth=Depends(require_auth),
):
    referer = request.headers.get("Referer", "/")
    form = await request.form()
    properties = {key: value for key, value in form.items() if key != "obj_euid"}

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get_by_euid(obj_euid) if obj_euid else None
    if obj is None:
        raise HTTPException(status_code=404, detail=f"Object not found: {obj_euid}")

    payload = obj.json_addl if isinstance(obj.json_addl, dict) else {}
    payload.setdefault("properties", {})
    for key, values in properties.items():
        target_key = key[:-2] if key.endswith("[]") else key
        if isinstance(payload["properties"].get(target_key), list):
            payload["properties"][target_key] = values if isinstance(values, list) else [values]
        else:
            payload["properties"][target_key] = values

    obj.json_addl = payload
    flag_modified(obj, "json_addl")
    bobdb.session.flush()
    bobdb.session.commit()
    bobdb.session.refresh(obj)
    return RedirectResponse(url=referer, status_code=303)


@router.post("/ui/actions/execute")
async def execute_ui_action(request: Request, _auth=Depends(require_auth)):
    payload = await request.json()
    user_data = request.session.get("user_data", {})
    actor_email = str(user_data.get("email") or "bloomui-user")
    actor_user_id = user_data.get("sub") or user_data.get("user_id")

    try:
        request_data = normalize_action_execute_payload(payload)
        result = execute_action_for_instance(
            request_data,
            app_username=actor_email,
            actor_email=actor_email,
            actor_user_id=actor_user_id,
            user_preferences=user_data,
        )
        return JSONResponse(content=result)
    except ActionExecutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc


@router.get("/workflows")
async def workflows_redirect():
    raise HTTPException(status_code=410, detail="Workflow pages are retired in queue-centric Bloom beta.")


@router.get("/equipment")
async def equipment_redirect():
    return RedirectResponse(url="/equipment_overview", status_code=307)


@router.get("/reagents")
async def reagents_redirect():
    return RedirectResponse(url="/reagent_overview", status_code=307)


@router.get("/controls")
async def controls_redirect():
    raise HTTPException(status_code=404, detail="Controls overview has been retired.")


@router.post("/query_by_euids", response_class=HTMLResponse)
async def query_by_euids(request: Request, file_euids: str = Form(...)):
    try:
        bfi = BloomFile(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        euid_list = [euid.strip() for euid in file_euids.split("\n") if euid.strip()]

        detailed_results = [bfi.get_by_euid(euid) for euid in euid_list if euid]

        columns = ["EUID", "Date Created", "Status"]
        if detailed_results and detailed_results[0].json_addl.get("properties"):
            columns += list(detailed_results[0].json_addl["properties"].keys())

        table_data = []
        for result in detailed_results:
            row = {
                "EUID": result.euid,
                "Date Created": result.created_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Status": result.bstatus,
            }
            for key in columns[3:]:
                row[key] = result.json_addl["properties"].get(key, "N/A")
            table_data.append(row)

        rows = []
        for row in table_data:
            cells = "".join(f"<td>{row.get(col, '')}</td>" for col in columns)
            rows.append(f"<tr>{cells}</tr>")
        header = "".join(f"<th>{col}</th>" for col in columns)
        content = (
            "<html><body><h2>Query Results</h2>"
            "<table border='1'><thead><tr>"
            f"{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"
        )
        return HTMLResponse(content=content, status_code=200)

    except Exception as e:
        logging.error(f"Error querying files: {e}", exc_info=True)
        return HTMLResponse(content=f"<html><body><h2>Error: {e}</h2></body></html>", status_code=500)


@router.get("/update_object_name", response_class=HTMLResponse)
async def update_object_name(request: Request, euid, name, _auth=Depends(require_auth)):
    referer = request.headers.get("Referer", "/")
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get_by_euid(euid)
    if obj:
        obj.name = name
        flag_modified(obj, "name")
        bobdb.session.commit()
    return RedirectResponse(url=referer, status_code=303)


@router.get("/equipment_overview", response_class=HTMLResponse)
async def equipment_overview(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    equipment_instances = (
        bobdb.session.query(bobdb.Base.classes.equipment_instance)
        .filter_by(is_deleted=False)
        .all()
    )
    equipment_templates = (
        bobdb.session.query(bobdb.Base.classes.equipment_template)
        .filter_by(is_deleted=False)
        .all()
    )
    user_data = request.session.get("user_data", {})

    template = templates.get_template("modern/equipment.html")
    context = {
        "request": request,
        "udat": user_data,
        "equipment": equipment_instances,
        "templates": equipment_templates,
    }
    return HTMLResponse(content=template.render(context))


@router.get("/reagent_overview", response_class=HTMLResponse)
async def reagent_overview(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    reagent_instances = (
        bobdb.session.query(bobdb.Base.classes.content_instance)
        .filter_by(is_deleted=False, type="reagent")
        .all()
    )
    reagent_templates = (
        bobdb.session.query(bobdb.Base.classes.content_template)
        .filter_by(is_deleted=False, type="reagent")
        .all()
    )
    user_data = request.session.get("user_data", {})

    template = templates.get_template("modern/reagents.html")
    context = {
        "request": request,
        "udat": user_data,
        "reagents": reagent_instances,
        "templates": reagent_templates,
    }
    return HTMLResponse(content=template.render(context))


@router.get("/control_overview", response_class=HTMLResponse)
async def control_overview(request: Request, _auth=Depends(require_auth)):
    raise HTTPException(status_code=404, detail="Control overview has been retired.")


@router.get("/create_from_template", response_class=HTMLResponse)
async def create_from_template_get(
    request: Request, euid: str = None, _auth=Depends(require_auth)
):
    return await _create_from_template(request, euid)


@router.post("/create_from_template", response_class=HTMLResponse)
async def create_from_template_post(
    request: Request, euid: str = Form(None), _auth=Depends(require_auth)
):
    return await _create_from_template(request, euid)


async def _create_from_template(request: Request, euid: str):
    if euid is None:
        return HTMLResponse(
            content="<html><body><h2>Missing required 'euid' parameter for template creation</h2></body></html>",
            status_code=400,
        )

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    template = bobdb.create_instances(euid)

    if template:
        return RedirectResponse(url=f"/euid_details?euid={template[0][0].euid}", status_code=303)
    return RedirectResponse(url="/equipment_overview", status_code=303)
@router.get("/vertical_exp", response_class=HTMLResponse)
async def vertical_exp(request: Request, euid=None, _auth=Depends(require_auth)):
    raise HTTPException(status_code=404, detail="Vertical explorer has been retired.")


@router.get("/plate_carosel2", response_class=HTMLResponse)
async def plate_carosel(
    request: Request, plate_euid: str = Query(...), _auth=Depends(require_auth)
):
    raise HTTPException(status_code=404, detail="Plate carousel has been retired.")


@router.get("/get_related_plates", response_class=HTMLResponse)
async def get_related_plates(request: Request, main_plate, _auth=Depends(require_auth)):
    raise HTTPException(status_code=404, detail="Related plate expansion has been retired.")


@router.get("/plate_visualization", response_class=HTMLResponse)
async def plate_visualization(request: Request, plate_euid, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    plate = bobdb.get_by_euid(plate_euid)

    num_rows = 0
    num_cols = 0

    for i in plate.parent_of_lineages:
        if i.is_deleted:
            continue
        if i.parent_instance.euid == plate.euid and i.child_instance.type == "well":
            cd = i.child_instance.json_addl["cont_address"]
            if int(cd["row_idx"]) > num_rows:
                num_rows = int(cd["row_idx"])
            if int(cd["col_idx"]) > num_cols:
                num_cols = int(cd["col_idx"])
    plate.json_addl["properties"]["num_rows"] = num_rows + 1
    plate.json_addl["properties"]["num_cols"] = num_cols + 1
    flag_modified(plate, "json_addl")
    bobdb.session.commit()
    if not plate:
        return "Plate not found."
    user_data = request.session.get("user_data", {})

    template = templates.get_template("modern/plate_visualization.html")
    context = {
        "request": request,
        "udat": user_data,
        "plate": plate,
        "get_well_color": get_well_color,
    }
    return HTMLResponse(content=template.render(context))


@router.get("/database_statistics", response_class=HTMLResponse)
async def database_statistics(request: Request, _auth=Depends(require_auth)):
    user_data = request.session.get("user_data", {})
    if not user_data:
        return RedirectResponse(url="/login")

    bobdb = BloomObj(BLOOMdb3(app_username=user_data.get("email", "anonymous")))

    def get_stats(days):
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        return (
            bobdb.session.query(
                bobdb.Base.classes.generic_instance.subtype,
                func.count(bobdb.Base.classes.generic_instance.uid),
            )
            .filter(
                bobdb.Base.classes.generic_instance.created_dt >= cutoff_date,
                bobdb.Base.classes.generic_instance.is_deleted == False,
            )
            .group_by(bobdb.Base.classes.generic_instance.subtype)
            .all()
        )

    stats_1d = get_stats(1)
    stats_7d = get_stats(7)
    stats_30d = get_stats(30)

    template = templates.get_template("modern/database_statistics.html")
    context = {
        "request": request,
        "stats_1d": stats_1d,
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "udat": user_data,
    }
    return HTMLResponse(content=template.render(**context))


@router.post("/save_json_addl_key")
async def save_json_addl_key(request: Request, _auth=Depends(require_auth)):
    try:
        data = await request.json()
        euid = data.get("euid")
        json_addl_key = data.get("json_addl_key")
        json_data = data.get("json_data")

        if not euid or not json_addl_key or not json_data:
            logging.error("EUID, JSON key, or JSON data missing")
            raise HTTPException(status_code=400, detail="EUID, JSON key, or JSON data missing")

        bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        obj = bobdb.get_by_euid(euid)

        if not obj:
            raise HTTPException(status_code=404, detail="Object not found")

        obj.json_addl[json_addl_key] = json_data
        flag_modified(obj, "json_addl")
        bobdb.session.commit()

        return RedirectResponse(url=f"/euid_details?euid={euid}", status_code=303)

    except Exception as e:
        logging.error("Error saving JSON properties: %s", e)
        raise HTTPException(status_code=500, detail="An error occurred while saving JSON properties")


@router.get("/object_templates_summary", response_class=HTMLResponse)
async def object_templates_summary(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    generic_templates = (
        bobdb.session.query(bobdb.Base.classes.generic_template)
        .filter_by(is_deleted=False)
        .all()
    )

    unique_discriminators = sorted(set(t.polymorphic_discriminator for t in generic_templates))
    user_data = request.session.get("user_data", {})

    template = templates.get_template("modern/object_templates_summary.html")
    context = {
        "request": request,
        "generic_templates": generic_templates,
        "unique_discriminators": unique_discriminators,
        "udat": user_data,
        "user": user_data,
    }
    return HTMLResponse(content=template.render(context))


@router.get("/euid_details")
async def euid_details(
    request: Request,
    euid: str = Query(..., description="The EUID to fetch details for"),
    is_deleted: bool = Query(False, description="Flag to include deleted items"),
    _auth=Depends(require_auth),
):
    bobdb = BloomObj(
        BLOOMdb3(app_username=request.session["user_data"]["email"]),
        is_deleted=is_deleted,
    )

    try:
        obj = None
        try:
            obj = bobdb.get_by_euid(euid)
        except Exception:
            pass

        if not obj and not is_deleted:
            try:
                bobdb_deleted = BloomObj(
                    BLOOMdb3(app_username=request.session["user_data"]["email"]),
                    is_deleted=True,
                )
                obj = bobdb_deleted.get_by_euid(euid)
                if obj:
                    return RedirectResponse(url=f"/euid_details?euid={euid}&is_deleted=true", status_code=303)
            except Exception:
                pass

        relationship_data = get_relationship_data(obj) if obj else {}

        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {euid}")

        obj_dict = {
            column.key: getattr(obj, column.key)
            for column in obj.__table__.columns
            if hasattr(obj, column.key)
        }
        obj_dict["parent_template_euid"] = obj.parent_template.euid if hasattr(obj, "parent_template") else ""
        audit_logs = bobdb.query_audit_log_by_euid(euid)
        user_data = request.session.get("user_data", {})

        from bloom_lims.subjecting import list_subjects_for_object

        subjects_for_object = list_subjects_for_object(bobdb, euid)

        is_admin = user_data.get("role", "user") == "admin"
        action_groups = {}
        if isinstance(obj.json_addl, dict):
            action_groups = _hydrate_dynamic_action_groups(
                obj.json_addl.get("action_groups", {}),
                bobdb,
            )

        template = templates.get_template("modern/euid_details.html")
        context = {
            "request": request,
            "obj": obj,
            "obj_dict": obj_dict,
            "jaddl_prop": obj.json_addl.get("properties", {}),
            "jaddl_controlled_prop": obj.json_addl.get("controlled_properties", {}),
            "relationships": relationship_data,
            "audit_logs": audit_logs,
            "udat": user_data,
            "subjects_for_object": subjects_for_object,
            "is_admin": is_admin,
            "action_groups": action_groups,
            "external_refs": [
                ref.to_public_dict(ref_index=index)
                for index, ref in enumerate(resolve_external_refs_for_object(obj))
            ],
        }
        return HTMLResponse(content=template.render(context))

    except Exception as e:
        logging.error("Error in euid_details for %s: %s", euid, e, exc_info=True)
        raise e
@router.get("/bloom_schema_report", response_class=HTMLResponse)
async def bloom_schema_report(request: Request, _auth=Depends(require_auth)):
    return JSONResponse(
        status_code=410,
        content={
            "detail": "Legacy schema report page has been retired.",
        },
    )


@router.get("/delete_by_euid", response_class=HTMLResponse)
def delete_by_euid(request: Request, euid, _auth=Depends(require_auth)):
    referer = request.headers.get("Referer", "/")

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    bobdb.delete(bobdb.get_by_euid(euid))
    bobdb.session.flush()
    bobdb.session.commit()

    return RedirectResponse(url=referer, status_code=303)


@router.post("/delete_object")
async def delete_object(request: Request, _auth=Depends(require_auth)):
    logging.warning("Deprecated endpoint /delete_object used; prefer DELETE /api/object/{euid}")
    data = await request.json()
    euid = data.get("euid")
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    try:
        obj = bobdb.get_by_euid(euid)
        bobdb.delete_obj(obj)
        bobdb.session.flush()
        bobdb.session.commit()
        return {
            "status": "success",
            "message": f"Delete object performed for EUID {euid}",
            "deprecated": True,
        }
    except Exception as e:
        try:
            bobdb_deleted = BloomObj(
                BLOOMdb3(app_username=request.session["user_data"]["email"]),
                is_deleted=True,
            )
            obj = bobdb_deleted.get_by_euid(euid)
            if obj and obj.is_deleted:
                return {
                    "status": "success",
                    "message": f"Object {euid} was already soft-deleted",
                    "deprecated": True,
                }
        except Exception:
            pass
        logging.error("Error deleting object %s: %s", euid, e)
        raise HTTPException(status_code=404, detail=f"Object not found: {euid}")


@router.get("/user_audit_logs", response_class=HTMLResponse)
async def user_audit_logs(request: Request, username: str, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    results = bobdb.query_user_audit_logs(username)

    user_data = request.session.get("user_data", {})

    template = templates.get_template("modern/audit_log.html")
    context = {
        "request": request,
        "udat": user_data,
        "entries": results,
        "username": username,
        "page": 1,
        "total_pages": 1,
    }
    return HTMLResponse(content=template.render(context))


@router.get("/user_home", response_class=HTMLResponse)
async def user_home(request: Request):
    if os.environ.get("BLOOM_OAUTH", "yes") == "no":
        request.session["user_data"] = request.session.get("user_data") or {
            "email": "john@daylilyinformatics.bio",
            "dag_fnv2": "",
        }

    user_data = request.session.get("user_data", {})
    session_data = request.session.get("session_data", {})
    user_data["display_timezone"] = normalize_display_timezone(
        user_data.get("display_timezone"),
    )

    if not user_data:
        return RedirectResponse(url="/login")

    bobdb = BloomObj(
        BLOOMdb3(app_username=user_data.get("email", "anonymous")),
        cfg_printers=True,
        cfg_fedex=True,
    )

    skins_directory = Path("static/modern/css")
    if skins_directory.exists():
        css_files = [
            f"/static/modern/css/{css_file.name}"
            for css_file in sorted(skins_directory.glob("*.css"))
        ]
    else:
        css_files = []

    dest_section = request.query_params.get("dest_section", "")

    if "print_lab" in user_data:
        bobdb.get_lab_printers(user_data["print_lab"])

    printer_info = {
        "print_lab": bobdb.printer_labs,
        "printer_name": bobdb.site_printers,
        "label_zpl_style": bobdb.zpl_label_styles,
        "style_css": css_files,
    }

    from bloom_lims._version import get_version
    import importlib.metadata

    bloom_version = get_version()
    try:
        fedex_version = importlib.metadata.version("daylily-carrier-tracking")
    except importlib.metadata.PackageNotFoundError:
        fedex_version = "Not installed"
    try:
        zebra_printer_version = importlib.metadata.version("zebra_day")
    except importlib.metadata.PackageNotFoundError:
        zebra_printer_version = "Not installed"

    if os.environ.get("BLOOM_OAUTH", "yes") == "no":
        cognito_details = {
            "domain": "auth-disabled",
            "user_pool_id": "auth-disabled",
            "client_id": "auth-disabled",
        }
    else:
        try:
            cognito = _get_request_cognito_auth(request)
            cognito_details = {
                "domain": cognito.config.domain,
                "user_pool_id": cognito.config.user_pool_id,
                "client_id": cognito.config.client_id,
            }
        except CognitoConfigurationError as exc:
            raise MissingCognitoEnvVarsException(str(exc)) from exc

    template = templates.get_template("modern/user_home.html")
    timezone_options = [
        "UTC",
        "America/Los_Angeles",
        "America/Denver",
        "America/Chicago",
        "America/New_York",
        "Europe/London",
        "Europe/Berlin",
        "Asia/Tokyo",
        "Australia/Sydney",
    ]
    context = {
        "request": request,
        "user_data": user_data,
        "session_data": session_data,
        "css_files": css_files,
        "dest_section": dest_section,
        "whitelisted_domains": " , ".join(get_allowed_domains()) or "all",
        "s3_bucket_prefix": os.environ.get("BLOOM_DEWEY_S3_BUCKET_PREFIX", "NEEDS TO BE SET!") + "0",
        "cognito_details": cognito_details,
        "printer_info": printer_info,
        "bloom_version": bloom_version,
        "fedex_version": fedex_version,
        "zebra_printer_version": zebra_printer_version,
        "timezone_options": timezone_options,
        "udat": user_data,
    }
    return HTMLResponse(content=template.render(context))
