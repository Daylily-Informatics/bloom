"""Search contracts for BLOOM unified search v2."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


RecordType = Literal["instance", "template", "lineage", "audit"]
SearchSortBy = Literal["timestamp", "euid", "name", "record_type"]
SearchSortOrder = Literal["asc", "desc"]
JSONFilterOp = Literal["eq", "in", "ilike", "between", "exists", "contains"]
SearchMode = Literal["any", "all"]


ALL_RECORD_TYPES: List[str] = ["instance", "template", "lineage", "audit"]
ALL_SEARCHABLE_CATEGORIES: List[str] = [
    "container",
    "content",
    "workflow",
    "equipment",
    "file",
    "file_set",
    "subject",
    "data",
]


class SearchJSONFilter(BaseModel):
    """Structured JSON-path filter for json_addl fields."""

    path: str = Field(..., description="Dot-delimited JSON path, e.g. properties.patient_id")
    op: JSONFilterOp = Field(default="eq")
    value: Optional[Any] = None
    values: List[Any] = Field(default_factory=list)
    start: Optional[datetime] = None
    end: Optional[datetime] = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        cleaned = value.strip().strip(".")
        if not cleaned:
            raise ValueError("JSON filter path cannot be empty")
        return cleaned


class SearchRequest(BaseModel):
    """Canonical query contract for unified search."""

    query: str = Field(default="")
    record_types: List[RecordType] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    type_names: List[str] = Field(default_factory=list)
    subtype_names: List[str] = Field(default_factory=list)
    statuses: List[str] = Field(default_factory=list)
    include_deleted: bool = Field(default=False)
    json_filters: List[SearchJSONFilter] = Field(default_factory=list)
    search_mode: SearchMode = Field(default="any")
    created_dt_start: Optional[datetime] = None
    created_dt_end: Optional[datetime] = None
    sort_by: SearchSortBy = Field(default="timestamp")
    sort_order: SearchSortOrder = Field(default="desc")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    max_scan: int = Field(default=5000, ge=100, le=20000)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("categories", "type_names", "subtype_names", "statuses", mode="before")
    @classmethod
    def normalize_list_values(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            values = [token.strip() for token in value.split(",") if token.strip()]
        else:
            values = [str(token).strip() for token in value if str(token).strip()]
        return sorted(set(values))

    @field_validator("record_types", mode="before")
    @classmethod
    def normalize_record_types(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [token.strip().lower() for token in value.split(",") if token.strip()]
        else:
            candidates = [str(token).strip().lower() for token in value if str(token).strip()]
        valid = [token for token in candidates if token in ALL_RECORD_TYPES]
        return sorted(set(valid))


class SearchResultItem(BaseModel):
    """Normalized result item across all searchable record types."""

    record_type: RecordType
    euid: str = ""
    name: str = ""
    category: str = ""
    type: str = ""
    subtype: str = ""
    status: str = ""
    created_dt: Optional[datetime] = None
    modified_dt: Optional[datetime] = None
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Paginated unified search response."""

    query: str
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: SearchSortBy
    sort_order: SearchSortOrder
    truncated: bool
    facets: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    items: List[SearchResultItem] = Field(default_factory=list)


class SearchExportRequest(BaseModel):
    """Export request for v2 endpoint."""

    search: SearchRequest
    format: Literal["json", "tsv"] = Field(default="json")
    include_metadata: bool = Field(default=True)
    max_export_rows: int = Field(default=10000, ge=100, le=50000)
