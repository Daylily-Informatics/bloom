"""Shared graph/detail helpers for Bloom GUI and API routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from bloom_lims.config import get_settings
from bloom_lims.db import get_parent_lineages


GRAPH_CATEGORY_COLORS = {
    "workflow": "#00FF7F",
    "workflow_step": "#ADFF2F",
    "container": "#8B00FF",
    "content": "#00BFFF",
    "equipment": "#FF4500",
    "data": "#FFD700",
    "actor": "#FF69B4",
    "action": "#FF8C00",
    "health_event": "#DC143C",
    "file": "#00FF00",
    "subject": "#9370DB",
    "object_set": "#FF6347",
    "generic": "#FF1493",
}

GRAPH_SUBTYPE_COLORS = {
    "well": "#70658C",
    "file_set": "#228080",
}

EXTERNAL_REFERENCE_RELATIONSHIP = "has_external_reference"
ATLAS_REFERENCE_FIELD_BY_TYPE = {
    "atlas_trf": "atlas_trf_euid",
    "atlas_patient": "atlas_patient_euid",
    "atlas_shipment": "atlas_shipment_euid",
    "atlas_testkit": "atlas_testkit_euid",
    "atlas_test": "atlas_test_euid",
    "atlas_test_process_item": "atlas_test_fulfillment_item_euid",
    "atlas_collection_event": "atlas_collection_event_euid",
    "atlas_organization_site": "atlas_organization_site_euid",
}


@dataclass(frozen=True)
class ExternalGraphRef:
    label: str
    system: str
    root_euid: str
    tenant_id: str | None
    href: str | None
    graph_expandable: bool
    reason: str | None

    def to_public_dict(self, *, ref_index: int) -> dict[str, Any]:
        payload = {
            "label": self.label,
            "system": self.system,
            "root_euid": self.root_euid,
            "tenant_id": self.tenant_id,
            "href": self.href,
            "graph_expandable": self.graph_expandable,
            "ref_index": ref_index,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def graph_node_color(category: str, obj_type: str, subtype: str) -> str:
    if obj_type in GRAPH_SUBTYPE_COLORS:
        return GRAPH_SUBTYPE_COLORS[obj_type]
    if subtype in GRAPH_SUBTYPE_COLORS:
        return GRAPH_SUBTYPE_COLORS[subtype]
    return GRAPH_CATEGORY_COLORS.get(category, "#888888")


def normalize_graph_request_params(
    start_euid: str | None,
    depth: int | None,
) -> tuple[str, int]:
    resolved_start = (start_euid or "AY1").strip() or "AY1"
    try:
        resolved_depth = int(depth if depth is not None else 4)
    except (TypeError, ValueError):
        resolved_depth = 4
    resolved_depth = max(1, min(resolved_depth, 10))
    return resolved_start, resolved_depth


def build_graph_elements_for_start(bobj: Any, start_euid: str, depth: int) -> tuple[list, list]:
    instance_result = {}
    lineage_result = {}

    for row in bobj.fetch_graph_data_by_node_depth(start_euid, depth):
        node_euid = row[0]
        if node_euid not in [None, "", "None"]:
            instance_result[node_euid] = {
                "euid": row[0],
                "name": row[2],
                "type": row[3],
                "category": row[4],
                "subtype": row[5],
                "version": row[6],
            }

        lineage_euid = row[8]
        if lineage_euid not in [None, "", "None"]:
            lineage_result[lineage_euid] = {
                "parent_euid": row[9],
                "child_euid": row[10],
                "lineage_euid": lineage_euid,
                "relationship_type": row[11] or "generic",
            }

    nodes = []
    for key in sorted(instance_result.keys()):
        node = instance_result[key]
        color = graph_node_color(node["category"], node["type"], node["subtype"])
        nodes.append(
            {
                "data": {
                    "id": str(node["euid"]),
                    "euid": str(node["euid"]),
                    "name": node["name"] or str(node["euid"]),
                    "type": node["type"],
                    "obj_type": node["type"],
                    "category": node["category"],
                    "subtype": node["subtype"],
                    "version": node["version"],
                    "color": color,
                }
            }
        )

    edges = []
    for key in sorted(lineage_result.keys()):
        edge = lineage_result[key]
        edges.append(
            {
                "data": {
                    "id": str(edge["lineage_euid"]),
                    "source": str(edge["child_euid"]),
                    "target": str(edge["parent_euid"]),
                    "relationship_type": str(edge["relationship_type"]),
                }
            }
        )

    return nodes, edges


def build_graph_object_payload(bobj: Any, euid: str) -> dict[str, Any]:
    obj = bobj.get_by_euid(euid)
    object_kind = "instance"
    if isinstance(obj, bobj.Base.classes.generic_template):
        object_kind = "template"
    elif isinstance(obj, bobj.Base.classes.generic_instance_lineage):
        object_kind = "lineage"

    payload = {
        "euid": obj.euid,
        "name": getattr(obj, "name", None),
        "type": object_kind,
        "obj_type": getattr(obj, "type", ""),
        "category": getattr(obj, "category", ""),
        "subtype": getattr(obj, "subtype", ""),
        "version": getattr(obj, "version", ""),
        "bstatus": getattr(obj, "bstatus", ""),
        "json_addl": getattr(obj, "json_addl", {}) or {},
        "created_dt": _iso(getattr(obj, "created_dt", None)),
        "modified_dt": _iso(getattr(obj, "modified_dt", None)),
        "external_refs": (
            [ref.to_public_dict(ref_index=index) for index, ref in enumerate(resolve_external_refs_for_object(obj))]
            if object_kind == "instance"
            else []
        ),
    }

    if object_kind == "lineage":
        instance_cls = bobj.Base.classes.generic_instance
        parent_instance_uid = getattr(obj, "parent_instance_uid", None)
        child_instance_uid = getattr(obj, "child_instance_uid", None)
        parent_obj = None
        child_obj = None
        if parent_instance_uid is not None:
            parent_obj = (
                bobj.session.query(instance_cls)
                .filter(instance_cls.uid == parent_instance_uid)
                .first()
            )
        if child_instance_uid is not None:
            child_obj = (
                bobj.session.query(instance_cls)
                .filter(instance_cls.uid == child_instance_uid)
                .first()
            )
        payload["relationship_type"] = getattr(obj, "relationship_type", "generic") or "generic"
        payload["source"] = getattr(child_obj, "euid", None)
        payload["target"] = getattr(parent_obj, "euid", None)

    return payload


def resolve_external_ref_by_index(obj: Any, ref_index: int) -> ExternalGraphRef:
    refs = resolve_external_refs_for_object(obj)
    if ref_index < 0 or ref_index >= len(refs):
        raise IndexError("External reference not found")
    return refs[ref_index]


def resolve_external_refs_for_object(obj: Any) -> list[ExternalGraphRef]:
    settings = get_settings()
    atlas_base_url = str(settings.atlas.base_url or "").strip().rstrip("/")
    atlas_token = str(settings.atlas.token or "").strip()
    refs: dict[tuple[str, str, str, str], ExternalGraphRef] = {}
    try:
        lineages = list(get_parent_lineages(obj))
    except Exception:
        lineages = []
    for lineage in lineages:
        if (
            getattr(lineage, "is_deleted", False)
            or getattr(lineage, "relationship_type", "") != EXTERNAL_REFERENCE_RELATIONSHIP
        ):
            continue
        external_ref = getattr(lineage, "child_instance", None)
        if external_ref is None or getattr(external_ref, "is_deleted", False):
            continue
        if (
            getattr(external_ref, "category", "") != "generic"
            or getattr(external_ref, "type", "") != "generic"
            or getattr(external_ref, "subtype", "") != "external_object_link"
        ):
            continue
        payload = _props(external_ref)
        if _clean(payload.get("provider")) != "atlas":
            continue
        ref_type = _clean(payload.get("reference_type"))
        root_euid = _atlas_root_euid(payload)
        tenant_id = _clean(payload.get("atlas_tenant_id")) or None
        href = None
        if atlas_base_url and root_euid:
            params = {"start_euid": root_euid, "depth": 4}
            if tenant_id:
                params["tenant_id"] = tenant_id
            href = f"{atlas_base_url}/graph?{urlencode(params)}"

        reason = None
        graph_expandable = True
        missing: list[str] = []
        if not root_euid:
            missing.append("root_euid")
        if not tenant_id:
            missing.append("atlas_tenant_id")
        if not atlas_base_url:
            missing.append("atlas.base_url")
        if not atlas_token:
            missing.append("atlas.token")
        if missing:
            graph_expandable = False
            reason = "Missing Atlas graph metadata: " + ", ".join(missing)

        label = _clean(payload.get("label")) or (
            f"atlas:{ref_type}:{root_euid or _clean(payload.get('reference_value')) or 'unknown'}"
        )
        ref = ExternalGraphRef(
            label=label,
            system="atlas",
            root_euid=root_euid,
            tenant_id=tenant_id,
            href=href,
            graph_expandable=graph_expandable,
            reason=reason,
        )
        refs[(ref.system, ref.label, ref.root_euid, ref.tenant_id or "")] = ref

    return [refs[key] for key in sorted(refs.keys())]


def namespace_external_graph(
    payload: dict[str, Any],
    *,
    ref: ExternalGraphRef,
    ref_index: int,
    source_euid: str,
) -> dict[str, Any]:
    elements = _as_dict(payload.get("elements"))
    nodes = _as_list(elements.get("nodes"))
    edges = _as_list(elements.get("edges"))
    namespace = f"ext::{ref.system}::{ref.tenant_id or 'global'}"

    def namespaced_id(raw_id: Any) -> str:
        return f"{namespace}::{_clean(raw_id)}"

    namespaced_nodes: list[dict[str, Any]] = []
    for node in nodes:
        data = _as_dict(_as_dict(node).get("data"))
        remote_euid = _clean(data.get("euid") or data.get("id"))
        if not remote_euid:
            continue
        node_data = dict(data)
        node_data["id"] = namespaced_id(remote_euid)
        node_data["remote_euid"] = remote_euid
        node_data["is_external"] = True
        node_data["external_system"] = ref.system
        node_data["external_tenant_id"] = ref.tenant_id
        node_data["source_ref_index"] = ref_index
        node_data["external_source_euid"] = source_euid
        namespaced_nodes.append({"data": node_data})

    namespaced_edges: list[dict[str, Any]] = []
    for edge in edges:
        data = _as_dict(_as_dict(edge).get("data"))
        remote_edge_id = _clean(data.get("id"))
        source_id = _clean(data.get("source"))
        target_id = _clean(data.get("target"))
        if not remote_edge_id or not source_id or not target_id:
            continue
        edge_data = dict(data)
        edge_data["id"] = namespaced_id(remote_edge_id)
        edge_data["source"] = namespaced_id(source_id)
        edge_data["target"] = namespaced_id(target_id)
        edge_data["remote_euid"] = remote_edge_id
        edge_data["is_external"] = True
        edge_data["external_system"] = ref.system
        edge_data["external_tenant_id"] = ref.tenant_id
        edge_data["source_ref_index"] = ref_index
        edge_data["external_source_euid"] = source_euid
        namespaced_edges.append({"data": edge_data})

    bridge_id = f"bridge::{source_euid}::{ref.system}::{ref.tenant_id or 'global'}::{ref.root_euid}"
    namespaced_edges.append(
        {
            "data": {
                "id": bridge_id,
                "source": source_euid,
                "target": namespaced_id(ref.root_euid),
                "relationship_type": "external_reference",
                "is_external_bridge": True,
                "external_system": ref.system,
                "external_tenant_id": ref.tenant_id,
                "source_ref_index": ref_index,
                "external_source_euid": source_euid,
            }
        }
    )

    return {
        "elements": {"nodes": namespaced_nodes, "edges": namespaced_edges},
        "meta": {
            "source_euid": source_euid,
            "root_euid": ref.root_euid,
            "system": ref.system,
            "tenant_id": ref.tenant_id,
            "ref_index": ref_index,
            "node_count": len(namespaced_nodes),
            "edge_count": len(namespaced_edges),
        },
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC).isoformat()
        return value.isoformat()
    return None


def _props(instance: Any) -> dict[str, Any]:
    payload = _as_dict(getattr(instance, "json_addl", None))
    return _as_dict(payload.get("properties"))


def _atlas_root_euid(payload: dict[str, Any]) -> str:
    ref_type = _clean(payload.get("reference_type"))
    field_name = ATLAS_REFERENCE_FIELD_BY_TYPE.get(ref_type, "")
    if field_name:
        direct = _clean(payload.get(field_name))
        if direct:
            return direct
    return _clean(payload.get("reference_value"))
