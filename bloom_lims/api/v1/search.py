"""BLOOM LIMS API v1 - legacy search endpoints (deprecated)."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from bloom_lims.search import SearchRequest, SearchService

from .dependencies import APIUser, require_api_auth


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


SEARCHABLE_TYPES = [
    "container",
    "content",
    "workflow",
    "equipment",
    "file",
    "file_set",
    "subject",
    "data",
]


def _set_deprecation_headers(response: Response) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Tue, 30 Jun 2026 00:00:00 GMT"
    response.headers["Link"] = '</api/v1/search/v2/query>; rel="successor-version"'


def _deprecation_headers_dict() -> Dict[str, str]:
    return {
        "Deprecation": "true",
        "Sunset": "Tue, 30 Jun 2026 00:00:00 GMT",
        "Link": '</api/v1/search/v2/query>; rel="successor-version"',
    }


def _legacy_item_from_v2(item: Dict, include_json_addl: bool) -> Dict:
    output = {
        "euid": item.get("euid", ""),
        "category": item.get("category", ""),
        "type": item.get("type", ""),
        "subtype": item.get("subtype", ""),
        "name": item.get("name", ""),
        "status": item.get("status", ""),
        "created_dt": item.get("created_dt") or item.get("timestamp"),
    }
    if include_json_addl:
        output["json_addl"] = (item.get("metadata") or {}).get("json_addl", {})
    return output


@router.get("/")
async def search_objects(
    response: Response,
    q: str = Query(..., min_length=1, description="Search query"),
    types: Optional[str] = Query(
        None, description="Comma-separated super types to search"
    ),
    format: str = Query("json", pattern="^(json|tsv)$", description="Response format"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: APIUser = Depends(require_api_auth),
):
    """Legacy search endpoint kept for compatibility; use /api/v1/search/v2/query."""
    _set_deprecation_headers(response)

    try:
        type_list = [t.strip().lower() for t in (types or "").split(",") if t.strip()]
        valid_types = [t for t in type_list if t in SEARCHABLE_TYPES]

        request = SearchRequest(
            query=q,
            record_types=["instance"],
            categories=valid_types,
            page=page,
            page_size=page_size,
            max_scan=10000,
        )
        service = SearchService(username=user.email)
        v2_result = service.search(request).model_dump(mode="json")

        legacy_items = [
            _legacy_item_from_v2(item, include_json_addl=(format == "json"))
            for item in v2_result["items"]
        ]

        if format == "tsv":
            return _generate_tsv_response(legacy_items, q)

        return {
            "query": q,
            "types_filter": types,
            "items": legacy_items,
            "total": v2_result["total"],
            "page": v2_result["page"],
            "page_size": v2_result["page_size"],
            "total_pages": v2_result["total_pages"],
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("Error searching objects: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _generate_tsv_response(results: List[Dict], query: str) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")

    headers = ["euid", "category", "type", "subtype", "name", "status", "created_dt"]
    writer.writerow(headers)

    for row in results:
        writer.writerow([row.get(h, "") for h in headers])

    output.seek(0)
    filename = f"bloom_search_{query[:20].replace(' ', '_')}.tsv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/tab-separated-values",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            **_deprecation_headers_dict(),
        },
    )


@router.get("/export")
async def export_search_results(
    response: Response,
    q: str = Query(..., min_length=1, description="Search query"),
    types: Optional[str] = Query(None, description="Comma-separated super types"),
    format: str = Query("json", pattern="^(json|tsv)$"),
    include_json_addl: bool = Query(True, description="Include full json_addl in export"),
    user: APIUser = Depends(require_api_auth),
):
    """Legacy export endpoint kept for compatibility; use /api/v1/search/v2/export."""
    _set_deprecation_headers(response)

    try:
        type_list = [t.strip().lower() for t in (types or "").split(",") if t.strip()]
        valid_types = [t for t in type_list if t in SEARCHABLE_TYPES]

        request = SearchRequest(
            query=q,
            record_types=["instance"],
            categories=valid_types,
            page=1,
            page_size=500,
            max_scan=10000,
        )
        service = SearchService(username=user.email)
        v2_result = service.search(request).model_dump(mode="json")

        legacy_items = [
            _legacy_item_from_v2(item, include_json_addl=include_json_addl)
            for item in v2_result["items"]
        ]

        if format == "tsv":
            return _generate_tsv_response(legacy_items, q)

        output = json.dumps({"query": q, "total": len(legacy_items), "items": legacy_items}, indent=2)
        filename = f"bloom_search_{q[:20].replace(' ', '_')}.json"
        return StreamingResponse(
            iter([output]),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                **_deprecation_headers_dict(),
            },
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("Error exporting search results: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
