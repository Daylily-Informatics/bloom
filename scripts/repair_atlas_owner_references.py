"""Bounded Bloom Atlas owner-reference repair for an operator-owned Session.

No connection, credentials, application bootstrap, commit or CLI is created here.
The coordinator supplies exact inventory rows and a live native owner lookup,
reviews ``preflight`` in a read-only transaction, and alone calls ``apply`` in
a separate write transaction after approval and an identical preflight.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Callable, Sequence
from uuid import UUID

from daylily_tapdb import generic_instance
from daylily_tapdb.external_references import (
    ExternalIdentifierTarget,
    ExternalLinkSpec,
    ExternalReferenceService,
    TapDBObjectTarget,
)
from sqlalchemy import text

AUTHORITY = "bloom.atlas-references"
OWNER = "atlas"
MAXIMUM = 174
OwnerLookup = Callable[[str], dict[str, Any]]


def select_inventory_rows(receipt: dict) -> list[dict]:
    """Select the exact active historical Atlas-owner cohort, without fallback."""
    if not isinstance(receipt, dict) or set(receipt.get("services", {})) != {
            "bloom", "dewey", "ursa"}:
        raise ValueError("expected exact three-service native producer inventory")
    inventory = receipt["services"]["bloom"]["inventory"]
    if inventory.get("service") != "bloom" or inventory.get("active_xrf_count") != 188:
        raise ValueError("Bloom native cohort count or service differs")
    rows = [row for row in inventory["records"] if
            row.get("assertion_authority") == AUTHORITY and
            row.get("target_service_id") == OWNER and
            row.get("target_type") == "opaque" and
            row.get("target_scope_claim") == "public_global" and
            row.get("source_tenant_scope") == "global"]
    if len(rows) != MAXIMUM or len({row["lineage_euid"] for row in rows}) != MAXIMUM:
        raise ValueError("Bloom historical Atlas owner selection differs from exact 174")
    return rows


def _owner_target(euid: str, lookup: OwnerLookup) -> tuple[TapDBObjectTarget, dict]:
    body = lookup(euid)
    if not isinstance(body, dict) or body.get("service_id") != OWNER:
        raise ValueError(f"Atlas owner service mismatch for {euid}")
    if body.get("euid") != euid or body.get("record_type") != "instance":
        raise ValueError(f"Atlas persisted object mismatch for {euid}")
    if "tenant_id" not in body:
        raise ValueError(f"Atlas owner scope missing for {euid}")
    tenant_text = body["tenant_id"]
    tenant = None
    if tenant_text is not None:
        if not isinstance(tenant_text, str):
            raise ValueError(f"Atlas owner tenant invalid for {euid}")
        tenant = UUID(tenant_text)
        if str(tenant) != tenant_text:
            raise ValueError(f"Atlas owner tenant noncanonical for {euid}")
    return TapDBObjectTarget(OWNER, euid, target_tenant_id=tenant), body


def _selected(session: Any, rows: Sequence[dict], lookup: OwnerLookup) -> list[dict]:
    if not 1 <= len(rows) <= MAXIMUM:
        raise ValueError(f"repair selection must contain 1..{MAXIMUM} exact rows")
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("repair preflight requires a clean Session")
    service = ExternalReferenceService(session)
    seen: set[tuple[str, str, str]] = set()
    owner_cache: dict[str, tuple[TapDBObjectTarget, dict]] = {}
    selected = []
    for row in rows:
        identity = (row["source_euid"], row["xrf_euid"], row["lineage_euid"])
        if identity in seen:
            raise ValueError("duplicate selected inventory triple")
        seen.add(identity)
        if (row.get("assertion_authority"), row.get("target_service_id"),
                row.get("target_type")) != (AUTHORITY, OWNER, "opaque"):
            raise ValueError("selection includes a non-Atlas-owner opaque row")
        euid = row["candidate_target_euid"]
        source = session.query(generic_instance).filter_by(euid=identity[0], is_deleted=False).one()
        if source.tenant_id is not None or row.get("source_tenant_scope") != "global":
            raise ValueError("selected historical source is no longer global")
        listed = service.list_for_source(source, assertion_authority=AUTHORITY, limit=100)
        if listed["page"]["next_cursor"] is not None:
            raise ValueError("selected Bloom source exceeds 100 active references")
        matches = [item for item in listed["items"] if
                   item["external_reference_euid"] == identity[1] and
                   item["lineage_euid"] == identity[2]]
        if len(matches) != 1:
            raise ValueError("selected active XRF/lineage changed")
        old = matches[0]
        if (old["target_type"] != "opaque" or old["scope"] != "public_global" or
                old["relationship_type"] != row["relationship_type"] or
                old["asserted_at"] != row["asserted_at"] or
                hashlib.sha256(old["assertion_provenance"].encode()).hexdigest()
                != row["assertion_provenance_sha256"]):
            raise ValueError("selected assertion changed since inventory")
        if old["value"] != euid:
            raise ValueError("selected owner candidate differs from stored opaque value")
        if any(item["target_type"] == "tapdb_object" and
               item.get("target_service_id") == OWNER and
               item.get("target_object_euid") == euid and
               item["relationship_type"] == old["relationship_type"]
               for item in listed["items"]):
            raise ValueError("native Atlas assertion already exists for selected relation")
        if euid not in owner_cache:
            owner_cache[euid] = _owner_target(euid, lookup)
        new_target, owner = owner_cache[euid]
        from bloom_lims.atlas_references import require_atlas_owner_kind

        require_atlas_owner_kind(old["kind"], owner)
        old_target = ExternalIdentifierTarget(
            namespace=old["namespace"], kind=old["kind"], value=old["value"],
            scope=old["scope"], canonical_uri=old.get("canonical_uri"),
        )
        document = json.loads(old["assertion_provenance"])
        if (not isinstance(document, dict) or
                document.get("contract") != "bloom.atlas-reference/v1" or
                not isinstance(document.get("properties"), dict) or
                document["properties"].get("reference_value") != euid):
            raise ValueError("historical Bloom provenance cannot be converted exactly")
        properties = dict(document["properties"])
        properties.update(
            atlas_native_record_type="instance",
            atlas_native_scope="tenant" if new_target.target_tenant_id else "global",
            atlas_native_tenant_id=(str(new_target.target_tenant_id)
                                    if new_target.target_tenant_id else None),
        )
        evidence = dict(document.get("evidence") or {})
        evidence["bounded_repair"] = {
            "old_lineage_euid": identity[2],
            "old_assertion_sha256": row["assertion_provenance_sha256"],
            "owner_service_id": OWNER,
            "owner_euid": euid,
        }
        new_provenance = json.dumps(
            {"contract": "bloom.atlas-reference/v1", "properties": properties,
             "evidence": evidence}, sort_keys=True, separators=(",", ":"),
        )
        if len(new_provenance) > 2048:
            raise ValueError("bounded repair provenance exceeds native limit")
        # Keep the exact old assertion in the historical lineage; the new
        # provenance refers to it by durable lineage identity and hash.
        selected.append({"source": source, "old": old_target, "new": new_target,
                         "row": row, "new_provenance": new_provenance,
                         "owner_scope": "tenant" if owner["tenant_id"] else "global"})
    return selected


def preflight(session: Any, rows: Sequence[dict], owner_lookup: OwnerLookup) -> dict:
    if session.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
        raise RuntimeError("preflight requires a read-only transaction")
    with session.no_autoflush:
        selected = _selected(session, rows, owner_lookup)
    return {"selected": len(selected), "global_owner": sum(
        item["owner_scope"] == "global" for item in selected),
        "tenant_owner": sum(item["owner_scope"] == "tenant" for item in selected),
        "triples": [{key: item["row"][key] for key in
                     ("source_euid", "xrf_euid", "lineage_euid")}
                    for item in selected]}


def apply(session: Any, rows: Sequence[dict], owner_lookup: OwnerLookup,
          *, deactivation_provenance: str) -> dict:
    """Apply exact owner-proven rows; caller owns authorization and commit."""
    if session.execute(text("SHOW transaction_read_only")).scalar_one() != "off":
        raise RuntimeError("apply requires an operator-owned write transaction")
    if not deactivation_provenance or len(deactivation_provenance) > 2048:
        raise ValueError("exact bounded deactivation provenance required")
    selected = _selected(session, rows, owner_lookup)
    service = ExternalReferenceService(session)
    outcomes = []
    for item in selected:
        row = item["row"]
        old = service.detach(
            item["source"], item["old"],
            relationship_type=row["relationship_type"], assertion_authority=AUTHORITY,
            deactivated_at=datetime.now(UTC),
            deactivation_provenance=deactivation_provenance,
        )
        if old.status != "deactivated" or old.lineage.euid != row["lineage_euid"]:
            raise RuntimeError("exact historical lineage was not deactivated")
        new = service.attach(item["source"], ExternalLinkSpec(
            target=item["new"], relationship_type=row["relationship_type"],
            assertion_authority=AUTHORITY,
            asserted_at=datetime.fromisoformat(row["asserted_at"]),
            assertion_provenance=item["new_provenance"],
        ))
        if new.status != "created":
            raise RuntimeError("replacement native lineage was not newly created")
        outcomes.append({"old_lineage_euid": old.lineage.euid,
                         "new_lineage_euid": new.lineage.euid,
                         "new_xrf_euid": new.reference.euid})
    return {"selected": len(selected), "outcomes": outcomes}


def readback(session: Any, rows: Sequence[dict], outcomes: Sequence[dict],
             owner_lookup: OwnerLookup) -> dict:
    """Verify committed old history and exact new native assertions read-only."""
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("readback requires a clean Session")
    if session.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
        raise RuntimeError("readback requires an already read-only transaction")
    if not 1 <= len(rows) <= MAXIMUM or len(outcomes) != len(rows):
        raise ValueError("readback needs exact selected rows and apply outcomes")
    outcomes_by_old = {item["old_lineage_euid"]: item for item in outcomes}
    if len(outcomes_by_old) != len(rows):
        raise ValueError("readback outcomes have duplicate old lineage")
    service = ExternalReferenceService(session)
    verified = []
    with session.no_autoflush:
        for row in rows:
            old_lineage_euid = row["lineage_euid"]
            outcome = outcomes_by_old.get(old_lineage_euid)
            if outcome is None:
                raise ValueError("selected old lineage has no apply outcome")
            source = session.query(generic_instance).filter_by(
                euid=row["source_euid"], is_deleted=False).one()
            listed = service.list_for_source(
                source, assertion_authority=AUTHORITY, include_inactive=True,
                limit=500,
            )
            if listed["page"]["next_cursor"] is not None:
                raise ValueError("selected source exceeded bounded readback page")
            old_items = [item for item in listed["items"] if
                         item["lineage_euid"] == old_lineage_euid]
            new_items = [item for item in listed["items"] if
                         item["lineage_euid"] == outcome["new_lineage_euid"]]
            if len(old_items) != 1 or len(new_items) != 1:
                raise ValueError("selected old/new native lineage missing or duplicated")
            old, new = old_items[0], new_items[0]
            if (old["active"] is not False or
                    old["external_reference_euid"] != row["xrf_euid"] or
                    old["target_type"] != "opaque" or
                    old["relationship_type"] != row["relationship_type"] or
                    old["asserted_at"] != row["asserted_at"] or
                    hashlib.sha256(old["assertion_provenance"].encode()).hexdigest()
                    != row["assertion_provenance_sha256"] or
                    not old.get("deactivated_at") or
                    not old.get("deactivation_provenance")):
                raise ValueError("historical Atlas assertion not preserved inactive")
            owner_target, owner = _owner_target(row["candidate_target_euid"], owner_lookup)
            from bloom_lims.atlas_references import require_atlas_owner_kind

            require_atlas_owner_kind(old["kind"], owner)
            expected_tenant = (str(owner_target.target_tenant_id)
                               if owner_target.target_tenant_id else None)
            provenance = json.loads(new["assertion_provenance"])
            if (new["active"] is not True or
                    new["external_reference_euid"] != outcome["new_xrf_euid"] or
                    new["target_type"] != "tapdb_object" or
                    new["target_service_id"] != OWNER or
                    new["target_object_euid"] != row["candidate_target_euid"] or
                    new.get("target_tenant_id") != expected_tenant or
                    new["relationship_type"] != row["relationship_type"] or
                    new["asserted_at"] != row["asserted_at"] or
                    provenance.get("contract") != "bloom.atlas-reference/v1" or
                    provenance.get("evidence", {}).get("bounded_repair", {}).get(
                        "old_lineage_euid") != old_lineage_euid or
                    provenance.get("evidence", {}).get("bounded_repair", {}).get(
                        "old_assertion_sha256") != row["assertion_provenance_sha256"]):
                raise ValueError("replacement Atlas assertion differs from owner proof")
            verified.append({"source_euid": source.euid,
                             "old_lineage_euid": old_lineage_euid,
                             "new_lineage_euid": new["lineage_euid"],
                             "new_xrf_euid": new["external_reference_euid"]})
    return {"verified": len(verified), "lineages": verified}
