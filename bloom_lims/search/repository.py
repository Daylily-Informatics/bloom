"""TapDB-backed repository for BLOOM unified search."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy import and_, cast, func, or_
from sqlalchemy.sql.sqltypes import String

from bloom_lims.db import BLOOMdb3
from bloom_lims.search.contracts import (
    SearchJSONFilter,
    SearchRequest,
    SearchResultItem,
)
from bloom_lims.template_identity import template_semantic_category

_KNOWN_LINEAGE_IDENTITIES = (
    "generic_instance_lineage",
    "workflow_instance_lineage",
    "workflow_step_instance_lineage",
    "container_instance_lineage",
    "content_instance_lineage",
    "equipment_instance_lineage",
    "data_instance_lineage",
    "test_requisition_instance_lineage",
    "actor_instance_lineage",
    "action_instance_lineage",
    "health_event_instance_lineage",
    "file_instance_lineage",
    "subject_instance_lineage",
)


class SearchRepository:
    """Repository that executes unified search queries using BLOOMdb3/TapDB models."""

    def __init__(self, bdb: BLOOMdb3):
        self._bdb = bdb
        self._session = bdb.session
        self._classes = bdb.Base.classes

    def search(
        self, request: SearchRequest
    ) -> Tuple[List[SearchResultItem], Dict[str, Dict[str, int]], bool]:
        """Run search for requested record types and return normalized items + facets."""
        handlers = {
            "instance": self._search_instances,
            "template": self._search_templates,
            "lineage": self._search_lineages,
            "audit": self._search_audit,
        }

        all_items: List[SearchResultItem] = []
        record_type_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = defaultdict(int)
        truncated = False

        for record_type in request.record_types:
            handler = handlers.get(record_type)
            if handler is None:
                continue
            items, total_count, is_truncated = handler(request)
            all_items.extend(items)
            record_type_counts[record_type] = total_count
            truncated = truncated or is_truncated
            for item in items:
                if item.category:
                    category_counts[item.category] += 1

        facets = {
            "record_type": record_type_counts,
            "category": dict(sorted(category_counts.items())),
        }
        return all_items, facets, truncated

    def _search_instances(
        self, request: SearchRequest
    ) -> Tuple[List[SearchResultItem], int, bool]:
        model = self._classes.generic_instance
        query = self._session.query(model)

        query = self._apply_common_filters(
            query, model, request, include_type_filters=True
        )
        query = self._apply_query_text_filter(
            query,
            request.query,
            [
                model.euid,
                model.name,
                model.category,
                model.type,
                model.subtype,
                cast(model.json_addl, String),
            ],
        )
        query = self._apply_json_filters(query, model.json_addl, request)
        query = self._apply_query_sort(
            query, model, request, timestamp_field="created_dt"
        )

        return self._materialize_items(
            query=query,
            record_type="instance",
            request=request,
            to_item=lambda row: SearchResultItem(
                record_type="instance",
                euid=str(getattr(row, "euid", "") or ""),
                name=str(getattr(row, "name", "") or ""),
                category=str(getattr(row, "category", "") or ""),
                type=str(getattr(row, "type", "") or ""),
                subtype=str(getattr(row, "subtype", "") or ""),
                status=str(getattr(row, "bstatus", "") or ""),
                created_dt=getattr(row, "created_dt", None),
                modified_dt=getattr(row, "modified_dt", None),
                timestamp=getattr(row, "created_dt", None)
                or getattr(row, "modified_dt", None),
                metadata={"json_addl": getattr(row, "json_addl", {}) or {}},
            ),
        )

    def _search_templates(
        self, request: SearchRequest
    ) -> Tuple[List[SearchResultItem], int, bool]:
        model = self._classes.generic_template
        query = self._session.query(model)

        query = self._apply_common_filters(
            query, model, request, include_type_filters=True
        )
        query = self._apply_query_text_filter(
            query,
            request.query,
            [
                model.euid,
                model.name,
                model.category,
                model.type,
                model.subtype,
                cast(model.json_addl, String),
            ],
        )
        query = self._apply_json_filters(query, model.json_addl, request)
        query = self._apply_query_sort(
            query, model, request, timestamp_field="created_dt"
        )

        return self._materialize_items(
            query=query,
            record_type="template",
            request=request,
            to_item=lambda row: SearchResultItem(
                record_type="template",
                euid=str(getattr(row, "euid", "") or ""),
                name=str(getattr(row, "name", "") or ""),
                category=template_semantic_category(row),
                type=str(getattr(row, "type", "") or ""),
                subtype=str(getattr(row, "subtype", "") or ""),
                status=str(getattr(row, "bstatus", "") or ""),
                created_dt=getattr(row, "created_dt", None),
                modified_dt=getattr(row, "modified_dt", None),
                timestamp=getattr(row, "created_dt", None)
                or getattr(row, "modified_dt", None),
                metadata={
                    "json_addl": getattr(row, "json_addl", {}) or {},
                    "json_addl_schema": getattr(row, "json_addl_schema", None),
                    "instance_prefix": getattr(row, "instance_prefix", ""),
                },
            ),
        )

    def _search_lineages(
        self, request: SearchRequest
    ) -> Tuple[List[SearchResultItem], int, bool]:
        model = self._classes.generic_instance_lineage
        query = self._session.query(model).filter(
            model.polymorphic_discriminator.in_(_KNOWN_LINEAGE_IDENTITIES)
        )

        query = self._apply_common_filters(
            query, model, request, include_type_filters=False
        )
        query = self._apply_query_text_filter(
            query,
            request.query,
            [
                model.euid,
                model.name,
                model.category,
                model.parent_type,
                model.child_type,
                model.relationship_type,
                cast(model.json_addl, String),
            ],
        )
        query = self._apply_json_filters(query, model.json_addl, request)
        query = self._apply_query_sort(
            query, model, request, timestamp_field="created_dt"
        )

        return self._materialize_items(
            query=query,
            record_type="lineage",
            request=request,
            to_item=lambda row: SearchResultItem(
                record_type="lineage",
                euid=str(getattr(row, "euid", "") or ""),
                name=str(getattr(row, "name", "") or ""),
                category=str(getattr(row, "category", "") or ""),
                type=str(getattr(row, "parent_type", "") or ""),
                subtype=str(getattr(row, "child_type", "") or ""),
                status=str(getattr(row, "relationship_type", "") or ""),
                created_dt=getattr(row, "created_dt", None),
                modified_dt=getattr(row, "modified_dt", None),
                timestamp=getattr(row, "created_dt", None)
                or getattr(row, "modified_dt", None),
                metadata={
                    "parent_instance_euid": getattr(
                        getattr(row, "parent_instance", None), "euid", None
                    ),
                    "child_instance_euid": getattr(
                        getattr(row, "child_instance", None), "euid", None
                    ),
                    "relationship_type": getattr(row, "relationship_type", ""),
                    "json_addl": getattr(row, "json_addl", {}) or {},
                },
            ),
        )

    def _search_audit(
        self, request: SearchRequest
    ) -> Tuple[List[SearchResultItem], int, bool]:
        model = self._classes.audit_log
        query = self._session.query(model)

        if not request.include_deleted and hasattr(model, "is_deleted"):
            query = query.filter(model.is_deleted.is_(False))

        if request.categories and hasattr(model, "category"):
            categories = [c.lower() for c in request.categories]
            semantic_category = func.lower(
                func.coalesce(
                    func.jsonb_extract_path_text(model.json_addl, "semantic_category"),
                    "",
                )
            )
            query = query.filter(
                or_(
                    func.lower(model.category).in_(categories),
                    semantic_category.in_(categories),
                )
            )

        if request.statuses:
            query = query.filter(
                func.lower(model.operation_type).in_(
                    [s.lower() for s in request.statuses]
                )
            )

        if request.type_names:
            query = query.filter(
                func.lower(model.rel_table_name).in_(
                    [t.lower() for t in request.type_names]
                )
            )

        if request.created_dt_start:
            query = query.filter(model.changed_at >= request.created_dt_start)
        if request.created_dt_end:
            query = query.filter(model.changed_at <= request.created_dt_end)

        query = self._apply_query_text_filter(
            query,
            request.query,
            [
                model.euid,
                model.rel_table_name,
                model.column_name,
                model.rel_table_euid_fk,
                model.changed_by,
                model.operation_type,
                model.old_value,
                model.new_value,
                cast(model.json_addl, String),
            ],
        )

        query = self._apply_json_filters(query, model.json_addl, request)
        query = self._apply_query_sort(
            query, model, request, timestamp_field="changed_at"
        )

        return self._materialize_items(
            query=query,
            record_type="audit",
            request=request,
            to_item=lambda row: SearchResultItem(
                record_type="audit",
                euid=str(getattr(row, "euid", "") or ""),
                name=str(getattr(row, "rel_table_name", "") or ""),
                category=str(getattr(row, "category", "") or ""),
                type=str(getattr(row, "rel_table_name", "") or ""),
                subtype=str(getattr(row, "column_name", "") or ""),
                status=str(getattr(row, "operation_type", "") or ""),
                created_dt=getattr(row, "changed_at", None),
                modified_dt=getattr(row, "changed_at", None),
                timestamp=getattr(row, "changed_at", None),
                metadata={
                    "rel_table_name": getattr(row, "rel_table_name", ""),
                    "column_name": getattr(row, "column_name", ""),
                    "rel_table_euid_fk": getattr(row, "rel_table_euid_fk", ""),
                    "changed_by": getattr(row, "changed_by", ""),
                    "old_value": getattr(row, "old_value", ""),
                    "new_value": getattr(row, "new_value", ""),
                    "json_addl": getattr(row, "json_addl", {}) or {},
                },
            ),
        )

    def _materialize_items(
        self, *, query, record_type: str, request: SearchRequest, to_item
    ):
        total_count = query.count()
        rows = query.limit(request.max_scan).all()
        truncated = total_count > len(rows)
        items = [to_item(row) for row in rows]
        return items, total_count, truncated

    def _apply_common_filters(
        self, query, model, request: SearchRequest, include_type_filters: bool
    ):
        if not request.include_deleted and hasattr(model, "is_deleted"):
            query = query.filter(model.is_deleted.is_(False))

        if request.categories and hasattr(model, "category"):
            query = query.filter(
                func.lower(model.category).in_([c.lower() for c in request.categories])
            )

        if include_type_filters and request.type_names and hasattr(model, "type"):
            query = query.filter(
                func.lower(model.type).in_([t.lower() for t in request.type_names])
            )

        if include_type_filters and request.subtype_names and hasattr(model, "subtype"):
            query = query.filter(
                func.lower(model.subtype).in_(
                    [s.lower() for s in request.subtype_names]
                )
            )

        if request.statuses and hasattr(model, "bstatus"):
            query = query.filter(
                func.lower(model.bstatus).in_([s.lower() for s in request.statuses])
            )

        if request.created_dt_start and hasattr(model, "created_dt"):
            query = query.filter(model.created_dt >= request.created_dt_start)
        if request.created_dt_end and hasattr(model, "created_dt"):
            query = query.filter(model.created_dt <= request.created_dt_end)

        return query

    def _apply_query_text_filter(self, query, search_text: str, columns: Iterable[Any]):
        if not search_text:
            return query

        pattern = f"%{search_text}%"
        conditions = [column.ilike(pattern) for column in columns if column is not None]
        if conditions:
            query = query.filter(or_(*conditions))
        return query

    def _apply_json_filters(self, query, json_column, request: SearchRequest):
        if not request.json_filters:
            return query

        conditions = []
        for json_filter in request.json_filters:
            condition = self._build_json_filter_condition(json_column, json_filter)
            if condition is not None:
                conditions.append(condition)

        if not conditions:
            return query

        if request.search_mode == "all":
            return query.filter(and_(*conditions))
        return query.filter(or_(*conditions))

    def _build_json_filter_condition(self, json_column, json_filter: SearchJSONFilter):
        path_parts = [part for part in json_filter.path.split(".") if part]
        extracted = func.jsonb_extract_path_text(json_column, *path_parts)

        if json_filter.op == "exists":
            return extracted.isnot(None)

        if json_filter.op == "between":
            start = json_filter.start
            end = json_filter.end
            if start is None and end is None:
                return None
            conditions = [extracted.isnot(None), extracted != ""]
            if start is not None:
                conditions.append(extracted >= start.strftime("%Y-%m-%d"))
            if end is not None:
                conditions.append(extracted <= end.strftime("%Y-%m-%d"))
            return and_(*conditions)

        if json_filter.op == "contains":
            if path_parts:
                payload = self._build_nested_payload(path_parts, json_filter.value)
            else:
                payload = json_filter.value
            return json_column.op("@>")(json.dumps(payload, default=str))

        if json_filter.op == "in":
            values = json_filter.values or (
                [] if json_filter.value is None else [json_filter.value]
            )
            if not values:
                return None
            return or_(*[extracted == str(value) for value in values])

        if json_filter.op == "ilike":
            if json_filter.value is None:
                return None
            return extracted.ilike(f"%{json_filter.value}%")

        if json_filter.value is None:
            return extracted.is_(None)
        return extracted == str(json_filter.value)

    def _build_nested_payload(
        self, path_parts: List[str], value: Any
    ) -> Dict[str, Any]:
        payload: Any = value
        for key in reversed(path_parts):
            payload = {key: payload}
        return payload

    def _apply_query_sort(
        self, query, model, request: SearchRequest, timestamp_field: str
    ):
        if request.sort_by == "euid" and hasattr(model, "euid"):
            order_column = model.euid
        elif request.sort_by == "name" and hasattr(model, "name"):
            order_column = model.name
        else:
            order_column = getattr(model, timestamp_field, None) or getattr(
                model, "created_dt", None
            )
            if order_column is None and hasattr(model, "euid"):
                order_column = model.euid

        if request.sort_order == "asc":
            return query.order_by(order_column.asc())
        return query.order_by(order_column.desc())
