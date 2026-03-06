from __future__ import annotations

"""
Legacy and miscellaneous GUI endpoints.

This module intentionally keeps the pre-existing handlers mostly unchanged while
`main.py` is refactored into a thin entrypoint.
"""

import csv
import difflib
import json
import logging
import os
import random
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

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
from bloom_lims.config import get_settings
from bloom_lims.db import BLOOMdb3
from bloom_lims.gui.actions import hydrate_dynamic_action_groups as _hydrate_dynamic_action_groups
from bloom_lims.gui.deps import (
    _get_request_cognito_auth,
    get_allowed_domains,
    get_user_preferences,
    require_auth,
)
from bloom_lims.gui.errors import MissingCognitoEnvVarsException
from bloom_lims.gui.jinja import templates
from bloom_lims.security.transport import is_https_url


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
                    "uuid": rel_obj.uuid,
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
                        "uuid": rel_obj.uuid,
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
    count = request.session.get("count", 0)
    count += 1
    request.session["count"] = count

    template = templates.get_template("legacy/index2.html")
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
    context = {"request": request, "style": style, "udat": user_data}

    return HTMLResponse(content=template.render(context), status_code=200)


@router.get("/lims", response_class=HTMLResponse)
async def lims(request: Request, _=Depends(require_auth)):
    count = request.session.get("count", 0)
    count += 1
    request.session["count"] = count

    template = templates.get_template("legacy/lims_main.html")
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
    context = {"request": request, "style": style, "udat": user_data}

    return HTMLResponse(content=template.render(context), status_code=200)


@router.get("/assays", response_class=HTMLResponse)
async def assays(request: Request, show_type: str = "all", _auth=Depends(require_auth)):
    if "user_data" not in request.session or "email" not in request.session["user_data"]:
        return RedirectResponse(url="/login")

    user_email = request.session["user_data"]["email"]
    user_data = request.session.get("user_data", {})

    bobdb = BloomObj(BLOOMdb3(app_username=user_email))
    ay_ds = {}
    for i in (
        bobdb.session.query(bobdb.Base.classes.workflow_instance)
        .filter_by(is_deleted=False, is_singleton=True)
        .all()
    ):
        if show_type == "all" or i.json_addl.get("assay_type", "all") == show_type:
            ay_ds[i.euid] = i

    assays = []
    ay_dss = {}
    atype = {}

    if show_type == "assay":
        atype["type"] = "Assays"
    else:
        atype["type"] = "All Assays, etc"

    for i in sorted(ay_ds.keys()):
        assays.append(ay_ds[i])
        ay_dss[i] = {
            "Instantaneous COGS": 0,
            "tot": 0,
            "tit_s": 0,
            "tot_fx": 0,
            "inprog": 0,
            "complete": 0,
            "exception": 0,
            "avail": 0,
        }

        for q in ay_ds[i].parent_of_lineages:
            if q.is_deleted:
                continue
            wset = ""
            child_json = q.child_instance.json_addl if isinstance(q.child_instance.json_addl, dict) else {}
            child_props = (
                child_json.get("properties", {})
                if isinstance(child_json.get("properties", {}), dict)
                else {}
            )
            n = str(child_props.get("name", ""))
            if n.startswith("In"):
                wset = "inprog"
            elif n.startswith("Comple"):
                wset = "complete"
            elif n.startswith("Exception"):
                wset = "exception"
            elif n.startswith("Ready"):
                wset = "avail"

            lins = [lin for lin in q.child_instance.parent_of_lineages.all() if not lin.is_deleted]
            if wset:
                ay_dss[i][wset] = len(lins)
            lctr = 0
            lctr_max = 150
            for llin in lins:
                if lctr > lctr_max:
                    break
                ay_dss[i]["Instantaneous COGS"] += round(
                    bobdb.get_cost_of_euid_children(llin.child_instance.euid), 2
                )
                ay_dss[i]["tot"] += 1
                lctr += 1

        try:
            ay_dss[i]["avg_d_fx"] = round(
                float(ay_dss[i]["tit_s"]) / 60.0 / 60.0 / 24.0 / float(ay_dss[i]["tot_fx"]),
                2,
            )
        except Exception:
            ay_dss[i]["avg_d_fx"] = "na"

        complete_n = int(ay_dss[i].get("complete", 0))
        exception_n = int(ay_dss[i].get("exception", 0))
        ay_dss[i]["conv"] = (
            round(float(complete_n) / float(complete_n + exception_n), 2)
            if (complete_n + exception_n) > 0
            else "na"
        )
        ay_dss[i]["wsetp"] = (
            round(float(ay_dss[i]["Instantaneous COGS"]) / float(ay_dss[i]["tot"]), 2)
            if ay_dss[i]["tot"] > 0
            else "na"
        )

    assay_types = list(set(a.json_addl.get("assay_type", "unknown") for a in assays))

    template = templates.get_template("modern/assays.html")
    context = {
        "request": request,
        "udat": user_data,
        "assays": assays,
        "assay_types": assay_types,
        "show_type": show_type,
        "ay_stats": ay_dss,
    }
    return HTMLResponse(content=template.render(context))


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
    dest_section = {"section": dest}

    user_data = request.session.get("user_data", {})
    settings = get_settings()
    configured_zebra_admin_url = (
        os.environ.get("BLOOM_ZEBRA_ADMIN_URL")
        or os.environ.get("BLOOM_UI__ZEBRA_ADMIN_URL")
        or str(getattr(settings.ui, "zebra_admin_url", "") or "")
    ).strip()
    zebra_admin_url = configured_zebra_admin_url if is_https_url(configured_zebra_admin_url) else None
    zebra_admin_url_warning = bool(configured_zebra_admin_url and not zebra_admin_url)

    bobdb = BloomObj(
        BLOOMdb3(app_username=request.session["user_data"]["email"]),
        cfg_printers=True,
        cfg_fedex=True,
    )

    if "print_lab" in user_data:
        bobdb.get_lab_printers(user_data["print_lab"])

    csss = []
    for css in sorted(os.popen("ls -1 static/legacy/skins/*css").readlines()):
        csss.append(css.rstrip())

    printer_info = {
        "print_lab": bobdb.printer_labs,
        "printer_name": bobdb.site_printers,
        "label_zpl_style": bobdb.zpl_label_styles,
        "style_css": csss,
    }
    csss = ["/static/legacy/skins/" + os.path.basename(css) for css in csss]
    printer_info["style_css"] = csss

    from bloom_lims._version import get_version

    bloom_version = get_version()

    import importlib.metadata

    dependency_info = {}

    try:
        zebra_version = importlib.metadata.version("zebra_day")
        dependency_info["zebra_day"] = {
            "version": zebra_version,
            "admin_url": zebra_admin_url,
            "admin_url_warning": zebra_admin_url_warning,
            "description": "Zebra printer fleet management and ZPL label printing",
            "status": "available",
        }
    except importlib.metadata.PackageNotFoundError:
        dependency_info["zebra_day"] = {
            "version": "Not installed",
            "admin_url": zebra_admin_url,
            "admin_url_warning": zebra_admin_url_warning,
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
        "tapdb_metrics_summary": tapdb_metrics_summary,
        "saved": request.query_params.get("saved") == "1",
        "zebra_started": request.query_params.get("zebra_started") == "1",
        "zebra_error": request.query_params.get("zebra_error", ""),
        "tool_api_default_token_days": settings.auth.tool_api_default_token_days,
        "tool_api_max_token_days": settings.auth.tool_api_max_token_days,
    }
    return HTMLResponse(content=template.render(context))


