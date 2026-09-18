"""Token-authenticated graph read endpoints for cross-system integrations."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, text

from bloom_lims.api.v1.dependencies import APIUser, require_api_auth, require_read
from bloom_lims.api.v1.owner_contracts import OwnerSnapshotRequest, canonical_sha256
from bloom_lims.domain import BloomObj
from bloom_lims.graph_support import (
    build_graph_elements_for_start,
    build_graph_meta_for_nodes,
    build_graph_object_payload,
    normalize_graph_request_params,
)
from bloom_lims.tapdb_adapter import BLOOMdb3

router = APIRouter(prefix="/graph", tags=["graph"])
logger = logging.getLogger(__name__)


@router.post("/snapshot")
def get_owner_snapshot(
    data: OwnerSnapshotRequest,
    user: APIUser = Depends(require_read),
):
    """Read only the exact requested live objects and persisted lineage edges."""
    try:
        with BLOOMdb3(app_username=user.email) as bdb:
            session = bdb.new_session()
            # Configure the fresh connection before its first statement. The
            # adapter's after_begin hook retains native TapDB scope and actor.
            session.connection(execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            })
            isolation = session.execute(text("SHOW transaction_isolation")).scalar_one()
            read_only = session.execute(text("SHOW transaction_read_only")).scalar_one()
            if isolation != "repeatable read" or read_only != "on":
                raise RuntimeError("Owner snapshot requires a read-only repeatable-read transaction")
            observed_at = session.execute(text("SELECT transaction_timestamp()")).scalar_one()
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise RuntimeError("Owner snapshot requires a timezone-bearing source timestamp")

            model = bdb.Base.classes.generic_instance
            objects = session.query(model).filter(
                model.euid.in_(data.object_euids), model.is_deleted.is_(False)
            ).limit(len(data.object_euids) + 1).all()
            by_euid = {obj.euid: obj for obj in objects}
            if len(by_euid) != len(objects) or set(by_euid) != set(data.object_euids):
                raise HTTPException(status_code=409, detail="Requested live owner object set is incomplete or ambiguous")
            by_uid = {obj.uid: obj.euid for obj in objects}
            if len(by_uid) != len(objects):
                raise HTTPException(status_code=409, detail="Requested owner object identities are ambiguous")

            lineage = bdb.Base.classes.generic_instance_lineage
            edges = []
            if data.lineage_selectors:
                clauses = [and_(
                    lineage.parent_instance_uid == by_euid[item.parent_euid].uid,
                    lineage.child_instance_uid == by_euid[item.child_euid].uid,
                    lineage.relationship_type == item.relationship_type,
                ) for item in data.lineage_selectors]
                edges = session.query(lineage).filter(
                    lineage.is_deleted.is_(False), or_(*clauses)
                ).limit(len(data.lineage_selectors) + 1).all()
            edge_payloads = [{
                "euid": edge.euid,
                "parent_euid": by_uid[edge.parent_instance_uid],
                "child_euid": by_uid[edge.child_instance_uid],
                "relationship_type": edge.relationship_type,
                "is_deleted": False,
            } for edge in edges]
            selected = {(row["parent_euid"], row["child_euid"], row["relationship_type"]) for row in edge_payloads}
            requested = {item.identity() for item in data.lineage_selectors}
            if (selected != requested or len(selected) != len(edges)
                    or len({edge.euid for edge in edges}) != len(edges)):
                raise HTTPException(status_code=409, detail="Requested live owner lineage set is incomplete or ambiguous")

            payload = {
                "schema": "bloom.owner_snapshot/1",
                "request_sha256": canonical_sha256(data.canonical_request()),
                "observed_at": observed_at.isoformat(),
                "transaction_isolation": isolation,
                "read_only": True,
                "complete": True,
                "objects": [{
                    "euid": obj.euid,
                    "name": obj.name,
                    "type": obj.type,
                    "subtype": obj.subtype,
                    "status": obj.bstatus,
                    "json_addl": obj.json_addl,
                    "created_at": obj.created_dt.isoformat() if obj.created_dt else None,
                    "is_deleted": False,
                } for obj in sorted(objects, key=lambda item: item.euid)],
                "lineages": sorted(edge_payloads, key=lambda row: (
                    row["parent_euid"], row["child_euid"], row["relationship_type"], row["euid"]
                )),
            }
            payload["snapshot_sha256"] = canonical_sha256(payload)
            return payload
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to capture the requested owner snapshot")
        raise HTTPException(status_code=500, detail="Owner snapshot capture failed") from exc


@router.get("/data")
async def get_graph_data(
    start_euid: str | None = Query(default=None),
    depth: int = Query(default=4, ge=1, le=10),
    user: APIUser = Depends(require_api_auth),
):
    resolved_start_euid, resolved_depth = normalize_graph_request_params(
        start_euid, depth
    )
    try:
        bobj = BloomObj(BLOOMdb3(app_username=user.email))
        nodes, edges = build_graph_elements_for_start(
            bobj, resolved_start_euid, resolved_depth
        )
        meta = {"start_euid": resolved_start_euid, "depth": resolved_depth}
        meta.update(build_graph_meta_for_nodes(nodes))
        return {
            "elements": {"nodes": nodes, "edges": edges},
            "meta": meta,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load graph data: {exc}"
        ) from exc


@router.get("/object/{euid}")
async def get_graph_object(
    euid: str,
    user: APIUser = Depends(require_api_auth),
):
    try:
        bobj = BloomObj(BLOOMdb3(app_username=user.email))
        return build_graph_object_payload(bobj, euid)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"Object not found: {euid}"
        ) from exc
