#!/usr/bin/env python3
"""Plan or apply Bloom's bounded TapDB 10.1 metadata/reference conversion.

This command performs no schema migration, template setup, principal changes,
sequence operations, backup, or writer fencing. The operator must supply the
frozen native source contract and run it only inside the reviewed outage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from collections import Counter, defaultdict
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

TAPDB_VERSION = "10.1.3"


def _read_object(path: Path) -> dict[str, Any]:
    def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as handle:
        value = json.load(
            handle,
            object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number in {path}: {value}")
            ),
        )
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write_new(path: Path, value: dict[str, Any]) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("receipt path must be canonical and absolute")
    if not path.parent.is_dir():
        raise ValueError(f"receipt parent does not exist: {path.parent}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _replace_reserved(path: Path, value: dict[str, Any]) -> None:
    reserved = _read_object(path)
    if (
        reserved.get("schema_version") != "bloom-tapdb10-conversion-reservation/v1"
        or reserved.get("status") != "reserved"
    ):
        raise ValueError("conversion receipt is not the exact reserved output")
    temporary = path.with_name(path.name + f".final-{os.getpid()}")
    _write_new(temporary, value)
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _plan_equality_projection(plan: dict[str, Any]) -> dict[str, Any]:
    """Normalize only the native dry-run receipt timestamp for plan comparison."""

    projected = deepcopy(plan)
    for change in projected["conversion"]["metadata_changes"]:
        receipt = change["native_receipt"]
        recorded_at = receipt.get("recorded_at")
        if not isinstance(recorded_at, str) or not recorded_at:
            raise ValueError("native mutation dry-run receipt lacks recorded_at")
        parsed = datetime.fromisoformat(recorded_at)
        if parsed.tzinfo is None:
            raise ValueError("native mutation dry-run receipt timestamp lacks timezone")
        receipt["recorded_at"] = "<native-dry-run-timestamp>"
    return projected


@contextmanager
def _template_owner_scope(session: Any, owner_repo_name: str):
    """Apply Bloom's runtime template-owner visibility to native XRF calls."""

    from daylily_tapdb.models.template import generic_template
    from sqlalchemy import event
    from sqlalchemy.orm import with_loader_criteria

    if not owner_repo_name or owner_repo_name != owner_repo_name.strip():
        raise ValueError("template owner must be exact and non-empty")

    def apply_owner_criterion(execute_state: Any) -> None:
        if execute_state.is_select:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    generic_template,
                    generic_template.issuer_app_code == owner_repo_name,
                    include_aliases=True,
                )
            )

    event.listen(session, "do_orm_execute", apply_owner_criterion)
    try:
        yield
    finally:
        event.remove(session, "do_orm_execute", apply_owner_criterion)


