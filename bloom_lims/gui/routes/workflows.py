from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.bobjs import BloomObj, BloomWorkflow
from bloom_lims.core.action_execution import (
    ActionExecutionError,
    execute_action_for_instance,
    normalize_action_execute_payload,
)
from bloom_lims.db import BLOOMdb3
from bloom_lims.gui.actions import hydrate_dynamic_action_groups
from bloom_lims.gui.deps import require_auth
from bloom_lims.gui.jinja import templates


router = APIRouter()


@router.get("/workflow_summary", response_class=HTMLResponse)
async def workflow_summary(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    workflows = (
        bobdb.session.query(bobdb.Base.classes.workflow_instance)
        .filter_by(is_deleted=False)
        .all()
    )

    workflow_statistics = defaultdict(
        lambda: {
            "status_counts": defaultdict(int),
            "oldest": datetime.max.date(),
            "newest": datetime.min.date(),
        }
    )

    for wf in workflows:
        wf_type = wf.type or "unknown"
        wf_status = wf.bstatus or "queued"
        if isinstance(wf.json_addl, dict):
            wf_status = wf.json_addl.get("status", wf_status) or wf_status
        wf_created_dt = wf.created_dt.date() if wf.created_dt else datetime.utcnow().date()

        stats = workflow_statistics[wf_type]
        stats["status_counts"][wf_status] += 1
        stats["oldest"] = min(stats["oldest"], wf_created_dt)
        stats["newest"] = max(stats["newest"], wf_created_dt)

    workflow_statistics = {k: dict(v) for k, v in workflow_statistics.items()}
    unique_workflow_types = list(workflow_statistics.keys())
    workflow_status_totals = defaultdict(int)
    for wf_stats in workflow_statistics.values():
        for status_name, count in wf_stats.get("status_counts", {}).items():
            workflow_status_totals[status_name] += count

    user_data = request.session.get("user_data", {})

    template = templates.get_template("modern/workflows.html")
    context = {
        "request": request,
        "udat": user_data,
        "workflows": workflows,
        "workflow_statistics": workflow_statistics,
        "unique_workflow_types": unique_workflow_types,
        "workflow_status_totals": dict(workflow_status_totals),
    }
    return HTMLResponse(content=template.render(context))


@router.get("/workflow_details", response_class=HTMLResponse)
async def workflow_details(request: Request, workflow_euid, _auth=Depends(require_auth)):
    bwfdb = BloomWorkflow(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    workflow = bwfdb.get_sorted_euid(workflow_euid)
    accordion_states = dict(request.session)
    user_data = request.session.get("user_data", {})
    max_recursive_depth = 12

    def _iter_active_children(parent_obj):
        for lineage in getattr(parent_obj, "parent_of_lineages", []) or []:
            if getattr(lineage, "is_deleted", False):
                continue
            child = getattr(lineage, "child_instance", None)
            if child is None or getattr(child, "is_deleted", False):
                continue
            yield child

    def _collect_workflow_steps(root_workflow):
        workflow_steps = {}
        stack = list(getattr(root_workflow, "workflow_steps_sorted", []) or [])
        while stack:
            step_obj = stack.pop()
            step_euid = getattr(step_obj, "euid", None)
            if not step_euid or step_euid in workflow_steps:
                continue

            workflow_steps[step_euid] = step_obj
            for child in _iter_active_children(step_obj):
                if getattr(child, "category", None) == "workflow_step":
                    stack.append(child)

        return workflow_steps

    def _descendant_summary(root_obj, depth_limit):
        counts_by_category = {}
        counts_by_type = {}
        visited = set()
        stack = [(root_obj, 0)]

        while stack:
            current, depth = stack.pop()
            if depth >= depth_limit:
                continue

            for child in _iter_active_children(current):
                child_key = (
                    getattr(child, "euid", None)
                    or id(child)
                )
                if child_key in visited:
                    continue

                visited.add(child_key)
                child_category = getattr(child, "category", None) or "other"
                child_type = getattr(child, "type", None) or child_category or "other"
                counts_by_category[child_category] = counts_by_category.get(child_category, 0) + 1
                counts_by_type[child_type] = counts_by_type.get(child_type, 0) + 1
                stack.append((child, depth + 1))

        return {
            "total_descendants": sum(counts_by_category.values()),
            "counts_by_category": counts_by_category,
            "counts_by_type": counts_by_type,
        }

    workflow_steps = _collect_workflow_steps(workflow)
    step_descendant_summaries = {}
    for step_euid, step_obj in workflow_steps.items():
        step_descendant_summaries[step_euid] = _descendant_summary(step_obj, max_recursive_depth)

    action_groups_by_euid = {}

    def _hydrated_action_groups_for(obj):
        if not isinstance(getattr(obj, "json_addl", None), dict):
            return {}
        return hydrate_dynamic_action_groups(obj.json_addl.get("action_groups", {}), bwfdb)

    action_groups_by_euid[workflow.euid] = _hydrated_action_groups_for(workflow)
    for step_obj in workflow_steps.values():
        action_groups_by_euid[step_obj.euid] = _hydrated_action_groups_for(step_obj)

    for lineage in getattr(workflow, "child_of_lineages", []) or []:
        parent = getattr(lineage, "parent_instance", None)
        if parent is None or getattr(parent, "is_deleted", False):
            continue
        if getattr(parent, "type", None) == "test_requisition":
            action_groups_by_euid[parent.euid] = _hydrated_action_groups_for(parent)

    template = templates.get_template("modern/workflow_details.html")
    context = {
        "request": request,
        "workflow": workflow,
        "accordion_states": accordion_states,
        "step_descendant_summaries": step_descendant_summaries,
        "action_groups_by_euid": action_groups_by_euid,
        "udat": user_data,
    }
    return HTMLResponse(content=template.render(**context))


@router.post("/update_accordion_state")
async def update_accordion_state(request: Request, _auth=Depends(require_auth)):
    data = await request.json()
    step_euid = data["step_euid"]
    state = data["state"]
    request.session[step_euid] = state
    return {"status": "success"}


@router.post("/update_obj_json_addl_properties", response_class=HTMLResponse)
async def update_obj_json_addl_properties(
    request: Request,
    obj_euid: str = Form(None),
    _auth=Depends(require_auth),
):
    referer = request.headers.get("Referer", "/default_page")

    form = await request.form()
    properties = {key: value for key, value in form.items() if key != "obj_euid"}

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    step = bobdb.get_by_euid(obj_euid)

    if step is None:
        return False

    try:
        for key, values in properties.items():
            if key in step.json_addl["properties"]:
                if isinstance(step.json_addl["properties"][key], list):
                    step.json_addl["properties"][key] = values if isinstance(values, list) else [values]
                else:
                    step.json_addl["properties"][key] = values
            if key.endswith("[]"):
                key = key[:-2]
                if key in step.json_addl["properties"]:
                    step.json_addl["properties"][key] = values if isinstance(values, list) else [values]
                else:
                    step.json_addl["properties"][key] = values

        flag_modified(step, "json_addl")
        bobdb.session.flush()
        bobdb.session.commit()
        bobdb.session.refresh(step)

    except Exception as exc:
        raise Exception("Error updating step properties:", exc)

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
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload())
