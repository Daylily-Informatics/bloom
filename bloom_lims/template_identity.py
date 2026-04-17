"""Helpers for Bloom template identity under TapDB 6.0.3."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, or_

SEMANTIC_CATEGORY_KEY = "semantic_category"


def template_payload(template_row: Any) -> dict[str, Any]:
    """Return a template payload as a dictionary."""
    payload = getattr(template_row, "json_addl", None)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


def instance_payload(instance_row: Any) -> dict[str, Any]:
    """Return an instance payload as a dictionary."""
    payload = getattr(instance_row, "json_addl", None)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


def template_semantic_category(template_row: Any) -> str:
    """Return the semantic category stored with a seeded template."""
    payload = template_payload(template_row)
    semantic_category = str(payload.get(SEMANTIC_CATEGORY_KEY) or "").strip()
    if semantic_category:
        return semantic_category
    return str(getattr(template_row, "category", "") or "").strip()


def instance_semantic_category(instance_row: Any) -> str:
    """Return the semantic category stored with a runtime instance."""
    payload = instance_payload(instance_row)
    semantic_category = str(payload.get(SEMANTIC_CATEGORY_KEY) or "").strip()
    if semantic_category:
        return semantic_category
    template_row = getattr(instance_row, "parent_template", None)
    if template_row is not None:
        template_semantic = template_semantic_category(template_row)
        if template_semantic:
            return template_semantic
    return str(getattr(instance_row, "category", "") or "").strip()


def template_category_filter(model: Any, category: str | None):
    """Build a category filter that matches either prefix or semantic category."""
    normalized = str(category or "").strip().lower()
    if not normalized:
        return None

    if not hasattr(model, "json_addl"):
        return func.lower(model.category) == normalized

    semantic_category = func.lower(
        func.coalesce(
            func.jsonb_extract_path_text(model.json_addl, SEMANTIC_CATEGORY_KEY),
            "",
        )
    )
    return or_(
        func.lower(model.category) == normalized, semantic_category == normalized
    )


def instance_category_filter(model: Any, category: str | None):
    """Build a category filter for generic instances across prefix and semantic forms."""
    normalized = str(category or "").strip().lower()
    if not normalized:
        return None

    if not hasattr(model, "json_addl"):
        return func.lower(model.category) == normalized

    semantic_category = func.lower(
        func.coalesce(
            func.jsonb_extract_path_text(model.json_addl, SEMANTIC_CATEGORY_KEY),
            "",
        )
    )
    return or_(
        func.lower(model.category) == normalized, semantic_category == normalized
    )
