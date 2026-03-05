"""BLOOM external container helper endpoints for Atlas integrations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .containers import get_bdb
from .dependencies import APIUser, require_read


router = APIRouter(prefix="/external/containers", tags=["External Containers"])


class BulkContainerStatusRequest(BaseModel):
    container_euids: list[str] = Field(default_factory=list, min_length=1, max_length=5000)

    @field_validator("container_euids")
    @classmethod
    def _validate_container_euids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            euid = str(raw or "").strip()
            if not euid:
                continue
            if euid in seen:
                continue
            seen.add(euid)
            cleaned.append(euid)
        if not cleaned:
            raise ValueError("container_euids must contain at least one non-empty EUID")
        return cleaned


@router.post("/status/bulk")
async def bulk_container_status(
    request: BulkContainerStatusRequest,
    user: APIUser = Depends(require_read),
) -> dict[str, Any]:
    """Return deterministic tube/container statuses for Atlas reconciliation."""
    try:
        bdb = get_bdb(user.email)
        GI = bdb.Base.classes.generic_instance
        rows = (
            bdb.session.query(GI.euid, GI.bstatus)
            .filter(GI.category == "container")
            .filter(GI.is_deleted == False)  # noqa: E712
            .filter(GI.euid.in_(request.container_euids))
            .all()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    status_map = {row.euid: (row.bstatus or "unknown") for row in rows}
    items = []
    for euid in request.container_euids:
        status_value = status_map.get(euid, "unknown")
        items.append({"container_euid": euid, "euid": euid, "status": status_value})

    return {
        "statuses": {item["container_euid"]: item["status"] for item in items},
        "items": items,
        "requested_count": len(request.container_euids),
        "found_count": len(rows),
    }

