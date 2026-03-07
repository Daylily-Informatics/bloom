"""BLOOM LIMS API v1 - Search v2 endpoints."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from bloom_lims.search import SearchExportRequest, SearchRequest, SearchService

from .dependencies import APIUser, require_api_auth


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search/v2", tags=["Search"])


@router.post("/query")
async def search_v2_query(
    search: SearchRequest,
    user: APIUser = Depends(require_api_auth),
):
    """Execute unified search across instance/template/lineage/audit records."""
    try:
        service = SearchService(username=user.email)
        result = service.search(search)
        return result.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error running search v2 query: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/export")
async def search_v2_export(
    payload: SearchExportRequest,
    user: APIUser = Depends(require_api_auth),
):
    """Export unified search results in JSON or TSV."""
    try:
        service = SearchService(username=user.email)
        base_search = payload.search.model_copy(
            update={
                "page": 1,
                "page_size": 500,
                "max_scan": payload.max_export_rows,
            }
        )

        first_page = service.search(base_search)
        collected_items = list(first_page.items)
        max_pages = max(1, (payload.max_export_rows + base_search.page_size - 1) // base_search.page_size)
        last_page = min(first_page.total_pages, max_pages)

        for page in range(2, last_page + 1):
            if len(collected_items) >= payload.max_export_rows:
                break
            page_result = service.search(base_search.model_copy(update={"page": page}))
            if not page_result.items:
                break
            collected_items.extend(page_result.items)

        collected_items = collected_items[: payload.max_export_rows]
        items = [item.model_dump(mode="json") for item in collected_items]
        if not payload.include_metadata:
            for item in items:
                item.pop("metadata", None)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        query_part = (first_page.query or "search").strip().replace(" ", "_")[:40]
        if not query_part:
            query_part = "search"

        if payload.format == "tsv":
            output = io.StringIO()
            writer = csv.writer(output, delimiter="\t")
            headers = [
                "record_type",
                "euid",
                "name",
                "category",
                "type",
                "subtype",
                "status",
                "created_dt",
                "modified_dt",
                "timestamp",
                "metadata_json",
            ]
            writer.writerow(headers)
            for item in items:
                writer.writerow(
                    [
                        item.get("record_type", ""),
                        item.get("euid", ""),
                        item.get("name", ""),
                        item.get("category", ""),
                        item.get("type", ""),
                        item.get("subtype", ""),
                        item.get("status", ""),
                        item.get("created_dt", ""),
                        item.get("modified_dt", ""),
                        item.get("timestamp", ""),
                        json.dumps(item.get("metadata", {}), ensure_ascii=True),
                    ]
                )

            filename = f"bloom_search_v2_{query_part}_{timestamp}.tsv"
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/tab-separated-values",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        payload_json: Dict[str, object] = {
            "query": first_page.query,
            "total": first_page.total,
            "page": 1,
            "page_size": len(items),
            "total_pages": first_page.total_pages,
            "sort_by": first_page.sort_by,
            "sort_order": first_page.sort_order,
            "truncated": first_page.truncated or len(items) < first_page.total,
            "facets": first_page.facets,
            "items": items,
        }
        filename = f"bloom_search_v2_{query_part}_{timestamp}.json"
        return StreamingResponse(
            iter([json.dumps(payload_json, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error exporting search v2 results: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
