"""Bloom's native TapDB external-reference contract for Atlas identifiers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Iterable

from daylily_tapdb.external_references import (
    ExternalIdentifierTarget,
    ExternalLinkSpec,
    ExternalReferenceService,
)

ASSERTION_AUTHORITY = "bloom.atlas-references"
DEWEY_ASSERTION_AUTHORITY = "bloom.dewey-references"
PROVENANCE_CONTRACT = "bloom.atlas-reference/v1"
_KIND_RE = re.compile(r"[^a-z0-9._-]+")


def canonical_kind(reference_type: Any) -> str:
    value = _KIND_RE.sub("_", str(reference_type or "").strip().lower()).strip("_.-")
    if not value or len(value) > 128:
        raise ValueError("Atlas reference_type cannot form a canonical XRF kind")
    return value


def canonical_target(properties: dict[str, Any]) -> ExternalIdentifierTarget:
    if str(properties.get("provider") or "").strip() != "atlas":
        raise ValueError("Atlas reference provider must be exact: atlas")
    value = str(properties.get("reference_value") or "")
    if not value or value != value.strip():
        raise ValueError("Atlas reference_value must be exact and non-empty")
    tenant = str(properties.get("atlas_tenant_id") or "").strip().lower()
    if tenant:
        tenant = canonical_kind(tenant)
    return ExternalIdentifierTarget(
        namespace=f"atlas.{tenant}" if tenant else "atlas",
        kind=canonical_kind(properties.get("reference_type")),
        value=value,
        scope="public_global",
    )


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
    target_value = str(item.get("value") or "")
    target_kind = str(item.get("kind") or "")
    target_namespace = str(item.get("namespace") or "")
    if (
        str(properties.get("provider") or "") != "atlas"
        or canonical_kind(properties.get("reference_type")) != target_kind
        or str(properties.get("reference_value") or "") != target_value
    ):
        raise ValueError("Atlas assertion provenance diverges from its canonical XRF")
    tenant = (
        target_namespace.removeprefix("atlas.") if target_namespace != "atlas" else ""
    )
    if tenant and canonical_kind(properties.get("atlas_tenant_id")) != tenant:
        raise ValueError("Atlas assertion tenant diverges from its canonical XRF")
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


def _item_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item["namespace"]),
        str(item["kind"]),
        str(item["value"]),
        str(item["relationship_type"]),
    )


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
    existing = {_item_key(item): item for item in current["items"]}
    desired: list[ExternalLinkSpec] = []
    seen: set[tuple[str, str, str, str]] = set()
    stamp = asserted_at or datetime.now(UTC)
    for item in properties:
        target = canonical_target(item)
        relation = relationship_type(item)
        key = (target.namespace, target.kind, target.value, relation)
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
    desired: list[ExternalLinkSpec] = []
    if value:
        same_prior = (
            prior is not None
            and prior.get("target_type") == "opaque"
            and prior.get("namespace") == "dewey"
            and prior.get("kind") == "quant_artifact"
            and prior.get("value") == value
            and prior.get("relationship_type") == "uses_quant_artifact"
        )
        desired.append(
            ExternalLinkSpec(
                target=ExternalIdentifierTarget(
                    namespace="dewey",
                    kind="quant_artifact",
                    value=value,
                    scope="public_global",
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
