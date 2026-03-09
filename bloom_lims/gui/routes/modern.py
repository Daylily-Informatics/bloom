from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3
from bloom_lims.gui.deps import _is_tapdb_reachable, require_auth
from bloom_lims.gui.jinja import templates
from bloom_lims.search import SearchRequest, SearchService


router = APIRouter()


def _parse_csv_param(raw_value: str) -> List[str]:
    return [token.strip().lower() for token in (raw_value or "").split(",") if token.strip()]


def _render_search_page(
    *,
    request: Request,
    user_data: Dict,
    search_request: SearchRequest | None,
    query_value: str,
    categories_value: str,
    record_types_value: str,
) -> HTMLResponse:
    search_payload = {
        "query": query_value,
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
        "total_pages": 1,
        "sort_by": "timestamp",
        "sort_order": "desc",
        "truncated": False,
        "facets": {"record_type": {}, "category": {}},
    }

    if search_request is not None:
        service = SearchService(username=user_data.get("email", "anonymous"))
        search_payload = service.search(search_request).model_dump(mode="json")

    template = templates.get_template("modern/search_results.html")
    context = {
        "request": request,
        "udat": user_data,
        "query": query_value,
        "types": categories_value,
        "record_types": record_types_value,
        "results": search_payload.get("items", []),
        "search_response": search_payload,
        "selected_types": _parse_csv_param(categories_value),
        "selected_record_types": _parse_csv_param(record_types_value),
    }
    return HTMLResponse(content=template.render(context), status_code=200)


@router.get("/", response_class=HTMLResponse)
async def modern_dashboard(request: Request, _=Depends(require_auth)):
    user_data = request.session.get("user_data", {})
    stats = {
        "queue_runtime_total": 0,
        "objects_total": 0,
        "equipment_total": 0,
        "reagents_total": 0,
    }
    recent_queue_runtime = []
    recent_objects = []
    db_unavailable = not _is_tapdb_reachable()

    if not db_unavailable:
        try:
            bobdb = BloomObj(BLOOMdb3(app_username=user_data.get("email", "anonymous")))
            stats = {
                "queue_runtime_total": bobdb.session.query(bobdb.Base.classes.workflow_instance)
                .filter_by(is_deleted=False, is_singleton=True)
                .count(),
                "objects_total": bobdb.session.query(bobdb.Base.classes.generic_instance)
                .filter_by(is_deleted=False)
                .count(),
                "equipment_total": bobdb.session.query(bobdb.Base.classes.equipment_instance)
                .filter_by(is_deleted=False)
                .count(),
                "reagents_total": bobdb.session.query(bobdb.Base.classes.content_instance)
                .filter(
                    bobdb.Base.classes.content_instance.is_deleted == False,
                    bobdb.Base.classes.content_instance.subtype.like("%reagent%"),
                )
                .count(),
            }
            recent_queue_runtime = (
                bobdb.session.query(bobdb.Base.classes.workflow_instance)
                .filter_by(is_deleted=False, is_singleton=True)
                .order_by(bobdb.Base.classes.workflow_instance.created_dt.desc())
                .limit(5)
                .all()
            )
            recent_objects = (
                bobdb.session.query(bobdb.Base.classes.generic_instance)
                .filter_by(is_deleted=False)
                .order_by(bobdb.Base.classes.generic_instance.created_dt.desc())
                .limit(5)
                .all()
            )
        except Exception:
            db_unavailable = True

    template = templates.get_template("modern/dashboard.html")
    context = {
        "request": request,
        "udat": user_data,
        "stats": stats,
        "recent_queue_runtime": recent_queue_runtime,
        "recent_objects": recent_objects,
        "db_unavailable": db_unavailable,
    }

    return HTMLResponse(content=template.render(context), status_code=200)


@router.get("/create_object", response_class=HTMLResponse)
async def create_object_wizard(request: Request, _auth=Depends(require_auth)):
    user_data = request.session.get("user_data", {})
    template = templates.get_template("modern/create_object_wizard.html")
    context = {
        "request": request,
        "user_data": user_data,
        "user": user_data,
        "page_title": "Create Object",
    }
    return HTMLResponse(content=template.render(context), status_code=200)


@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    user_data = request.session.get("user_data", {})
    template = templates.get_template("modern/help.html")
    context = {
        "request": request,
        "udat": user_data,
        "user": user_data,
    }
    return HTMLResponse(content=template.render(context), status_code=200)


@router.get("/search", response_class=HTMLResponse)
async def modern_search(
    request: Request,
    q: str = Query("", description="Search query"),
    types: str = Query("", description="Comma-separated categories to search"),
    record_types: str = Query("", description="Comma-separated record types to search"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = Query("timestamp"),
    sort_order: str = Query("desc"),
    _=Depends(require_auth),
):
    user_data = request.session.get("user_data", {})
    categories = _parse_csv_param(types)
    selected_record_types = _parse_csv_param(record_types)

    has_filters = bool(q.strip() or categories or selected_record_types)
    search_request = None
    if has_filters:
        search_request = SearchRequest(
            query=q,
            categories=categories,
            record_types=selected_record_types,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            max_scan=10000,
        )

    return _render_search_page(
        request=request,
        user_data=user_data,
        search_request=search_request,
        query_value=q,
        categories_value=types,
        record_types_value=record_types,
    )


@router.post("/search", response_class=HTMLResponse)
async def modern_search_from_dewey(request: Request, _=Depends(require_auth)):
    user_data = request.session.get("user_data", {})
    form = await request.form()
    form_data = {}
    for key in form.keys():
        values = form.getlist(key)
        form_data[key] = values if len(values) > 1 else values[0]

    target = str(form_data.get("search_target", "file")).strip().lower()
    service = SearchService(username=user_data.get("email", "anonymous"))
    search_request = service.build_dewey_request(form_data, target=target)

    query_value = search_request.query
    categories_value = ",".join(search_request.categories)
    record_types_value = ",".join(search_request.record_types)
    return _render_search_page(
        request=request,
        user_data=user_data,
        search_request=search_request,
        query_value=query_value,
        categories_value=categories_value,
        record_types_value=record_types_value,
    )


@router.get("/bulk_create_containers", response_class=HTMLResponse)
async def modern_bulk_create_containers(request: Request, _=Depends(require_auth)):
    user_data = request.session.get("user_data", {})
    template = templates.get_template("modern/bulk_create_containers.html")
    context = {"request": request, "udat": user_data}
    return HTMLResponse(content=template.render(context), status_code=200)
