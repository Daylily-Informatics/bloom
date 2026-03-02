"""Contracts for Atlas integration responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AtlasLookupResult:
    key: str
    payload: dict[str, Any]
    from_cache: bool
    stale: bool
    fetched_at: datetime

