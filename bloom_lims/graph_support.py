"""Shared graph/detail helpers for Bloom GUI and API routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from daylily_tapdb.external_references import ExternalReferenceService
from sqlalchemy.orm import object_session

from bloom_lims.config import get_settings

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


@dataclass(frozen=True)
class ExternalGraphRef:
    label: str
    system: str
    root_euid: str
    tenant_id: str | None
    href: str | None
    graph_expandable: bool
    reason: str | None
    relationship_type: str | None = None

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
        if self.relationship_type:
            payload["relationship_type"] = self.relationship_type
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


def build_graph_elements_for_start(
    bobj: Any, start_euid: str, depth: int
) -> tuple[list, list]:
    instance_result = {}
    lineage_result = {}

    for row in bobj.fetch_graph_data_by_node_depth(start_euid, depth):
        extended_row = len(row) >= 15
        node_euid = row[0]
        if node_euid not in [None, "", "None"]:
            instance_result[node_euid] = {
                "euid": row[0],
                "name": row[2],
                "type": row[3],
                "category": row[4],
                "subtype": row[5],
                "version": row[6],
                "created_dt": row[7] if extended_row else None,
                "modified_dt": row[8] if extended_row else None,
                "json_addl": row[9] if extended_row else {},
            }

        lineage_euid = row[11] if extended_row else row[8]
        if lineage_euid not in [None, "", "None"]:
            lineage_result[lineage_euid] = {
                "parent_euid": row[12] if extended_row else row[9],
                "child_euid": row[13] if extended_row else row[10],
                "lineage_euid": lineage_euid,
                "relationship_type": (row[14] if extended_row else row[11])
                or "generic",
            }

    nodes = []
    for key in sorted(instance_result.keys()):
        node = instance_result[key]
        color = graph_node_color(node["category"], node["type"], node["subtype"])
        props = _props_from_json_addl(node.get("json_addl"))
        graph = _as_dict(props.get("graph"))
        instance = bobj.get_by_euid(node["euid"])
        external_refs = [
            ref.to_public_dict(ref_index=index)
            for index, ref in enumerate(resolve_external_refs_for_object(instance))
        ]
        node_data = {
            "id": str(node["euid"]),
            "euid": str(node["euid"]),
            "name": node["name"] or str(node["euid"]),
            "type": node["type"],
            "obj_type": node["type"],
            "category": node["category"],
            "subtype": node["subtype"],
            "version": node["version"],
            "created_dt": _iso(node.get("created_dt")),
            "modified_dt": _iso(node.get("modified_dt")),
            "color": color,
        }
        if graph:
            node_data["graph"] = graph
        if external_refs:
            node_data["external_refs"] = external_refs
        nodes.append({"data": node_data})

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


def build_graph_meta_for_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    expected_fanout: list[dict[str, Any]] = []
    for node in nodes:
        data = _as_dict(_as_dict(node).get("data"))
        euid = _clean(data.get("euid") or data.get("id"))
        graph = _as_dict(data.get("graph"))
        for entry in _as_list(graph.get("expected_fanout")):
            row = _as_dict(entry)
            if not euid or not row:
                continue
            expected_fanout.append({"euid": euid, "system": "bloom", **row})
    if not expected_fanout:
        return {}
    return {"expected_fanout": expected_fanout}


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
            [
                ref.to_public_dict(ref_index=index)
                for index, ref in enumerate(resolve_external_refs_for_object(obj))
            ]
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
        payload["relationship_type"] = (
            getattr(obj, "relationship_type", "generic") or "generic"
        )
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
    refs: dict[tuple[str, str, str, str, str], ExternalGraphRef] = {}
    session = object_session(obj)
    if session is None:
        raise RuntimeError(
            "native external references require an attached TapDB object"
        )
    page = ExternalReferenceService(session).list_for_source(obj, limit=100)
    if page["page"]["next_cursor"] is not None:
        raise RuntimeError("one Bloom object exceeds the reviewed 100-reference bound")
    for payload in page["items"]:
        target_type = _clean(payload.get("target_type"))
        if target_type == "tapdb_object":
            system = _clean(payload.get("target_service_id"))
            root_euid = _clean(payload.get("target_object_euid"))
            tenant_id = _clean(payload.get("target_tenant_id")) or None
            graph_expandable = system == "atlas"
            reason = None
        elif target_type == "opaque":
            system = _clean(payload.get("namespace"))
            root_euid = _clean(payload.get("value"))
            tenant_id = None
            graph_expandable = False
            reason = "Opaque external identifiers do not identify a graph object"
        else:
            raise RuntimeError(
                "native external reference has an unsupported target type"
            )
        relationship_type = _clean(payload.get("relationship_type"))
        if not (system and root_euid and relationship_type):
            raise RuntimeError("native external reference projection is incomplete")
        if graph_expandable:
            missing: list[str] = []
            if not atlas_base_url:
                missing.append("atlas.base_url")
            if not atlas_token:
                missing.append("atlas.token")
            if missing:
                graph_expandable = False
                reason = "Missing Atlas graph metadata: " + ", ".join(missing)
        href = None
        if graph_expandable:
            params = {"start_euid": root_euid, "depth": 4}
            if tenant_id is not None:
                params["tenant_id"] = tenant_id
            href = f"{atlas_base_url}/graph?{urlencode(params)}"
        ref = ExternalGraphRef(
            label=f"{system}:{relationship_type}:{root_euid}",
            system=system,
            root_euid=root_euid,
            tenant_id=tenant_id,
            href=href,
            graph_expandable=graph_expandable,
            reason=reason,
            relationship_type=relationship_type,
        )
        refs[
            (
                ref.system,
                ref.label,
                ref.root_euid,
                ref.tenant_id or "",
                ref.relationship_type or "",
            )
        ] = ref

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
    if isinstance(value, str):
        clean = value.strip()
        return clean or None
    return None


def _props(instance: Any) -> dict[str, Any]:
    payload = _as_dict(getattr(instance, "json_addl", None))
    return _as_dict(payload.get("properties"))


def _props_from_json_addl(json_addl: Any) -> dict[str, Any]:
    payload = _as_dict(json_addl)
    return _as_dict(payload.get("properties"))
