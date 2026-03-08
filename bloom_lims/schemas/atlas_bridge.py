"""Schemas for manual Atlas query/status bridge APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AtlasTestStatusEventRequest(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=200)
    status: Literal[
        "IN_PROGRESS",
        "COMPLETED",
        "FAILED",
        "ON_HOLD",
        "CANCELED",
        "REJECTED",
    ]
    occurred_at: datetime
    reason: str | None = None
    container_euid: str | None = None
    specimen_euid: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AtlasTestStatusEventResponse(BaseModel):
    applied: bool
    idempotent_replay: bool
    test_euid: str
    test_status: str
    trf_euid: str
    trf_status: str
    status_event_id: str | None = None
    trf_status_event_id: str | None = None