@router.get("/admin/metrics", response_class=HTMLResponse)
async def admin_metrics(request: Request, _auth=Depends(require_auth), limit: int = 5000):
    from bloom_lims.tapdb_metrics import build_metrics_page_context

    user_data = request.session.get("user_data", {})
    metrics_ctx = build_metrics_page_context(
        os.environ.get("TAPDB_ENV", "dev"), limit=limit
    )

    template = templates.get_template("modern/admin_metrics.html")
    context = {"request": request, "udat": user_data, "user_data": user_data, **metrics_ctx}
    return HTMLResponse(content=template.render(context))


@router.post("/admin")
async def admin_update_preferences(request: Request, _auth=Depends(require_auth)):
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
    """Launch zebra_day service using zday_start."""
    accepts = request.headers.get("accept", "").lower()

    if shutil.which("zday_start") is None:
        if "application/json" in accepts:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "detail": "zday_start command not found"},
            )
        return RedirectResponse(url="/admin?zebra_error=command_not_found", status_code=303)

    try:
        result = subprocess.run(
            ["zday_start"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except Exception as exc:
        logging.error("Failed to launch zday_start: %s", exc)
        if "application/json" in accepts:
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "detail": f"Failed to launch zday_start: {exc}",
                },
            )
        return RedirectResponse(url="/admin?zebra_error=launch_failed", status_code=303)

    if result.returncode != 0:
        stderr_trimmed = (result.stderr or "").strip()
        logging.error(
            "zday_start returned non-zero (%s): %s", result.returncode, stderr_trimmed
        )
        if "application/json" in accepts:
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "detail": "zday_start returned non-zero exit code",
                    "stderr": stderr_trimmed,
                },
            )
        return RedirectResponse(url="/admin?zebra_error=start_failed", status_code=303)

    if "application/json" in accepts:
        return {"status": "success", "message": "zday_start executed successfully"}

    return RedirectResponse(url="/admin?zebra_started=1", status_code=303)


