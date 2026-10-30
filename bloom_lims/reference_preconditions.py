"""Observed native revisions for Bloom's already-authorized reference writes."""

from daylily_tapdb.external_references import ExternalReferenceService
from daylily_tapdb.models.lineage import generic_instance_lineage as Lineage
from sqlalchemy import select


def reference_preconditions(session, source, target, relationship):
    session.flush()
    source_revision = source.record_revision
    reference = ExternalReferenceService(session).resolve(target)
    edge = None
    if reference is not None:
        edge = session.scalars(select(Lineage).where(
            Lineage.parent_instance_uid == source.uid,
            Lineage.child_instance_uid == reference.uid,
            Lineage.relationship_type == relationship,
        )).one_or_none()
    return {"expected_source_revision": source_revision,
            "expected_lineage_revision": edge.record_revision if edge is not None else None}


def authority_preconditions(session, source, authority):
    session.flush()
    source_revision = source.record_revision
    result = ExternalReferenceService(session).list_for_source(
        source, assertion_authority=authority, limit=500,
    )
    if result["page"]["next_cursor"] is not None:
        raise ValueError("Reference authority set exceeds the native reconcile bound")
    euids = [item["lineage_euid"] for item in result["items"]]
    edges = session.scalars(select(Lineage).where(Lineage.euid.in_(euids))).all() if euids else []
    if len(edges) != len(euids):
        raise ValueError("Reference authority set changed during observation")
    return {"expected_source_revision": source_revision,
            "expected_lineage_revisions": {edge.euid: edge.record_revision for edge in edges}}
