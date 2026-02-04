"""
BLOOM LIMS API v1 - Search Endpoints

Unified search across all BLOOM object types.
"""

import csv
import io
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3

    return BLOOMdb3(app_username=username)


# All searchable super types
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


@router.get("/")
async def search_objects(
    q: str = Query(..., min_length=1, description="Search query"),
    types: Optional[str] = Query(
        None, description="Comma-separated super types to search"
    ),
    format: str = Query("json", pattern="^(json|tsv)$", description="Response format"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: APIUser = Depends(require_api_auth),
):
    """
    Search across all BLOOM object types.

    - **q**: Search query (searches euid, name, type, subtype, json_addl)
    - **types**: Comma-separated list of categories to filter (e.g., "container,content")
    - **format**: Response format - "json" or "tsv"
    - **page**: Page number
    - **page_size**: Results per page
    """
    try:
        bdb = get_bdb(user.email)
        from sqlalchemy import or_
        from sqlalchemy.sql import cast
        from sqlalchemy.types import String

        gi = bdb.Base.classes.generic_instance
        query = bdb.session.query(gi)
        query = query.filter(gi.is_deleted == False)

        # Filter by categories if specified
        if types:
            type_list = [t.strip().lower() for t in types.split(",") if t.strip()]
            valid_types = [t for t in type_list if t in SEARCHABLE_TYPES]
            if valid_types:
                query = query.filter(gi.category.in_(valid_types))

        # Search across multiple fields
        search_pattern = f"%{q}%"
        query = query.filter(
            or_(
                gi.euid.ilike(search_pattern),
                gi.name.ilike(search_pattern),
                gi.type.ilike(search_pattern),
                gi.subtype.ilike(search_pattern),
                cast(gi.json_addl, String).ilike(search_pattern),
            )
        )

        # Order by created_dt descending
        query = query.order_by(gi.created_dt.desc())

        total = query.count()
        offset = (page - 1) * page_size
        items = query.limit(page_size).offset(offset).all()

        # Build results
        results = []
        for obj in items:
            result = {
                "euid": obj.euid,
                "uuid": str(obj.uuid),
                "category": obj.category,
                "type": obj.type,
                "subtype": obj.subtype,
                "name": obj.name,
                "status": obj.bstatus,
                "created_dt": obj.created_dt.isoformat() if obj.created_dt else None,
            }
            if format == "json":
                result["json_addl"] = obj.json_addl
            results.append(result)

        if format == "tsv":
            return _generate_tsv_response(results, q)

        return {
            "query": q,
            "types_filter": types,
            "items": results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    except Exception as e:
        logger.error(f"Error searching objects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _generate_tsv_response(results: List[Dict], query: str) -> StreamingResponse:
    """Generate TSV file response."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")

    # Header
    headers = ["euid", "category", "type", "subtype", "name", "status", "created_dt"]
    writer.writerow(headers)

    # Data rows
    for row in results:
        writer.writerow([row.get(h, "") for h in headers])

    output.seek(0)
    filename = f"bloom_search_{query[:20].replace(' ', '_')}.tsv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
async def export_search_results(
    q: str = Query(..., min_length=1, description="Search query"),
    types: Optional[str] = Query(None, description="Comma-separated super types"),
    format: str = Query("json", pattern="^(json|tsv)$"),
    include_json_addl: bool = Query(True, description="Include full json_addl in export"),
    user: APIUser = Depends(require_api_auth),
):
    """
    Export full search results as JSON or TSV file download.

    Returns all matching results (no pagination) for export.
    """
    try:
        bdb = get_bdb(user.email)
        from sqlalchemy import or_
        from sqlalchemy.sql import cast
        from sqlalchemy.types import String

        gi = bdb.Base.classes.generic_instance
        query = bdb.session.query(gi)
        query = query.filter(gi.is_deleted == False)

        if types:
            type_list = [t.strip().lower() for t in types.split(",") if t.strip()]
            valid_types = [t for t in type_list if t in SEARCHABLE_TYPES]
            if valid_types:
                query = query.filter(gi.category.in_(valid_types))

        search_pattern = f"%{q}%"
        query = query.filter(
            or_(
                gi.euid.ilike(search_pattern),
                gi.name.ilike(search_pattern),
                gi.type.ilike(search_pattern),
                gi.subtype.ilike(search_pattern),
                cast(gi.json_addl, String).ilike(search_pattern),
            )
        )

        query = query.order_by(gi.created_dt.desc()).limit(10000)
        items = query.all()

        results = []
        for obj in items:
            result = {
                "euid": obj.euid,
                "uuid": str(obj.uuid),
                "category": obj.category,
                "type": obj.type,
                "subtype": obj.subtype,
                "name": obj.name,
                "status": obj.bstatus,
                "created_dt": obj.created_dt.isoformat() if obj.created_dt else None,
            }
            if include_json_addl:
                result["json_addl"] = obj.json_addl
            results.append(result)

        if format == "tsv":
            return _generate_tsv_response(results, q)

        # JSON export
        output = json.dumps({"query": q, "total": len(results), "items": results}, indent=2)
        filename = f"bloom_search_{q[:20].replace(' ', '_')}.json"
        return StreamingResponse(
            iter([output]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as e:
        logger.error(f"Error exporting search results: {e}")
        raise HTTPException(status_code=500, detail=str(e))

