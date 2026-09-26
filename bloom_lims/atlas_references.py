"""Bloom's native TapDB external-reference contract for Atlas identifiers."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID
from datetime import UTC, datetime
from typing import Any, Iterable

from daylily_tapdb.external_references import (
    ExternalIdentifierTarget,
    ExternalLinkSpec,
    ExternalReferenceService,
    TapDBObjectTarget,
)

ASSERTION_AUTHORITY = "bloom.atlas-references"
DEWEY_ASSERTION_AUTHORITY = "bloom.dewey-references"
PROVENANCE_CONTRACT = "bloom.atlas-reference/v1"
_KIND_RE = re.compile(r"[^a-z0-9._-]+")
_ATLAS_OBJECT_KINDS = {
    "trf_euid", "order_euid", "order_test_euid", "shipment_euid",
    "atlas_trf_euid", "atlas_test_euid",
    "atlas_trf", "atlas_test", "atlas_testkit", "atlas_shipment",
    "atlas_patient", "atlas_collection_event", "atlas_organization_site",
    "atlas_test_fulfillment_item", "atlas_test_process_item",
}
_ATLAS_OPAQUE_KINDS = {"patient_id", "kit_barcode"}
_ATLAS_OWNER_COORDINATES = {
    "trf_euid": ("ordering", "order"),
    "order_euid": ("ordering", "order"),
    "order_test_euid": ("ordering", "order-test"),
    "shipment_euid": ("logistics", "shipment"),
    "atlas_trf_euid": ("ordering", "order"),
    "atlas_test_euid": ("ordering", "order-test"),
    "atlas_trf": ("ordering", "order"),
    "atlas_test": ("ordering", "order-test"),
    "atlas_testkit": ("logistics", "order_test-kit"),
    "atlas_shipment": ("logistics", "shipment"),
    "atlas_patient": ("subjects", "subject-ref"),
    "atlas_collection_event": ("people", "collection-event"),
    "atlas_organization_site": ("core", "site"),
    "atlas_test_fulfillment_item": ("fulfillment", "fulfillment-slot"),
    "atlas_test_process_item": ("fulfillment", "fulfillment-slot"),
}


def require_atlas_owner_kind(kind: str, body: dict[str, Any]) -> None:
    """Corroborate Bloom's reference role with Atlas's native template."""
    expected = _ATLAS_OWNER_COORDINATES.get(kind)
    if expected is None:
        raise ValueError(f"Atlas reference has no owner-kind contract: {kind}")
    observed = tuple(body.get(key) for key in ("category", "type", "subtype", "version"))
    if observed != (*expected, "generic", "1.0"):
        raise ValueError(f"Atlas owner kind differs from Bloom reference: {kind}")


def canonical_kind(reference_type: Any) -> str:
    value = _KIND_RE.sub("_", str(reference_type or "").strip().lower()).strip("_.-")
    if not value or len(value) > 128:
        raise ValueError("Atlas reference_type cannot form a canonical XRF kind")
    return value


def canonical_target(properties: dict[str, Any]) -> TapDBObjectTarget | ExternalIdentifierTarget:
    if str(properties.get("provider") or "").strip() != "atlas":
        raise ValueError("Atlas reference provider must be exact: atlas")
    value = str(properties.get("reference_value") or "")
    if not value or value != value.strip():
        raise ValueError("Atlas reference_value must be exact and non-empty")
    kind = canonical_kind(properties.get("reference_type"))
    tenant_text = str(properties.get("atlas_tenant_id") or "").strip()
    if kind in _ATLAS_OBJECT_KINDS:
        if properties.get("atlas_native_record_type") != "instance":
            raise ValueError("Atlas target requires an exact native object receipt")
        native_scope = properties.get("atlas_native_scope")
        native_tenant_text = properties.get("atlas_native_tenant_id")
        if native_scope == "global":
            if native_tenant_text is not None:
                raise ValueError("Global Atlas native target cannot declare a tenant")
            native_tenant = None
        elif native_scope == "tenant":
            if not isinstance(native_tenant_text, str):
                raise ValueError("Tenant Atlas native target requires owner tenant UUID")
            native_tenant = UUID(native_tenant_text)
            if str(native_tenant) != native_tenant_text:
                raise ValueError("Atlas native tenant UUID is not canonical")
        else:
            raise ValueError("Atlas native scope must be owner-confirmed")
        return TapDBObjectTarget(
            target_service_id="atlas",
            target_object_euid=value,
            target_tenant_id=native_tenant,
        )
    if kind in _ATLAS_OPAQUE_KINDS:
        tenant = UUID(tenant_text) if tenant_text else None
        if any(key in properties for key in (
            "atlas_native_record_type", "atlas_native_scope", "atlas_native_tenant_id"
        )):
            raise ValueError("Opaque Atlas identifier cannot carry native object scope")
        if tenant is None:
            raise ValueError("Atlas opaque reference requires explicit atlas_tenant_id")
        return ExternalIdentifierTarget(
            namespace=f"atlas.{tenant}",
            kind=kind,
            value=value,
            scope="public_global",
        )
    raise ValueError(f"Atlas reference type has no reviewed target contract: {kind}")


def relationship_type(properties: dict[str, Any]) -> str:
    return f"references_atlas_{canonical_kind(properties.get('reference_type'))}"


def provenance(
    properties: dict[str, Any], *, evidence: dict[str, Any] | None = None
) -> str:
    payload: dict[str, Any] = {
        "contract": PROVENANCE_CONTRACT,
        "properties": dict(properties),
    }
    if evidence:
        payload["evidence"] = evidence
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(rendered) > 2048:
        raise ValueError("Atlas assertion provenance exceeds TapDB's 2048 byte bound")
    return rendered


def _payload_from_item(item: dict[str, Any]) -> dict[str, Any]:
    raw = str(item.get("assertion_provenance") or "")
    try:
        document = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Atlas assertion provenance is not canonical JSON") from exc
    if (
        not isinstance(document, dict)
        or document.get("contract") != PROVENANCE_CONTRACT
        or not isinstance(document.get("properties"), dict)
    ):
        raise ValueError("Atlas assertion provenance contract is invalid")
    properties = dict(document["properties"])
    if (
        str(properties.get("provider") or "") != "atlas"
    ):
        raise ValueError("Atlas assertion provenance diverges from its canonical XRF")
    target = canonical_target(properties)
    if isinstance(target, TapDBObjectTarget):
        matched = (
            item.get("target_type") == "tapdb_object"
            and item.get("target_service_id") == target.target_service_id
            and item.get("target_object_euid") == target.target_object_euid
            and item.get("target_tenant_id")
            == (str(target.target_tenant_id) if target.target_tenant_id else None)
        )
    else:
        matched = (
            item.get("target_type") == "opaque"
            and item.get("namespace") == target.namespace
            and item.get("kind") == target.kind
            and item.get("value") == target.value
            and item.get("scope") == target.scope
        )
    if not matched:
        raise ValueError("Atlas assertion target diverges from its canonical XRF")
    return properties


def list_reference_payloads(session: Any, source: Any) -> list[dict[str, Any]]:
    page = ExternalReferenceService(session).list_for_source(
        source,
        assertion_authority=ASSERTION_AUTHORITY,
        limit=100,
    )
    if page["page"]["next_cursor"] is not None:
        raise RuntimeError("one Bloom object exceeds the reviewed 100-reference bound")
    return [_payload_from_item(item) for item in page["items"]]


def _item_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    if item.get("target_type") == "tapdb_object":
        return (
            "tapdb_object", str(item["target_service_id"]),
            str(item["target_object_euid"]), "", str(item["relationship_type"]),
        )
    if item.get("target_type") == "opaque":
        return (
            "opaque", str(item["namespace"]), str(item["kind"]),
            str(item["value"]), str(item["relationship_type"]),
        )
    raise ValueError("Unsupported external reference target type")


def replace_references(
    session: Any,
    source: Any,
    properties: Iterable[dict[str, Any]],
    *,
    asserted_at: datetime | None = None,
) -> tuple[Any, ...]:
    service = ExternalReferenceService(session)
    current = service.list_for_source(
        source,
        assertion_authority=ASSERTION_AUTHORITY,
        limit=100,
    )
    if current["page"]["next_cursor"] is not None:
        raise RuntimeError("one Bloom object exceeds the reviewed 100-reference bound")
    if any(
        item.get("target_type") == "opaque"
        and item.get("kind") in _ATLAS_OBJECT_KINDS
        for item in current["items"]
    ):
        raise RuntimeError("historical opaque Atlas owner reference requires bounded repair")
    existing = {_item_key(item): item for item in current["items"]}
    desired: list[ExternalLinkSpec] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    stamp = asserted_at or datetime.now(UTC)
    owner_client = None
    owner_receipts: dict[str, dict[str, Any]] = {}
    for raw_item in properties:
        item = dict(raw_item)
        kind = canonical_kind(item.get("reference_type"))
        if kind in _ATLAS_OBJECT_KINDS:
            value = str(item.get("reference_value") or "")
            if owner_client is None:
                from bloom_lims.integrations.atlas.service import AtlasService

                owner_client = AtlasService().owner_client
            body = owner_receipts.get(value)
            if body is None:
                body = owner_client.require_native_object(value)
                owner_receipts[value] = body
            require_atlas_owner_kind(kind, body)
            item["atlas_native_record_type"] = body["record_type"]
            item["atlas_native_scope"] = (
                "tenant" if body["tenant_id"] is not None else "global"
            )
            item["atlas_native_tenant_id"] = body["tenant_id"]
        target = canonical_target(item)
        relation = relationship_type(item)
        if isinstance(target, TapDBObjectTarget):
            key = ("tapdb_object", target.target_service_id, target.target_object_euid, "", relation)
        else:
            key = ("opaque", target.namespace, target.kind, target.value, relation)
        if key in seen:
            raise ValueError("desired Atlas references contain a duplicate")
        seen.add(key)
        prior = existing.get(key)
        desired_provenance = provenance(item)
        identical_replay = prior is not None and _payload_from_item(prior) == dict(item)
        if prior is not None and not identical_replay:
            service.detach(
                source,
                target,
                relationship_type=relation,
                assertion_authority=ASSERTION_AUTHORITY,
                deactivated_at=stamp,
                deactivation_provenance=json.dumps(
                    {
                        "contract": PROVENANCE_CONTRACT,
                        "operation": "replace_changed_context",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        desired.append(
            ExternalLinkSpec(
                target=target,
                relationship_type=relation,
                assertion_authority=ASSERTION_AUTHORITY,
                asserted_at=(
                    datetime.fromisoformat(str(prior["asserted_at"]))
                    if identical_replay
                    else stamp
                ),
                assertion_provenance=(
                    str(prior["assertion_provenance"])
                    if identical_replay
                    else desired_provenance
                ),
            )
        )
    return service.reconcile(
        source,
        ASSERTION_AUTHORITY,
        desired,
        deactivated_at=stamp,
        deactivation_provenance=json.dumps(
            {"contract": PROVENANCE_CONTRACT, "operation": "replace"},
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def replace_reference_types(
    session: Any,
    source: Any,
    properties: Iterable[dict[str, Any]],
    *,
    managed_reference_types: Iterable[str],
) -> tuple[Any, ...]:
    """Replace selected Atlas kinds while preserving every other active kind."""

    managed = {canonical_kind(item) for item in managed_reference_types}
    retained = [
        payload
        for payload in list_reference_payloads(session, source)
        if canonical_kind(payload.get("reference_type")) not in managed
    ]
    return replace_references(session, source, [*retained, *properties])


def replace_dewey_quant_reference(
    session: Any, source: Any, quant_artifact_euid: str | None
) -> tuple[Any, ...]:
    """Reconcile Bloom's one native Dewey quant-artifact reference."""

    value = str(quant_artifact_euid or "")
    if value != value.strip():
        raise ValueError("Dewey quant artifact reference must be exact")
    service = ExternalReferenceService(session)
    current = service.list_for_source(
        source,
        assertion_authority=DEWEY_ASSERTION_AUTHORITY,
        limit=2,
    )
    if current["page"]["next_cursor"] is not None or len(current["items"]) > 1:
        raise RuntimeError("one Bloom QC record has multiple Dewey quant references")
    prior = current["items"][0] if current["items"] else None
    if prior is not None and prior.get("target_type") == "opaque":
        raise RuntimeError("historical opaque Dewey artifact reference requires bounded repair")
    desired: list[ExternalLinkSpec] = []
    if value:
        same_prior = (
            prior is not None
            and prior.get("target_type") == "tapdb_object"
            and prior.get("target_service_id") == "dewey"
            and prior.get("target_object_euid") == value
            and prior.get("relationship_type") == "uses_quant_artifact"
        )
        desired.append(
            ExternalLinkSpec(
                target=TapDBObjectTarget(
                    target_service_id="dewey",
                    target_object_euid=value,
                ),
                relationship_type="uses_quant_artifact",
                assertion_authority=DEWEY_ASSERTION_AUTHORITY,
                asserted_at=(
                    datetime.fromisoformat(str(prior["asserted_at"]))
                    if same_prior
                    else datetime.now(UTC)
                ),
                assertion_provenance=(
                    str(prior["assertion_provenance"])
                    if same_prior
                    else json.dumps(
                        {
                            "contract": "bloom.dewey-reference/v1",
                            "quant_artifact_euid": value,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
            )
        )
    return service.reconcile(
        source,
        DEWEY_ASSERTION_AUTHORITY,
        desired,
        deactivated_at=datetime.now(UTC),
        deactivation_provenance=json.dumps(
            {"contract": "bloom.dewey-reference/v1", "operation": "replace"},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def legacy_evidence_summary(
    euids: list[str], fingerprints: list[str]
) -> dict[str, Any]:
    rendered = json.dumps(
        sorted(zip(euids, fingerprints, strict=True)),
        separators=(",", ":"),
    ).encode()
    return {
        "legacy_bgx_count": len(euids),
        "legacy_bgx_sha256": hashlib.sha256(rendered).hexdigest(),
    }