def _properties(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("historical json_addl must be an object")
    value = payload.get("properties")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("historical json_addl.properties must be an object")
    return value


def _external_target(properties: dict[str, Any]):
    from daylily_tapdb.external_references import ExternalIdentifierTarget

    from bloom_lims.atlas_references import canonical_kind, canonical_target

    provider = str(properties.get("provider") or "").strip()
    if provider == "atlas":
        return canonical_target(properties)
    if provider != "dewey":
        raise ValueError("legacy BGX provider is not a supported canonical source")
    value = str(properties.get("reference_value") or "")
    if not value or value != value.strip():
        raise ValueError("Dewey legacy reference_value must be exact and non-empty")
    return ExternalIdentifierTarget(
        namespace="dewey",
        kind=canonical_kind(properties.get("reference_type")),
        value=value,
        scope="public_global",
    )


_GRAPH_RELATIONSHIP_BY_REFERENCE_TYPE = {
    "atlas_test_fulfillment_item": "fulfills_atlas_test_fulfillment_item",
    "atlas_test_process_item": "fulfills_atlas_test_fulfillment_item",
    "atlas_patient": "derived_from_atlas_patient",
    "atlas_trf": "received_from_atlas_trf",
    "atlas_test": "prepared_for_atlas_test",
    "atlas_testkit": "received_with_atlas_testkit",
    "atlas_shipment": "received_in_atlas_shipment",
    "atlas_organization_site": "received_from_atlas_organization_site",
    "atlas_collection_event": "collected_during_atlas_event",
    "order_euid": "references_order_euid",
    "order_test_euid": "references_order_test_euid",
    "patient_id": "references_patient_id",
    "atlas_tenant_id": "references_atlas_tenant_id",
}
_REFERENCE_VALUE_FIELD_BY_TYPE = {
    "atlas_test_fulfillment_item": "atlas_test_fulfillment_item_euid",
    "atlas_test_process_item": "atlas_test_fulfillment_item_euid",
    "atlas_patient": "atlas_patient_euid",
    "atlas_trf": "atlas_trf_euid",
    "atlas_test": "atlas_test_euid",
    "atlas_testkit": "atlas_testkit_euid",
    "atlas_shipment": "atlas_shipment_euid",
    "atlas_organization_site": "atlas_organization_site_euid",
    "atlas_collection_event": "atlas_collection_event_euid",
    "order_euid": "order_euid",
    "order_test_euid": "order_test_euid",
}


def _graph_reference_keys(
    records: list[dict[str, Any]],
) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for item in records:
        properties = item["properties"]
        if str(properties.get("provider") or "").strip() != "atlas":
            continue
        reference_type = str(properties.get("reference_type") or "").strip()
        relationship = _GRAPH_RELATIONSHIP_BY_REFERENCE_TYPE.get(reference_type)
        if relationship is None:
            continue
        value = str(properties.get("reference_value") or "").strip()
        value_field = _REFERENCE_VALUE_FIELD_BY_TYPE.get(reference_type)
        if value_field and properties.get(value_field) is not None:
            direct = str(properties.get(value_field) or "").strip()
            if direct != value:
                raise ValueError(
                    "legacy BGX explicit identity field diverges from reference_value"
                )
        tenant = str(properties.get("atlas_tenant_id") or "").strip()
        keys.add((value, relationship, tenant, reference_type))
    return keys


def _partition_graph_entries(
    graph: list[dict[str, Any]],
    allowed: set[tuple[str, str, str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    archived: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for position, entry in enumerate(graph):
        if str(entry.get("system") or "").strip() != "atlas":
            raise ValueError("retired graph contains a non-Atlas entry")
        root = str(entry.get("root_euid") or entry.get("target_euid") or "").strip()
        relationship = str(entry.get("relationship_type") or "").strip()
        tenant = str(entry.get("tenant_id") or "").strip()
        source_field = str(entry.get("source_field") or "").strip()
        if not root or not relationship or not source_field:
            raise ValueError("retired graph entry is malformed")
        candidates = {
            key
            for key in allowed
            if key[0] == root
            and key[1] == relationship
            and key[2] == tenant
            and key[3] == source_field
        }
        if candidates:
            archived.append({"position": position, "entry": deepcopy(entry)})
        else:
            unresolved.append(deepcopy(entry))
    return archived, unresolved


def _converted_payload(
    payload: dict[str, Any], *, archive_key: str
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    result = deepcopy(payload)
    if archive_key in result:
        raise ValueError("conversion archive key already exists; inspect before replay")
    if "properties" not in result:
        result["properties"] = {}
    properties = result["properties"]
    if not isinstance(properties, dict):
        raise ValueError("existing properties must be an object")
    forbidden = {
        key
        for key in properties
        if key in {"object_euid", "target_object_euid"} or key.endswith("_object_euid")
    }
    if forbidden:
        raise ValueError("metadata pseudo-edge fields require separate disposition")
    external = properties.get("external_payload")
    if external is not None and not isinstance(external, dict):
        raise ValueError("existing external_payload must be an object")
    graph: list[dict[str, Any]] = []
    graph_present = isinstance(external, dict) and "tapdb_graph" in external
    if graph_present:
        raw_graph = external["tapdb_graph"]
        if not isinstance(raw_graph, list) or any(
            not isinstance(item, dict) for item in raw_graph
        ):
            raise ValueError("retired tapdb_graph must be its observed list shape")
        graph = deepcopy(raw_graph)
        result[archive_key] = {
            "properties.external_payload.tapdb_graph": deepcopy(graph)
        }
        del external["tapdb_graph"]
    return result, graph, graph_present


def _source_inventory(path: Path) -> dict[str, Any]:
    from daylily_tapdb.backup.source_contract import validate_source_contract
    from daylily_tapdb.identity_inventory import validate_receipt

    document = _read_object(path)
    if document.get("schema_version") != "tapdb-source-contract/v1":
        raise ValueError("--source-contract must be a frozen native source contract")
    validate_source_contract(document)
    inventory = document["identity_inventory"]
    validate_receipt(inventory, "tapdb-identity-inventory/v1")
    return inventory


def _legacy_references(session: Any, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    from daylily_tapdb.identity_inventory import content_hash
    from daylily_tapdb.models.instance import generic_instance
    from daylily_tapdb.models.lineage import generic_instance_lineage

    legacy = manifest["legacy_reference"]
    refs = (
        session.query(generic_instance)
        .filter(
            generic_instance.euid_prefix == legacy["euid_prefix"],
        )
        .order_by(generic_instance.uid.asc())
        .all()
    )
    records: list[dict[str, Any]] = []
    for ref in refs:
        if (
            ref.category != legacy["category"]
            or ref.type != legacy["type"]
            or ref.subtype != legacy["subtype"]
        ):
            raise ValueError("BGX identity has an unexpected historical template shape")
        props = _properties(ref.json_addl)
        lineages = (
            session.query(generic_instance_lineage)
            .filter(
                generic_instance_lineage.child_instance_uid == ref.uid,
                generic_instance_lineage.relationship_type
                == legacy["relationship_type"],
            )
            .order_by(generic_instance_lineage.uid.asc())
            .all()
        )
        if len(lineages) > 1:
            raise ValueError("legacy BGX has multiple owning lineages")
        lineage = lineages[0] if lineages else None
        source = lineage.parent_instance if lineage is not None else None
        provider = str(props.get("provider") or "").strip()
        reference_type = str(props.get("reference_type") or "").strip()
        reference_value = str(props.get("reference_value") or "")
        if not provider and not reference_type and not reference_value and not lineages:
            disposition = "unresolved_orphan"
            target = None
        else:
            if lineage is None or source is None:
                raise ValueError("typed legacy BGX lacks one owning lineage and source")
            if source.is_deleted:
                disposition = "deleted_source"
                target = None
            else:
                target = _external_target(props)
                disposition = f"canonical_{provider}"
            if bool(ref.is_deleted) != bool(lineage.is_deleted):
                raise ValueError(
                    "legacy BGX and its lineage have divergent deletion state"
                )
        lineage_evidence = [
            {
                "uid": item.uid,
                "euid": item.euid,
                "deleted": bool(item.is_deleted),
                "source_uid": item.parent_instance_uid,
                "source_euid": (
                    item.parent_instance.euid
                    if item.parent_instance is not None
                    else None
                ),
            }
            for item in lineages
        ]
        records.append(
            {
                "ref": ref,
                "lineage": lineage,
                "lineages": lineages,
                "source": source,
                "target": target,
                "properties": props,
                "disposition": disposition,
                "fingerprint": content_hash(
                    {
                        "ref_uid": ref.uid,
                        "ref_euid": ref.euid,
                        "ref_deleted": ref.is_deleted,
                        "ref_json_addl": ref.json_addl,
                        "lineages": lineage_evidence,
                    }
                ),
            }
        )
    return records


def _legacy_preservation(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ref_uid": item["ref"].uid,
            "ref_euid": item["ref"].euid,
            "ref_deleted": bool(item["ref"].is_deleted),
            "lineages": [
                {
                    "uid": lineage.uid,
                    "euid": lineage.euid,
                    "deleted": bool(lineage.is_deleted),
                    "source_uid": lineage.parent_instance_uid,
                    "source_euid": (
                        lineage.parent_instance.euid
                        if lineage.parent_instance is not None
                        else None
                    ),
                }
                for lineage in item["lineages"]
            ],
            "disposition": item["disposition"],
            "fingerprint": item["fingerprint"],
        }
        for item in records
    ]


def _collect_plan(
    session: Any, manifest: dict[str, Any], *, actor: str
) -> tuple[dict[str, Any], dict[int, Any], list[dict[str, Any]]]:
    from daylily_tapdb.identity_inventory import content_hash
    from daylily_tapdb.models.instance import generic_instance
    from daylily_tapdb.services.object_operations import ObjectSelector, update_object

    expected = manifest["expected"]
    archive_key = manifest["archive"]["root_key"]
    references = _legacy_references(session, manifest)
    active = sum(not item["ref"].is_deleted for item in references)
    deleted = len(references) - active
    if (len(references), active, deleted) != (
        expected["legacy_bgx_total"],
        expected["legacy_bgx_active"],
        expected["legacy_bgx_deleted"],
    ):
        raise ValueError("legacy BGX population differs from reviewed manifest")
    dispositions = Counter(item["disposition"] for item in references)
    if dict(sorted(dispositions.items())) != expected["legacy_dispositions"]:
        raise ValueError("legacy BGX dispositions differ from reviewed manifest")

    reference_keys: dict[int, set[tuple[str, str, str, str]]] = defaultdict(set)
    for item in references:
        if item["source"] is not None:
            reference_keys[item["source"].uid].update(_graph_reference_keys([item]))

    changes: list[dict[str, Any]] = []
    objects: dict[int, Any] = {}
    observed_prefixes: Counter[str] = Counter()
    missing_sys = 0
    graph_rows = 0
    graph_entries = 0
    archived_graph_rows = 0
    archived_graph_entries = 0
    unresolved_graph_rows = 0
    unresolved_graph_entries = 0
    mixed_graph_rows = 0
    empty_graph_rows = 0
    for obj in session.query(generic_instance).order_by(generic_instance.uid.asc()):
        original = obj.json_addl
        if not isinstance(original, dict):
            raise ValueError("existing generic_instance.json_addl must be an object")
        missing_properties = "properties" not in original
        proposed, graph, graph_present = _converted_payload(
            original, archive_key=archive_key
        )
        if missing_properties:
            if obj.euid_prefix != "SYS":
                raise ValueError("only reviewed SYS rows may receive missing envelopes")
            missing_sys += 1
        if graph_present:
            graph_rows += 1
            graph_entries += len(graph)
            observed_prefixes[str(obj.euid_prefix)] += 1
            allowed = reference_keys.get(obj.uid, set())
            archived, unresolved = _partition_graph_entries(graph, allowed)
            if not graph:
                empty_graph_rows += 1
            if archived:
                archived_graph_rows += 1
                archived_graph_entries += len(archived)
                proposed[archive_key] = {
                    "properties.external_payload.tapdb_graph": {
                        "original_length": len(graph),
                        "archived_entries": archived,
                    }
                }
            else:
                proposed.pop(archive_key, None)
            if unresolved:
                unresolved_graph_rows += 1
                unresolved_graph_entries += len(unresolved)
                proposed["properties"]["external_payload"]["tapdb_graph"] = unresolved
            if archived and unresolved:
                mixed_graph_rows += 1
        if proposed == original:
            continue
        if obj.is_deleted:
            raise ValueError("reviewed metadata conversion cannot update a deleted row")
        receipt = update_object(
            session,
            ObjectSelector(uid=obj.uid, record_type="instance"),
            {"json_addl": proposed},
            actor=actor,
            dry_run=True,
        )
        changes.append(
            {
                "uid": obj.uid,
                "euid": obj.euid,
                "before": content_hash(original),
                "after": content_hash(proposed),
                "missing_properties": missing_properties,
                "archived_graph_entries": len(archived) if graph_present else 0,
                "unresolved_graph_entries": len(unresolved) if graph_present else 0,
                "archived_graph_key": bool(archived) if graph_present else False,
                "native_receipt": receipt,
            }
        )
        objects[obj.uid] = obj

    if missing_sys != expected["missing_properties_sys"]:
        raise ValueError("SYS envelope count differs from reviewed manifest")
    if graph_rows != expected["retired_graph_rows"]:
        raise ValueError("retired graph row count differs from reviewed manifest")
    graph_counts = {
        "retired_graph_entries": graph_entries,
        "archived_graph_rows": archived_graph_rows,
        "archived_graph_entries": archived_graph_entries,
        "unresolved_graph_rows": unresolved_graph_rows,
        "unresolved_graph_entries": unresolved_graph_entries,
        "mixed_graph_rows": mixed_graph_rows,
        "empty_graph_rows": empty_graph_rows,
    }
    if any(graph_counts[key] != expected[key] for key in graph_counts):
        raise ValueError("retired graph disposition differs from reviewed manifest")
    if (
        dict(sorted(observed_prefixes.items()))
        != expected["retired_graph_rows_by_prefix"]
    ):
        raise ValueError("retired graph prefix distribution differs from manifest")

    groups: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in references:
        if item["target"] is None:
            continue
        provider = str(item["properties"].get("provider") or "").strip()
        relationship = f"references_{provider}_{item['target'].kind}"
        groups[(item["source"].uid, item["target"].identity_key, relationship)].append(
            item
        )
    assertions: list[dict[str, Any]] = []
    for (_, _, relationship), evidence in sorted(groups.items()):
        first = evidence[0]
        if any(item["source"].uid != first["source"].uid for item in evidence):
            raise ValueError("canonical assertion group crosses Bloom sources")
        property_hashes = {content_hash(item["properties"]) for item in evidence}
        if len(property_hashes) != 1:
            raise ValueError(
                "duplicate canonical BGX group has differing properties; explicit disposition required"
            )
        assertions.append(
            {
                "source_uid": first["source"].uid,
                "source_euid": first["source"].euid,
                "relationship_type": relationship,
                "target": {
                    "namespace": first["target"].namespace,
                    "kind": first["target"].kind,
                    "value": first["target"].value,
                    "scope": first["target"].scope,
                },
                "active": any(not item["ref"].is_deleted for item in evidence),
                "properties": deepcopy(first["properties"]),
                "legacy_records": [
                    {
                        "ref_uid": item["ref"].uid,
                        "ref_euid": item["ref"].euid,
                        "ref_deleted": bool(item["ref"].is_deleted),
                        "lineage_uid": item["lineage"].uid,
                        "lineage_euid": item["lineage"].euid,
                        "lineage_deleted": bool(item["lineage"].is_deleted),
                        "fingerprint": item["fingerprint"],
                    }
                    for item in evidence
                ],
                "asserted_at": min(
                    item["ref"].created_dt for item in evidence
                ).isoformat(),
                "deactivated_at": max(
                    item["ref"].modified_dt for item in evidence
                ).isoformat(),
            }
        )
    return (
        {
            "metadata_changes": changes,
            "canonical_assertions": assertions,
            "legacy_bgx_preservation": _legacy_preservation(references),
            "observed": {
                "legacy_bgx_total": len(references),
                "legacy_bgx_active": active,
                "legacy_bgx_deleted": deleted,
                "missing_properties_sys": missing_sys,
                "retired_graph_rows": graph_rows,
                **graph_counts,
                "retired_graph_rows_by_prefix": dict(sorted(observed_prefixes.items())),
                "canonical_assertion_groups": len(assertions),
                "legacy_dispositions": dict(sorted(dispositions.items())),
            },
        },
        objects,
        references,
    )


def _assertion_material(assertion: dict[str, Any]) -> tuple[str, str]:
    from bloom_lims.atlas_references import (
        ASSERTION_AUTHORITY,
        DEWEY_ASSERTION_AUTHORITY,
        provenance,
    )

    provider = str(assertion["properties"].get("provider") or "").strip()
    authority = (
        ASSERTION_AUTHORITY if provider == "atlas" else DEWEY_ASSERTION_AUTHORITY
    )
    if provider == "atlas":
        rendered = provenance(
            assertion["properties"],
            evidence={"legacy_records": assertion["legacy_records"]},
        )
    elif provider == "dewey":
        rendered = json.dumps(
            {
                "contract": "bloom.dewey-reference/v1",
                "properties": assertion["properties"],
                "evidence": {"legacy_records": assertion["legacy_records"]},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(rendered) > 2048:
            raise ValueError("Dewey assertion provenance exceeds TapDB's bound")
    else:
        raise ValueError("canonical assertion has an unsupported provider")
    return authority, rendered


def _apply(session: Any, plan: dict[str, Any], *, actor: str) -> dict[str, Any]:
    from daylily_tapdb.external_references import (
        ExternalIdentifierTarget,
        ExternalLinkSpec,
        ExternalReferenceService,
    )
    from daylily_tapdb.models.instance import generic_instance
    from daylily_tapdb.services.object_operations import ObjectSelector, update_object

    outcomes: Counter[str] = Counter()
    for change in plan["conversion"]["metadata_changes"]:
        obj = (
            session.query(generic_instance)
            .filter(generic_instance.uid == change["uid"])
            .with_for_update()
            .one()
        )
        if obj.euid != change["euid"]:
            raise ValueError("metadata plan row identity changed")
        proposed = change["native_receipt"]["changes"]["json_addl"]["new"]
        update_object(
            session,
            ObjectSelector(uid=obj.uid, record_type="instance"),
            {"json_addl": proposed},
            actor=actor,
            dry_run=False,
        )

    service = ExternalReferenceService(session)
    for assertion in plan["conversion"]["canonical_assertions"]:
        source = (
            session.query(generic_instance)
            .filter(generic_instance.uid == assertion["source_uid"])
            .with_for_update()
            .one()
        )
        if source.euid != assertion["source_euid"] or source.is_deleted:
            raise ValueError("canonical assertion source changed or is deleted")
        target = ExternalIdentifierTarget(**assertion["target"])
        authority, assertion_provenance = _assertion_material(assertion)
        spec = ExternalLinkSpec(
            target=target,
            relationship_type=assertion["relationship_type"],
            assertion_authority=authority,
            asserted_at=datetime.fromisoformat(assertion["asserted_at"]),
            assertion_provenance=assertion_provenance,
        )
        with _template_owner_scope(session, "bloom"):
            outcome = service.attach(source, spec)
            outcomes[outcome.status] += 1
            if not assertion["active"]:
                detached = service.detach(
                    source,
                    target,
                    relationship_type=assertion["relationship_type"],
                    assertion_authority=authority,
                    deactivated_at=datetime.fromisoformat(assertion["deactivated_at"]),
                    deactivation_provenance=assertion_provenance,
                )
                outcomes[detached.status] += 1
    return dict(sorted(outcomes.items()))


def _verify_applied_state(
    session: Any, plan: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    from daylily_tapdb.external_references import ExternalReferenceService
    from daylily_tapdb.identity_inventory import content_hash
    from daylily_tapdb.models.instance import generic_instance

    for change in plan["conversion"]["metadata_changes"]:
        obj = (
            session.query(generic_instance)
            .filter(generic_instance.uid == change["uid"])
            .one()
        )
        if obj.euid != change["euid"] or content_hash(obj.json_addl) != change["after"]:
            raise ValueError("actual converted metadata differs from reviewed plan")
    preserved = _legacy_preservation(_legacy_references(session, manifest))
    if preserved != plan["conversion"]["legacy_bgx_preservation"]:
        raise ValueError("actual legacy BGX preservation differs from reviewed plan")

    expected_by_source: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for assertion in plan["conversion"]["canonical_assertions"]:
        authority, rendered = _assertion_material(assertion)
        expected_by_source[(assertion["source_uid"], authority)].append(
            {**assertion, "assertion_provenance": rendered}
        )
    service = ExternalReferenceService(session)
    checked = 0
    for (source_uid, authority), expected in expected_by_source.items():
        source = (
            session.query(generic_instance)
            .filter(generic_instance.uid == source_uid)
            .one()
        )
        page = service.list_for_source(
            source,
            assertion_authority=authority,
            include_inactive=True,
            limit=100,
        )
        if page["page"]["next_cursor"] is not None:
            raise ValueError("actual canonical assertion set exceeds reviewed bound")
        actual = {
            (
                item.get("namespace"),
                item.get("kind"),
                item.get("value"),
                item.get("relationship_type"),
            ): item
            for item in page["items"]
        }
        expected_keys = {
            (
                item["target"]["namespace"],
                item["target"]["kind"],
                item["target"]["value"],
                item["relationship_type"],
            )
            for item in expected
        }
        if set(actual) != expected_keys:
            raise ValueError("actual canonical assertion identities differ from plan")
        for item in expected:
            key = (
                item["target"]["namespace"],
                item["target"]["kind"],
                item["target"]["value"],
                item["relationship_type"],
            )
            observed = actual[key]
            if (
                bool(observed["active"]) != bool(item["active"])
                or observed["asserted_at"] != item["asserted_at"]
                or observed["assertion_provenance"] != item["assertion_provenance"]
            ):
                raise ValueError("actual canonical assertion state differs from plan")
            checked += 1
    return {
        "metadata_changes": len(plan["conversion"]["metadata_changes"]),
        "legacy_bgx": len(preserved),
        "canonical_assertions": checked,
    }


def main() -> int:
    from daylily_tapdb.cli.db_config import get_db_config
    from daylily_tapdb.identity_inventory import physical_target, validate_target
    from daylily_tapdb.runtime_principal import operator_connection
    from daylily_tapdb.security_context import (
        TapdbTransactionContext,
        apply_transaction_context,
        assert_operator_role,
    )
    from sqlalchemy.orm import Session

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "apply", "reconcile"))
    parser.add_argument("--operator-config", type=Path, required=True)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    parser.add_argument("--review-reference")
    parser.add_argument("--actor", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if importlib.metadata.version("daylily-tapdb") != TAPDB_VERSION:
        raise RuntimeError(f"exact daylily-tapdb {TAPDB_VERSION} is required")
    if not args.actor or args.actor != args.actor.strip():
        raise ValueError("actor must be exact and non-empty")
    for path in (args.operator_config, args.source_contract, args.manifest):
        if not path.is_absolute() or path.resolve() != path or not path.is_file():
            raise ValueError(
                f"input must be an existing canonical absolute file: {path}"
            )
    manifest = _read_object(args.manifest)
    if manifest.get("schema_version") != "bloom-tapdb10-conversion-manifest/v1":
        raise ValueError("unexpected Bloom conversion manifest")
    before = _source_inventory(args.source_contract)
    cfg = get_db_config(
        config_path=args.operator_config,
        client_id="bloom",
        database_name="bloom-day",
    )
    expected_target = manifest["target"]
    if (
        any(
            cfg.get(key) != expected_target[key]
            for key in (
                "engine_type",
                "database",
                "schema_name",
                "client_id",
                "database_name",
                "domain_code",
                "owner_repo_name",
                "allow_global_claims",
            )
        )
        or cfg.get("user") != expected_target["runtime_user"]
        or cfg.get("operator_user") != expected_target["operator_user"]
    ):
        raise ValueError("operator config differs from Bloom's reviewed target scope")
    target = validate_target(
        {
            "engine_type": cfg["engine_type"],
            "host": cfg["host"],
            "port": cfg["port"],
            "database": cfg["database"],
            "schema_name": cfg["schema_name"],
            "config_identity": str(args.operator_config),
            "domain_code": expected_target["domain_code"],
            "owner_repo_name": expected_target["owner_repo_name"],
        },
        cfg["schema_name"],
    )
    fingerprint = {
        "schema_version": "bloom-tapdb10-conversion-plan/v1",
        "operator_config": str(args.operator_config),
        "operator_config_sha256": _sha256(args.operator_config),
        "source_contract": str(args.source_contract),
        "source_contract_sha256": _sha256(args.source_contract),
        "source_inventory_sha256": before["sha256"],
        "manifest": str(args.manifest),
        "manifest_sha256": _sha256(args.manifest),
        "script_sha256": _sha256(Path(__file__)),
        "actor": args.actor,
        "target": target,
    }
    if args.operation in {"apply", "reconcile"}:
        if args.plan is None or not args.plan.is_absolute() or not args.plan.is_file():
            raise ValueError("apply/reconcile requires the reviewed canonical plan")
        if (
            not args.reviewed_plan_sha256
            or _sha256(args.plan) != args.reviewed_plan_sha256
            or not str(args.review_reference or "").strip()
        ):
            raise ValueError(
                "apply/reconcile requires the exact reviewed plan and review reference"
            )
        reviewed = _read_object(args.plan)
        if any(reviewed.get(key) != value for key, value in fingerprint.items()):
            raise ValueError("reviewed conversion inputs changed")

    if args.operation == "reconcile":
        reservation = _read_object(args.receipt)
        if (
            reservation.get("schema_version")
            != "bloom-tapdb10-conversion-reservation/v1"
            or reservation.get("status") != "reserved"
            or reservation.get("plan_sha256") != args.reviewed_plan_sha256
        ):
            raise ValueError("reconcile requires the exact reserved apply receipt")
        with operator_connection(
            cfg, isolation_level="REPEATABLE READ", read_only=True
        ) as connection:
            actual_physical = physical_target(connection, target)
            if actual_physical != before["physical_target"]:
                raise ValueError("live physical target differs from source contract")
            with Session(bind=connection, expire_on_commit=False) as session:
                apply_transaction_context(
                    session,
                    TapdbTransactionContext(
                        config_identity=str(args.operator_config),
                        schema_name=cfg["schema_name"],
                        domain_code="M",
                        owner_repo_name="bloom",
                        tenant_id=cfg.get("tenant_id") or None,
                        actor=args.actor,
                        allow_global_rows=True,
                    ),
                    assert_runtime_role=False,
                )
                assert_operator_role(
                    session,
                    schema_name=cfg["schema_name"],
                    operator_user=cfg["operator_user"],
                )
                reconciled = _verify_applied_state(session, reviewed, manifest)
        _replace_reserved(
            args.receipt,
            {
                "schema_version": "bloom-tapdb10-conversion-result/v1",
                "status": "reconciled_committed",
                "review_reference": args.review_reference,
                "plan_sha256": args.reviewed_plan_sha256,
                "physical_target": before["physical_target"],
                "observed": reviewed["conversion"]["observed"],
                "verified_state": reconciled,
            },
        )
        print(
            json.dumps({"status": "reconciled_committed", "receipt": str(args.receipt)})
        )
        return 0

    with operator_connection(
        cfg,
        isolation_level="REPEATABLE READ",
        read_only=args.operation == "plan",
    ) as connection:
        actual_physical = physical_target(connection, target)
        if actual_physical != before["physical_target"]:
            raise ValueError("live physical target differs from frozen source contract")
        with Session(bind=connection, expire_on_commit=False) as session:
            apply_transaction_context(
                session,
                TapdbTransactionContext(
                    config_identity=str(args.operator_config),
                    schema_name=cfg["schema_name"],
                    domain_code="M",
                    owner_repo_name="bloom",
                    tenant_id=cfg.get("tenant_id") or None,
                    actor=args.actor,
                    allow_global_rows=True,
                ),
                assert_runtime_role=False,
            )
            assert_operator_role(
                session,
                schema_name=cfg["schema_name"],
                operator_user=cfg["operator_user"],
            )
            conversion, _objects, _references = _collect_plan(
                session, manifest, actor=args.actor
            )
            plan = {
                **fingerprint,
                "physical_target": actual_physical,
                "conversion": conversion,
            }
            if args.operation == "plan":
                _write_new(args.receipt, plan)
                print(
                    json.dumps(
                        {
                            "status": "planned",
                            "receipt": str(args.receipt),
                            "sha256": _sha256(args.receipt),
                            "observed": conversion["observed"],
                        },
                        sort_keys=True,
                    )
                )
                return 0
            if _plan_equality_projection(plan) != _plan_equality_projection(reviewed):
                raise ValueError(
                    "live conversion plan changed after independent review"
                )
            _write_new(
                args.receipt,
                {
                    "schema_version": "bloom-tapdb10-conversion-reservation/v1",
                    "status": "reserved",
                    "plan_sha256": args.reviewed_plan_sha256,
                },
            )
            outcomes = _apply(session, reviewed, actor=args.actor)
            preserved = _legacy_preservation(_legacy_references(session, manifest))
            if preserved != reviewed["conversion"]["legacy_bgx_preservation"]:
                raise RuntimeError(
                    "legacy BGX identity or lineage changed during conversion"
                )
            verified_state = _verify_applied_state(session, reviewed, manifest)

    _replace_reserved(
        args.receipt,
        {
            "schema_version": "bloom-tapdb10-conversion-result/v1",
            "status": "committed",
            "review_reference": args.review_reference,
            "plan_sha256": args.reviewed_plan_sha256,
            "physical_target": before["physical_target"],
            "observed": reviewed["conversion"]["observed"],
            "native_external_reference_outcomes": outcomes,
            "verified_state": verified_state,
        },
    )
    print(json.dumps({"status": "committed", "receipt": str(args.receipt)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "stopped", "error_class": type(exc).__name__},
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
