"""Atomic, tenant-qualified Atlas tube requests and immutable replay receipts.

No allocation in this module represents biological material or collection. Native
TapDB claims allocate identities; the caller's transaction owns every write.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID

from daylily_tapdb.advisory_locks import acquire_transaction_advisory_lock
from daylily_tapdb.external_references import (
    ExternalIdentifierTarget,
    ExternalLinkSpec,
    ExternalReferenceService,
    TapDBObjectTarget,
)
from daylily_tapdb.factory import IdentityClaimOutcome, IdentityScope, InstanceFactory
from daylily_tapdb.templates import TemplateManager
from sqlalchemy import or_

from bloom_lims.schemas.beta_lab import (
    BetaTubeIdentifier,
    BetaTubeIdentityResponse,
    BetaTubeRequestResponse,
    BetaTubeResponse,
)
from bloom_lims.template_identity import template_semantic_category


class TubeRequestConflict(ValueError):
    """The original request or physical identity cannot safely be changed."""


class TubeRequestNotFound(ValueError):
    """No visible receipt exists for this tenant and exact key."""


def tube_request_key(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise ValueError("Idempotency-Key must contain 1 through 200 characters")
    if re.fullmatch(r"[A-Za-z0-9._:-]+", value) is None:
        raise ValueError("Idempotency-Key must use only ASCII letters, digits, '.', '_', ':' or '-'")
    return value


def tube_request_digest(operation: str, payload) -> tuple[str, dict]:
    request = payload.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    encoded = json.dumps(
        {"operation": operation, "payload": request},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > 65536:
        raise ValueError("Tube request exceeds the 64 KiB canonical request limit")
    return hashlib.sha256(encoded).hexdigest(), request


class _BetaLabTubeRequestsMixin:
    TUBE_REQUEST_TEMPLATE = "data/accession-request/tube/1.0"
    TUBE_IDENTITY_TEMPLATE = "data/accession-identity/tube/1.0"
    TUBE_CONTAINER_RELATIONSHIP = "bloom_tube_container"
    TUBE_IDENTIFIER_RELATIONSHIP = "bloom_tube_identifier"
    TUBE_IDENTIFIER_AUTHORITY = "bloom.atlas-tube-registration"
    TUBE_REQUEST_RESULT_RELATIONSHIP = "bloom_tube_request_result"

    def _tube_factory(self):
        return InstanceFactory(TemplateManager(), domain_code=self.bdb.domain_code)

    def _require_tube_tenant_scope(self, tenant):
        context = self.bdb._conn.transaction_context()
        allowed = {str(value) for value in context.additional_tenant_ids}
        if context.tenant_id is not None:
            allowed.add(str(context.tenant_id))
        if str(tenant) not in allowed:
            raise PermissionError("Atlas registration tenant is outside Bloom's explicitly configured native tenant scope")

    @staticmethod
    def _tube_request_identity(request_key: str, tenant_id: UUID) -> str:
        return "bloom.atlas-tube-request/v1:" + hashlib.sha256(json.dumps([str(tenant_id), request_key], separators=(",", ":")).encode()).hexdigest()

    def _require_exact_tube_template(self, code: str):
        parts = code.split("/")
        if len(parts) != 4 or any(not part or part != part.strip() or "*" in part for part in parts):
            raise ValueError("An exact tube template code is required")
        templates = self.bobj.query_template_by_component_v2(*parts)
        if len(templates) != 1:
            raise ValueError("Exact tube template not found or ambiguous")
        template = templates[0]
        if template.is_deleted or template_semantic_category(template) != "container" or template.type != "tube":
            raise ValueError("Requested template must identify a tube container")
        return template

    def _require_tenant_tube(self, container_euid: str, tenant_id: UUID):
        model = self.bdb.Base.classes.generic_instance
        tube = self.bdb.session.query(model).filter(
            model.euid == container_euid,
            model.domain_code == self.bdb.domain_code,
            model.issuer_app_code == self.bdb.owner_repo_name,
            model.is_deleted.is_(False),
        ).one_or_none()
        if tube is None:
            raise TubeRequestNotFound("Tube not found in the requested tenant")
        self._require_exact_tube_template(self._tube_template_code(tube))
        contexts = self._atlas_tenant_contexts(tube)
        if contexts != {str(tenant_id)}:
            raise TubeRequestConflict("Tube Atlas ownership context is absent or conflicts with its tenant")
        return tube

    @staticmethod
    def _tube_template_code(tube) -> str:
        return f"{tube.category}/{tube.type}/{tube.subtype}/{tube.version}"

    def _tube_request_record(self, request_key: str, tenant_id: UUID):
        model = self.bdb.Base.classes.generic_instance
        return self.bdb.session.query(model).filter(
            model.identity_key == self._tube_request_identity(request_key, tenant_id),
            model.tenant_id == tenant_id,
            model.issuer_app_code == self.bdb.owner_repo_name,
            model.domain_code == self.bdb.domain_code,
            model.category == "data", model.type == "accession-request",
            model.subtype == "tube", model.version == "1.0",
        ).one_or_none()

    def _completed_tube_receipt(self, record, request_key: str, tenant_id: UUID, digest=None):
        props = self._props(record)
        if record.is_deleted or record.tenant_id != tenant_id or props.get("request_key") != request_key or props.get("atlas_tenant_id") != str(tenant_id):
            raise TubeRequestConflict("Tube request receipt identity is inconsistent")
        if digest is not None and props.get("request_digest") != digest:
            raise TubeRequestConflict("Idempotency-Key was already used for a different tube request")
        if props.get("state") != "completed" or not isinstance(props.get("response"), dict):
            raise TubeRequestConflict("Tube request remains unresolved; reconcile the original request")
        return BetaTubeRequestResponse.model_validate({
            key: copy.deepcopy(props[key]) for key in (
                "request_key", "request_digest", "atlas_tenant_id", "operation", "state", "request_payload", "response"
            )
        }).model_dump(mode="json")

    def _reject_unreceipted_tube_key(self, key, tenant):
        """Historical key-only writes cannot prove replay equivalence; never duplicate them."""
        model = self.bdb.Base.classes.generic_instance
        props = model.json_addl["properties"]
        existing = self.bdb.session.query(model).filter(
            model.domain_code == self.bdb.domain_code,
            model.issuer_app_code == self.bdb.owner_repo_name,
            model.type == "tube",
            props["idempotency_key"].as_string() == key,
            or_(props["atlas_registration_tenant_id"].as_string() == str(tenant),
                props["atlas_registration_tenant_id"].as_string().is_(None)),
        ).limit(1).first()
        if existing is not None:
            raise TubeRequestConflict("Historical tube request has no digest receipt; reconcile its existing identity")

    def get_tube_request(self, *, request_key: str, atlas_tenant_id: str):
        key, tenant = tube_request_key(request_key), UUID(atlas_tenant_id)
        self._require_tube_tenant_scope(tenant)
        record = self._tube_request_record(key, tenant)
        if record is None:
            raise TubeRequestNotFound("Tube request not found for the requested tenant")
        # Reconciliation is an immutable receipt read, never a new create.
        return self._completed_tube_receipt(record, key, tenant)

    def _tube_owner_target(self, tube):
        return TapDBObjectTarget(target_service_id="bloom", target_object_euid=tube.euid,
                                 target_tenant_id=tube.tenant_id, target_object_kind="container")

    def _attach_tube_reference(self, source, target, relationship, digest):
        return ExternalReferenceService(self.bdb.session).attach(source, ExternalLinkSpec(
            target=target, relationship_type=relationship,
            assertion_authority=self.TUBE_IDENTIFIER_AUTHORITY, asserted_at=datetime.now(UTC),
            assertion_provenance="bloom.atlas-tube-request/v1:sha256:" + digest,
        ))

    def _require_tube_assertion(self, euid, tenant):
        model = self.bdb.Base.classes.generic_instance
        source = self.bdb.session.query(model).filter(
            model.euid == euid, model.tenant_id == tenant, model.is_deleted.is_(False),
            model.domain_code == self.bdb.domain_code, model.issuer_app_code == self.bdb.owner_repo_name,
            model.category == "data", model.type == "accession-identity",
            model.subtype == "tube", model.version == "1.0",
        ).one_or_none()
        if source is None:
            raise TubeRequestConflict("Physical identifier source is not an authorized tube assertion")
        return source

    def _tube_from_assertion(self, source, tenant):
        links = ExternalReferenceService(self.bdb.session).list_for_source(
            source, relationship_type=self.TUBE_CONTAINER_RELATIONSHIP, limit=2,
        )
        if links["page"]["next_cursor"] or len(links["items"]) != 1:
            raise TubeRequestConflict("Physical identifier must have exactly one active container binding")
        link = links["items"][0]
        if (link["target_type"] != "tapdb_object" or link["target_service_id"] != "bloom"
                or link["assertion_authority"] != self.TUBE_IDENTIFIER_AUTHORITY
                or link.get("target_object_kind") != "container"):
            raise TubeRequestConflict("Physical identifier container owner evidence is inconsistent")
        tube = self._require_tenant_tube(link["target_object_euid"], tenant)
        actual_tenant = str(tube.tenant_id) if tube.tenant_id is not None else None
        if link.get("target_tenant_id") != actual_tenant:
            raise TubeRequestConflict("Physical identifier container native tenant has changed")
        return tube

    def _tube_identifier_evidence(self, source, tenant):
        references = ExternalReferenceService(self.bdb.session)
        links = references.list_for_source(source, relationship_type=self.TUBE_IDENTIFIER_RELATIONSHIP, limit=2)
        if links["page"]["next_cursor"] or len(links["items"]) != 1:
            raise TubeRequestConflict("Physical tube assertion must have exactly one active identifier")
        link = links["items"][0]
        if (link["target_type"] != "opaque" or link["scope"] != "tenant"
                or link["assertion_authority"] != self.TUBE_IDENTIFIER_AUTHORITY):
            raise TubeRequestConflict("Tube has conflicting physical identifier assertions")
        identifier = BetaTubeIdentifier(tenant_id=str(tenant), **{key: link[key] for key in ("namespace", "kind", "value")})
        if identifier.value != link["value"]:
            raise TubeRequestConflict("Stored tube identifier is not canonical")
        target = ExternalIdentifierTarget(namespace=identifier.namespace, kind=identifier.kind,
                                          value=identifier.value, scope="tenant", tenant_id=tenant)
        matches = references.find_sources(target, relationship_type=self.TUBE_IDENTIFIER_RELATIONSHIP, limit=2)
        if (matches["page"]["next_cursor"] or len(matches["items"]) != 1
                or matches["items"][0]["source"]["euid"] != source.euid):
            raise TubeRequestConflict("Physical tube identifier is ambiguous")
        return {"identifier": identifier.model_dump(mode="json"),
                "identifier_reference_euid": link["external_reference_euid"],
                "identifier_lineage_euid": link["lineage_euid"]}

    def get_tube_identity(self, *, container_euid: str, atlas_tenant_id: str):
        tenant = UUID(atlas_tenant_id)
        self._require_tube_tenant_scope(tenant)
        tube = self._require_tenant_tube(container_euid, tenant)
        references = ExternalReferenceService(self.bdb.session)
        sources = references.find_sources(self._tube_owner_target(tube),
                                          relationship_type=self.TUBE_CONTAINER_RELATIONSHIP, limit=100)
        if sources["page"]["next_cursor"]:
            raise TubeRequestConflict("Tube identifier evidence exceeds the complete response limit")
        identifiers = []
        for item in sources["items"]:
            source = self._require_tube_assertion(item["source"]["euid"], tenant)
            if self._tube_from_assertion(source, tenant).euid != tube.euid:
                raise TubeRequestConflict("Tube identifier assertion has conflicting container targets")
            identifiers.append(self._tube_identifier_evidence(source, tenant))
        return BetaTubeIdentityResponse(
            tenant_id=str(tube.tenant_id) if tube.tenant_id is not None else None,
            atlas_tenant_id=str(tenant), container_euid=tube.euid,
            container_template_code=self._tube_template_code(tube), identifiers=identifiers,
        ).model_dump(mode="json")

    def create_empty_tube(self, *, payload, idempotency_key: str):
        return self._execute_tube_request(payload=payload, idempotency_key=idempotency_key, operation="create")

    def register_existing_tube(self, *, payload, idempotency_key: str):
        return self._execute_tube_request(payload=payload, idempotency_key=idempotency_key, operation="register-existing")

    def _execute_tube_request(self, *, payload, idempotency_key: str, operation: str):
        key = tube_request_key(idempotency_key)
        tenant = UUID(payload.atlas_context.atlas_tenant_id)
        self._require_tube_tenant_scope(tenant)
        self._validate_registration_properties(payload.properties)
        digest, request = tube_request_digest(operation, payload)
        session = self.bdb.session
        try:
            if not session.in_transaction():
                session.begin()
            acquire_transaction_advisory_lock(session, "bloom.tube-request/v1", tenant, key, timeout_seconds=10)
            existing = self._tube_request_record(key, tenant)
            if existing is not None:
                response = self._completed_tube_receipt(existing, key, tenant, digest)["response"]
                session.commit()
                return response
            self._reject_unreceipted_tube_key(key, tenant)
            self._require_exact_tube_template(payload.container_template_code)
            factory = self._tube_factory()
            native_tenant = self.bdb._conn.tenant_id
            native_tenant = UUID(str(native_tenant)) if native_tenant is not None else None
            native_scope = IdentityScope.TENANT if native_tenant is not None else IdentityScope.GLOBAL
            claim = factory.claim_instance_by_identity(
                session, template_code=self.TUBE_REQUEST_TEMPLATE,
                identity_key=self._tube_request_identity(key, tenant), name="Atlas tube request",
                scope=IdentityScope.TENANT, tenant_id=tenant,
                properties={"request_key": key, "request_digest": digest, "atlas_tenant_id": str(tenant),
                            "operation": operation, "request_payload": request, "state": "pending",
                            "requested_by": self.bdb.app_username, "requested_at": datetime.now(UTC).isoformat()},
                command_evidence={"contract": "bloom.atlas-tube-request/v1"}, create_children=False,
            )
            if claim.outcome is not IdentityClaimOutcome.CREATED:
                response = self._completed_tube_receipt(claim.instance, key, tenant, digest)["response"]
                session.commit()
                return response
            receipt = claim.instance
            identifier = getattr(payload, "identifier", None)
            target, evidence, tube = None, None, None
            references = ExternalReferenceService(session)
            if operation == "register-existing":
                if identifier is None or identifier.tenant_id != str(tenant):
                    raise ValueError("A qualified matching tenant identifier is required")
                target = ExternalIdentifierTarget(
                    namespace=identifier.namespace, kind=identifier.kind, value=identifier.value,
                    scope="tenant", tenant_id=tenant,
                )
                acquire_transaction_advisory_lock(
                    session, "bloom.physical-tube/v1", tenant, target.identity_key, timeout_seconds=10,
                )
                matches = references.find_sources(target, relationship_type=self.TUBE_IDENTIFIER_RELATIONSHIP, limit=2)
                if matches["page"]["next_cursor"] or len(matches["items"]) > 1:
                    raise TubeRequestConflict("Physical tube identifier is ambiguous; explicit resolution is required")
                if matches["items"]:
                    match = matches["items"][0]
                    evidence = match["matched_external_reference"]
                    if evidence["assertion_authority"] != self.TUBE_IDENTIFIER_AUTHORITY:
                        raise TubeRequestConflict("Physical tube identifier belongs to a different assertion authority")
                    source = self._require_tube_assertion(match["source"]["euid"], tenant)
                    verified = self._tube_identifier_evidence(source, tenant)
                    if verified["identifier"] != identifier.model_dump(mode="json"):
                        raise TubeRequestConflict("Physical tube assertion differs from requested identifier")
                    tube = self._tube_from_assertion(source, tenant)
                    if self._tube_template_code(tube) != payload.container_template_code:
                        raise TubeRequestConflict("Matching physical tube has a different exact template")
            created = tube is None
            if created:
                identity = ("bloom.physical-tube/v1:" + str(tenant) + ":" + target.identity_key if target is not None
                            else "bloom.allocated-tube/v1:" + self._tube_request_identity(key, tenant))
                tube_claim = factory.claim_instance_by_identity(
                    session, template_code=payload.container_template_code, identity_key=identity,
                    name=self._explicit_tube_name(payload.properties) or "Atlas tube",
                    scope=native_scope, tenant_id=native_tenant,
                    properties={**payload.properties, "beta_kind": "atlas_tube", "idempotency_key": key,
                                "atlas_registration_tenant_id": str(tenant)},
                    command_evidence={"contract": "bloom.atlas-tube-request/v1", "request_digest": digest},
                    create_children=False,
                )
                if tube_claim.outcome is not IdentityClaimOutcome.CREATED:
                    raise TubeRequestConflict("Tube identity exists without a complete matching assertion or receipt")
                tube = tube_claim.instance
                tube.bstatus = payload.status
                # Existing Atlas objects may be referenced; no material or collection is allocated.
                context = payload.atlas_context.model_dump()
                self._replace_container_entity_references(tube, atlas_context=context)
                self._replace_fulfillment_item_references(tube, atlas_context=context)
                if target is not None:
                    identity_claim = factory.claim_instance_by_identity(
                        session, template_code=self.TUBE_IDENTITY_TEMPLATE,
                        identity_key="bloom.tube-identifier/v1:" + target.identity_key,
                        name="Physical tube identifier assertion", scope=IdentityScope.TENANT, tenant_id=tenant,
                        properties={"asserted_by": self.bdb.app_username, "asserted_at": datetime.now(UTC).isoformat()},
                        command_evidence={"contract": "bloom.atlas-tube-request/v1", "request_digest": digest},
                        create_children=False,
                    )
                    if identity_claim.outcome is not IdentityClaimOutcome.CREATED:
                        raise TubeRequestConflict("Physical tube assertion exists without a complete matching binding")
                    source = identity_claim.instance
                    assertion = self._attach_tube_reference(source, target, self.TUBE_IDENTIFIER_RELATIONSHIP, digest)
                    self._attach_tube_reference(source, self._tube_owner_target(tube), self.TUBE_CONTAINER_RELATIONSHIP, digest)
                    evidence = {"external_reference_euid": assertion.reference.euid, "lineage_euid": assertion.lineage.euid}
            session.flush()
            # Native reference + lineage is authoritative; response is an immutable receipt snapshot.
            self._attach_tube_reference(receipt, self._tube_owner_target(tube), self.TUBE_REQUEST_RESULT_RELATIONSHIP, digest)
            response = BetaTubeResponse.model_validate({
                **self._tube_response(tube, created=created), "request_key": key, "idempotency_key": key,
                "request_digest": digest, "operation": operation, "atlas_tenant_id": str(tenant),
                "tenant_id": str(tube.tenant_id) if tube.tenant_id is not None else None,
                "container_template_code": self._tube_template_code(tube),
                "identifier": identifier.model_dump() if identifier is not None else None,
                "identifier_reference_euid": evidence["external_reference_euid"] if evidence else None,
                "identifier_lineage_euid": evidence["lineage_euid"] if evidence else None,
            }).model_dump(mode="json")
            if operation == "create":
                self._record_action(
                    target_instance=tube, action_key="create_empty_tube",
                    captured_data={**payload.model_dump(mode="json"), "idempotency_key": key},
                    result={"status": "success", "container_euid": tube.euid},
                )
            self._write_props(receipt, {
                **self._props(receipt), "state": "completed", "response": copy.deepcopy(response),
                "completed_at": datetime.now(UTC).isoformat(),
            })
            session.commit()
            return response
        except Exception:
            session.rollback()
            raise
