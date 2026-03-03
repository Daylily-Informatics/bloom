"""Service layer for BLOOM unified search v2."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from bloom_lims.db import BLOOMdb3
from bloom_lims.search.contracts import (
    ALL_RECORD_TYPES,
    SearchJSONFilter,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from bloom_lims.search.repository import SearchRepository


logger = logging.getLogger(__name__)


class SearchService:
    """High-level search orchestration with guardrails and pagination."""

    MAX_QUERY_LENGTH = 256

    def __init__(self, username: str = "search-user"):
        self.username = username or "search-user"

    def search(self, request: SearchRequest) -> SearchResponse:
        normalized = self._normalize_request(request)

        start_time = time.perf_counter()
        bdb = BLOOMdb3(app_username=self.username)
        try:
            repository = SearchRepository(bdb)
            items, facets, truncated = repository.search(normalized)
        finally:
            bdb.close()

        sorted_items = self._sort_items(items, normalized.sort_by, normalized.sort_order)
        total = len(sorted_items)
        offset = (normalized.page - 1) * normalized.page_size
        paged_items = sorted_items[offset : offset + normalized.page_size]

        total_pages = max(1, (total + normalized.page_size - 1) // normalized.page_size)
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info(
            "Unified search executed user=%s query=%r total=%s page=%s page_size=%s duration_ms=%s",
            self.username,
            normalized.query,
            total,
            normalized.page,
            normalized.page_size,
            duration_ms,
        )

        return SearchResponse(
            query=normalized.query,
            page=normalized.page,
            page_size=normalized.page_size,
            total=total,
            total_pages=total_pages,
            sort_by=normalized.sort_by,
            sort_order=normalized.sort_order,
            truncated=truncated,
            facets=facets,
            items=paged_items,
        )

    def build_dewey_request(self, form_data: Dict[str, Any], target: str) -> SearchRequest:
        """Convert Dewey metadata form payload into SearchRequest."""
        target_clean = (target or "file").strip().lower()
        type_name = "file_set" if target_clean == "file_set" else "file"
        greedy_value = str(form_data.get("is_greedy", "yes")).strip().lower()

        json_filters: List[SearchJSONFilter] = []
        text_query_parts: List[str] = []

        skip_keys = {
            "search_target",
            "is_greedy",
            "record_datetime_start",
            "record_datetime_end",
            "created_datetime_start",
            "created_datetime_end",
            "csrf_token",
        }

        for key, raw_value in form_data.items():
            if key in skip_keys:
                continue
            values = self._normalize_form_values(raw_value)
            if not values:
                continue

            if key == "euid":
                text_query_parts.extend(values)
                continue

            if len(values) == 1:
                json_filters.append(
                    SearchJSONFilter(path=f"properties.{key}", op="eq", value=values[0])
                )
            else:
                json_filters.append(
                    SearchJSONFilter(path=f"properties.{key}", op="in", values=values)
                )

        record_start = self._parse_date_or_datetime(form_data.get("record_datetime_start"))
        record_end = self._parse_date_or_datetime(form_data.get("record_datetime_end"))
        if record_start or record_end:
            json_filters.append(
                SearchJSONFilter(
                    path="properties.record_datetime",
                    op="between",
                    start=record_start,
                    end=record_end,
                )
            )

        created_start = self._parse_date_or_datetime(form_data.get("created_datetime_start"))
        created_end = self._parse_date_or_datetime(form_data.get("created_datetime_end"))

        return SearchRequest(
            query=" ".join(text_query_parts).strip(),
            record_types=["instance"],
            categories=["file"],
            type_names=[type_name],
            json_filters=json_filters,
            search_mode="any" if greedy_value == "yes" else "all",
            created_dt_start=created_start,
            created_dt_end=created_end,
            page=1,
            page_size=200,
            max_scan=10000,
        )

    def _normalize_request(self, request: SearchRequest) -> SearchRequest:
        payload = request.model_dump()

        query = (payload.get("query") or "").strip()
        if len(query) > self.MAX_QUERY_LENGTH:
            query = query[: self.MAX_QUERY_LENGTH]
        payload["query"] = query

        record_types = payload.get("record_types") or []
        if not record_types:
            payload["record_types"] = list(ALL_RECORD_TYPES)

        payload["categories"] = [value.lower() for value in payload.get("categories", [])]
        payload["type_names"] = [value.lower() for value in payload.get("type_names", [])]
        payload["subtype_names"] = [value.lower() for value in payload.get("subtype_names", [])]
        payload["statuses"] = [value.lower() for value in payload.get("statuses", [])]

        created_start = payload.get("created_dt_start")
        created_end = payload.get("created_dt_end")
        if created_start and created_end and created_start > created_end:
            payload["created_dt_start"] = created_end
            payload["created_dt_end"] = created_start

        return SearchRequest.model_validate(payload)

    def _sort_items(self, items: Iterable[SearchResultItem], sort_by: str, sort_order: str) -> List[SearchResultItem]:
        reverse = sort_order == "desc"

        if sort_by == "euid":
            key_fn = lambda item: (item.euid or "")
        elif sort_by == "name":
            key_fn = lambda item: (item.name or "")
        elif sort_by == "record_type":
            key_fn = lambda item: (item.record_type, item.timestamp or datetime.min)
        else:
            key_fn = lambda item: (item.timestamp or datetime.min, item.euid or "")

        return sorted(items, key=key_fn, reverse=reverse)

    def _normalize_form_values(self, raw_value: Any) -> List[str]:
        if raw_value is None:
            return []

        if isinstance(raw_value, (list, tuple, set)):
            values = [str(value).strip() for value in raw_value if str(value).strip()]
        else:
            value_str = str(raw_value).strip()
            if "\n" in value_str:
                values = [token.strip() for token in value_str.splitlines() if token.strip()]
            elif "," in value_str:
                values = [token.strip() for token in value_str.split(",") if token.strip()]
            else:
                values = [value_str] if value_str else []

        cleaned = [value for value in values if value and value not in {".na", "None"}]
        return cleaned

    def _parse_date_or_datetime(self, value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None

        text = str(value).strip()
        if not text:
            return None

        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