@router.post("/update_preference")
async def update_preference(request: Request, auth: dict = Depends(require_auth)):
    if not auth or "email" not in auth:
        return {"status": "error", "message": "Authentication failed or user data missing"}

    data = await request.json()
    key = data.get("key")
    value = data.get("value")

    if not key:
        return {"status": "error", "message": "Missing 'key' in request"}

    if "user_data" not in request.session:
        request.session["user_data"] = get_user_preferences(auth.get("email", ""))

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


@router.get("/workflows")
async def workflows_redirect():
    return RedirectResponse(url="/workflow_summary", status_code=307)


@router.get("/equipment")
async def equipment_redirect():
    return RedirectResponse(url="/equipment_overview", status_code=307)


@router.get("/reagents")
async def reagents_redirect():
    return RedirectResponse(url="/reagent_overview", status_code=307)


@router.get("/controls")
async def controls_redirect():
    return RedirectResponse(url="/control_overview", status_code=307)


@router.get("/dag")
async def dag_redirect(request: Request):
    query_params = str(request.query_params)
    url = "/dindex2" + ("?" + query_params if query_params else "")
    return RedirectResponse(url=url, status_code=307)


@router.get("/dag_explorer")
async def dag_explorer_redirect(request: Request):
    query_params = str(request.query_params)
    url = "/dindex2" + ("?" + query_params if query_params else "")
    return RedirectResponse(url=url, status_code=307)


