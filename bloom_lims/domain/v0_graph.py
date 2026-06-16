"""Bloom helpers for the locked LSMC v0 graph contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

LSMC_V0_EDGE_TYPES = {
    "CONTAINS",
    "HOLDS_MATERIAL",
    "MATERIAL_FROM_SUBJECT",
    "SLOT_SATISFIED_BY",
    "RUN_CONSUMED",
    "RUN_PRODUCED",
    "DERIVED_FROM",
    "USES_EVIDENCE",
}


def _mark_json_addl_dirty(lineage: Any) -> None:
    try:
        flag_modified(lineage, "json_addl")
    except (AttributeError, TypeError, KeyError):
        # Unit tests and small fakes are not SQLAlchemy-mapped rows.
        return


def _normalize_evidence_refs(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not value:
        raise ValueError("v0 edge evidence_refs is required")
    refs: list[dict[str, Any]] = []
    for item in value:
        euid = str(item.get("euid") or "").strip()
        if not euid:
            raise ValueError("v0 edge evidence reference requires euid")
        cleaned = dict(item)
        cleaned["euid"] = euid
        refs.append(cleaned)
    return refs


def attach_bloom_v0_edge(
    lineage: Any,
    *,
    edge_type: str,
    source_euid: str,
    target_euid: str,
    evidence_refs: list[dict[str, Any]],
    correlation_id: str,
    causation_id: str,
    edge_state: str = "active",
    source_role: str = "source",
    target_role: str = "target",
    source_system: str = "bloom",
    target_system: str = "bloom",
) -> Any:
    canonical = str(edge_type or "").strip().upper()
    if canonical not in LSMC_V0_EDGE_TYPES:
        raise ValueError(f"Unsupported LSMC v0 edge type: {edge_type!r}")
    if not str(correlation_id or "").strip():
        raise ValueError("v0 edge correlation_id is required")
    if not str(causation_id or "").strip():
        raise ValueError("v0 edge causation_id is required")
    json_addl = lineage.json_addl if isinstance(lineage.json_addl, dict) else {}
    properties = json_addl.get("properties")
    if not isinstance(properties, dict):
        properties = {}
        json_addl["properties"] = properties
    asserted_at = datetime.now(UTC).isoformat()
    properties["v0_edge"] = {
        "contract": "LSMC_V0",
        "edge_type": canonical,
        "semantic_source": {
            "system": str(source_system or "bloom").strip(),
            "euid": str(source_euid).strip(),
            "role": str(source_role or "source").strip(),
        },
        "semantic_target": {
            "system": str(target_system or "bloom").strip(),
            "euid": str(target_euid).strip(),
            "role": str(target_role or "target").strip(),
        },
        "asserted_by_system": "bloom",
        "asserted_at": asserted_at,
        "evidence_refs": _normalize_evidence_refs(evidence_refs),
        "correlation_id": str(correlation_id).strip(),
        "causation_id": str(causation_id).strip(),
        "validity": {"valid_from": asserted_at, "valid_to": None},
        "edge_state": str(edge_state or "active").strip(),
    }
    lineage.json_addl = json_addl
    _mark_json_addl_dirty(lineage)
    return lineage


def object_evidence(euid: str, *, role: str, system: str = "bloom") -> dict[str, Any]:
    return {"system": system, "euid": str(euid).strip(), "role": role}