@router.get("/graph")
async def graph_redirect(request: Request):
    params = dict(request.query_params)

    if "start_euid" in params and "globalStartNodeEUID" not in params:
        params["globalStartNodeEUID"] = params["start_euid"]
    if "depth" in params and "globalFilterLevel" not in params:
        params["globalFilterLevel"] = params["depth"]

    url = "/dindex2"
    if params:
        url = f"{url}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=307)


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

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

        content = templates.get_template("legacy/search_results.html").render(
            request=request,
            columns=columns,
            table_data=table_data,
            style=style,
            udat=user_data,
        )
        return HTMLResponse(content=content)

    except Exception as e:
        logging.error(f"Error querying files: {e}", exc_info=True)
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
        content = templates.get_template("legacy/search_error.html").render(
            request=request,
            error=f"An error occurred: {e}",
            style=style,
            udat=user_data,
        )
        return HTMLResponse(content=content)


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
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    control_instances = (
        bobdb.session.query(bobdb.Base.classes.content_instance)
        .filter_by(is_deleted=False, type="control")
        .all()
    )
    control_templates = (
        bobdb.session.query(bobdb.Base.classes.content_template)
        .filter_by(is_deleted=False, type="control")
        .all()
    )
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

    content = templates.get_template("legacy/control_overview.html").render(
        style=style,
        instance_list=control_instances,
        template_list=control_templates,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


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
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
        content = templates.get_template("legacy/search_error.html").render(
            request=request,
            error="Missing required 'euid' parameter for template creation",
            style=style,
            udat=user_data,
        )
        return HTMLResponse(content=content)

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    template = bobdb.create_instances(euid)

    if template:
        return RedirectResponse(url=f"/euid_details?euid={template[0][0].euid}", status_code=303)
    return RedirectResponse(url="/equipment_overview", status_code=303)


@router.get("/uuid_details", response_class=HTMLResponse)
async def uuid_details(request: Request, uuid: str, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get(uuid)
    return RedirectResponse(url=f"/euid_details?euid={obj.euid}")


@router.get("/vertical_exp", response_class=HTMLResponse)
async def vertical_exp(request: Request, euid=None, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    instance = bobdb.get_by_euid(euid)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

    content = templates.get_template("legacy/vertical_exp.html").render(
        style=style, instance=instance, udat=request.session["user_data"]
    )
    return HTMLResponse(content=content)


@router.get("/plate_carosel2", response_class=HTMLResponse)
async def plate_carosel(
    request: Request, plate_euid: str = Query(...), _auth=Depends(require_auth)
):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    try:
        main_plate = bobdb.get_by_euid(plate_euid)
    except Exception:
        main_plate = None
    if not main_plate:
        return "Main plate not found."

    related_plates = await get_related_plates(main_plate)
    related_plates.append(main_plate)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

    content = templates.get_template("legacy/vertical_exp.html").render(
        style=style,
        main_plate=main_plate,
        related_plates=related_plates,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@router.get("/get_related_plates", response_class=HTMLResponse)
async def get_related_plates(request: Request, main_plate, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    related_plates = []

    for parent_lineage in main_plate.parent_of_lineages:
        if parent_lineage.is_deleted:
            continue
        if parent_lineage.child_instance.type == "plate":
            related_plates.append(parent_lineage.child_instance)

    for child_lineage in main_plate.child_of_lineages:
        if child_lineage.is_deleted:
            continue
        if child_lineage.parent_instance.type == "plate":
            related_plates.append(child_lineage.parent_instance)

    related_plates = list({plate.euid: plate for plate in related_plates}.values())

    for plate in related_plates:
        num_rows = 0
        num_cols = 0
        for lineage in plate.parent_of_lineages:
            if lineage.is_deleted:
                continue
            if (
                lineage.parent_instance.euid == plate.euid
                and lineage.child_instance.type == "well"
            ):
                cd = lineage.child_instance.json_addl.get("cont_address", {})
                num_rows = max(num_rows, int(cd.get("row_idx", 0)))
                num_cols = max(num_cols, int(cd.get("col_idx", 0)))
        plate.json_addl["properties"]["num_rows"] = num_rows + 1
        plate.json_addl["properties"]["num_cols"] = num_cols + 1
        flag_modified(plate, "json_addl")

    return related_plates


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
        cutoff_date = datetime.now() - timedelta(days=days)
        return (
            bobdb.session.query(
                bobdb.Base.classes.generic_instance.subtype,
                func.count(bobdb.Base.classes.generic_instance.uuid),
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
    _uuid: str = Query(None, description="Optional UUID parameter"),
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
        }
        return HTMLResponse(content=template.render(context))

    except Exception as e:
        logging.error("Error in euid_details for %s: %s", euid, e, exc_info=True)
        raise e


@router.get("/un_delete_by_uuid")
async def un_delete_by_uuid(
    request: Request,
    uuid: str = Query(..., description="The UUID to un-delete"),
    euid: str = Query(..., description="The EUID associated with the UUID"),
    _auth=Depends(require_auth),
    is_deleted: bool = True,
):
    try:
        bobdb = BloomObj(
            BLOOMdb3(app_username=request.session["user_data"]["email"]),
            is_deleted=is_deleted,
        )

        obj = bobdb.get(uuid)
        if not obj:
            raise HTTPException(status_code=404, detail="Object not found")

        obj.is_deleted = False
        bobdb.session.commit()

        logging.info("Successfully un-deleted object with UUID: %s and EUID: %s", uuid, euid)
        return RedirectResponse(url=f"/euid_details?euid={euid}", status_code=303)

    except Exception as e:
        logging.error(
            "Error un-deleting object with UUID: %s and EUID: %s - %s",
            uuid,
            euid,
            e,
            exc_info=True,
        )
        if is_deleted:
            try:
                logging.info("Retrying with is_deleted=True for UUID: %s and EUID: %s", uuid, euid)
                return await un_delete_by_uuid(request, uuid, euid, _auth, is_deleted=False)
            except Exception as inner_e:
                logging.error(
                    "Retry failed for UUID: %s and EUID: %s - %s",
                    uuid,
                    euid,
                    inner_e,
                    exc_info=True,
                )
                raise HTTPException(status_code=404, detail="Object not found after retry")
        raise HTTPException(status_code=404, detail="Object not found")


@router.get("/bloom_schema_report", response_class=HTMLResponse)
async def bloom_schema_report(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    a_stat = bobdb.query_generic_instance_and_lin_stats()
    b_stats = bobdb.query_generic_template_stats()
    reports = [[a_stat[0]], [a_stat[1]], b_stats]
    nrows = 0
    for i in b_stats:
        nrows += int(i["Total_Templates"])
    for ii in a_stat:
        nrows += int(ii["Total_Instances"])

    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

    content = templates.get_template("legacy/bloom_schema_report.html").render(
        request=request,
        reports=reports,
        nrows=nrows,
        style=style,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


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
        bobdb.delete(obj)
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
            "email": "john@daylilyinformatics.com",
            "dag_fnv2": "",
        }

    user_data = request.session.get("user_data", {})
    session_data = request.session.get("session_data", {})

    if not user_data:
        return RedirectResponse(url="/login")

    bobdb = BloomObj(
        BLOOMdb3(app_username=user_data.get("email", "anonymous")),
        cfg_printers=True,
        cfg_fedex=True,
    )

    skins_directory = Path("static/legacy/skins")
    if skins_directory.exists():
        css_files = [
            f"/static/legacy/skins/{css_file.name}"
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
        "udat": user_data,
    }
    return HTMLResponse(content=template.render(context))
