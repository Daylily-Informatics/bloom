"""Domain service for external Atlas-driven specimen operations."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3, get_child_lineages, get_parent_lineages
from bloom_lims.integrations.atlas.service import AtlasDependencyError, AtlasService
from bloom_lims.schemas.external_specimens import (
    AtlasReferences,
    ExternalSpecimenCreateRequest,
    ExternalSpecimenResponse,
    ExternalSpecimenUpdateRequest,
)


class ExternalSpecimenService:
    """Creates, updates, and queries external specimens in Bloom."""

    EXTERNAL_REFERENCE_TEMPLATE_CODE = "generic/generic/external_object_link/1.0"
    EXTERNAL_REFERENCE_RELATIONSHIP = "has_external_reference"
    _ATLAS_REFERENCE_FIELDS = (
        "trf_euid",
        "patient_id",
        "shipment_number",
        "kit_barcode",
        "atlas_tenant_id",
        "atlas_trf_euid",
        "atlas_test_euid",
    )
    _REFERENCE_QUERY_SPECS: dict[str, dict[str, Any]] = {
        "trf_euid": {
            "reference_types": ("trf_euid",),
            "value_field": "reference_value",
        },
        "patient_id": {
            "reference_types": ("patient_id",),
            "value_field": "reference_value",
        },
        "shipment_number": {
            "reference_types": ("shipment_number",),
            "value_field": "reference_value",
        },
        "kit_barcode": {
            "reference_types": ("kit_barcode",),
            "value_field": "reference_value",
        },
        "atlas_tenant_id": {
            "reference_types": None,
            "value_field": "atlas_tenant_id",
        },
        "atlas_trf_euid": {
            "reference_types": ("atlas_trf_euid", "atlas_trf"),
            "value_field": "atlas_trf_euid",
        },
        "atlas_test_euid": {
            "reference_types": ("atlas_test_euid", "atlas_test"),
            "value_field": "atlas_test_euid",
        },
    }
    _REFERENCE_RESPONSE_NORMALIZATION: dict[str, tuple[str, str]] = {
        "atlas_trf": ("atlas_trf_euid", "atlas_trf_euid"),
        "atlas_test": ("atlas_test_euid", "atlas_test_euid"),
        "atlas_patient": ("atlas_patient_euid", "atlas_patient_euid"),
        "atlas_testkit": ("atlas_testkit_euid", "atlas_testkit_euid"),
        "atlas_shipment": ("atlas_shipment_euid", "atlas_shipment_euid"),
        "atlas_organization_site": (
            "atlas_organization_site_euid",
            "atlas_organization_site_euid",
        ),
        "atlas_collection_event": (
            "atlas_collection_event_euid",
            "atlas_collection_event_euid",
        ),
    }

    def __init__(self, *, app_username: str):
        self.bdb = BLOOMdb3(app_username=app_username)
        self.bobj = BloomObj(self.bdb)
        self._atlas: AtlasService | None = None

    def close(self) -> None:
        self.bdb.close()

    @property
    def atlas(self) -> AtlasService:
        if self._atlas is None:
            self._atlas = AtlasService()
        return self._atlas

    def create_specimen(
        self,
        *,
        payload: ExternalSpecimenCreateRequest,
        idempotency_key: str | None,
    ) -> ExternalSpecimenResponse:
        if idempotency_key:
            existing = self._find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return self._to_response(existing, created=False)

        atlas_refs, atlas_meta = self._validate_atlas_refs(
            payload.atlas_refs,
            container_euid=payload.container_euid,
        )

        try:
            specimen = self.bobj.create_instance_by_code(
                self._normalize_template_code(payload.specimen_template_code),
                {"json_addl": {"properties": payload.properties or {}}},
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        if specimen is None:
            raise ValueError("Failed to create specimen instance")

        if payload.specimen_name:
            specimen.name = payload.specimen_name
        specimen.bstatus = payload.status or specimen.bstatus

        specimen_props = self._props(specimen)
        specimen_props.update(payload.properties or {})
        if payload.specimen_name:
            specimen_props["name"] = payload.specimen_name
        if idempotency_key:
            specimen_props["external_idempotency_key"] = idempotency_key
        self._write_props(specimen, specimen_props)

        container = self._resolve_or_create_container(
            container_euid=payload.container_euid,
            container_template_code=payload.container_template_code,
            specimen_name=payload.specimen_name or specimen.name,
        )
        if container is not None:
            self._ensure_container_link(container.euid, specimen.euid)

        self._replace_external_references(
            specimen=specimen,
            atlas_refs=atlas_refs,
            atlas_validation=atlas_meta,
        )

        self.bdb.session.commit()
        return self._to_response(specimen, created=True)

    def get_specimen(self, specimen_euid: str) -> ExternalSpecimenResponse:
        specimen = self._safe_get_by_euid(specimen_euid)
        if specimen is None or specimen.is_deleted:
            raise ValueError(f"Specimen not found: {specimen_euid}")
        if specimen.category != "content":
            raise ValueError(f"EUID is not a specimen content object: {specimen_euid}")
        return self._to_response(specimen, created=True)

    def update_specimen(
        self,
        *,
        specimen_euid: str,
        payload: ExternalSpecimenUpdateRequest,
    ) -> ExternalSpecimenResponse:
        specimen = self._safe_get_by_euid(specimen_euid)
        if specimen is None or specimen.is_deleted:
            raise ValueError(f"Specimen not found: {specimen_euid}")
        if specimen.category != "content":
            raise ValueError(f"EUID is not a specimen content object: {specimen_euid}")

        if payload.specimen_name:
            specimen.name = payload.specimen_name
        if payload.status is not None:
            specimen.bstatus = payload.status

        specimen_props = self._props(specimen)
        if payload.properties:
            specimen_props.update(payload.properties)
        if payload.specimen_name:
            specimen_props["name"] = payload.specimen_name
        atlas_refs: dict[str, Any] | None = None
        atlas_meta: dict[str, Any] | None = None
        if payload.atlas_refs is not None:
            atlas_refs, atlas_meta = self._validate_atlas_refs(
                payload.atlas_refs,
                container_euid=payload.container_euid,
            )
        self._write_props(specimen, specimen_props)

        if payload.container_euid:
            container = self._safe_get_by_euid(payload.container_euid)
            if container is None or container.is_deleted:
                raise ValueError(f"Container not found: {payload.container_euid}")
            if container.category != "container":
                raise ValueError(f"EUID is not a container: {payload.container_euid}")
            self._ensure_container_link(container.euid, specimen.euid)

        if atlas_refs is not None:
            self._replace_external_references(
                specimen=specimen,
                atlas_refs=atlas_refs,
                atlas_validation=atlas_meta or {},
            )

        self.bdb.session.commit()
        return self._to_response(specimen, created=True)

    def find_by_references(
        self, refs: AtlasReferences
    ) -> list[ExternalSpecimenResponse]:
        filters = {
            field: getattr(refs, field) for field in self._ATLAS_REFERENCE_FIELDS
        }
        normalized_filters = {
            key: str(value).strip()
            for key, value in filters.items()
            if value is not None and str(value).strip()
        }
        if not normalized_filters:
            return []

        matching_parent_uids: set[int] | None = None
        for key, expected in normalized_filters.items():
            parent_uids = self._find_parent_uids_for_reference(
                reference_type=key,
                reference_value=expected,
            )
            if matching_parent_uids is None:
                matching_parent_uids = parent_uids
            else:
                matching_parent_uids &= parent_uids
            if not matching_parent_uids:
                return []

        if not matching_parent_uids:
            return []

        specimen_uids = self._expand_parent_uids_to_specimen_uids(matching_parent_uids)
        if not specimen_uids:
            return []

        rows = (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.uid.in_(
                    sorted(specimen_uids)
                ),
                self.bdb.Base.classes.generic_instance.category == "content",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
            )
            .order_by(self.bdb.Base.classes.generic_instance.euid.asc())
            .all()
        )
        return [self._to_response(row, created=True) for row in rows]

    def _resolve_or_create_container(
        self,
        *,
        container_euid: str | None,
        container_template_code: str,
        specimen_name: str,
    ):
        if container_euid:
            container = self._safe_get_by_euid(container_euid)
            if container is None or container.is_deleted:
                raise ValueError(f"Container not found: {container_euid}")
            if container.category != "container":
                raise ValueError(f"EUID is not a container: {container_euid}")
            return container

        try:
            container = self.bobj.create_instance_by_code(
                self._normalize_template_code(container_template_code),
                {"json_addl": {"properties": {"name": f"{specimen_name} container"}}},
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        if container is None:
            raise ValueError("Failed to create container for specimen")
        return container

    def _ensure_container_link(self, container_euid: str, specimen_euid: str) -> None:
        container = self._safe_get_by_euid(container_euid)
        specimen = self._safe_get_by_euid(specimen_euid)
        if container is None or specimen is None:
            return
        for lineage in get_parent_lineages(container):
            if lineage.is_deleted:
                continue
            if lineage.child_instance_uid == specimen.uid:
                return
        self.bobj.create_generic_instance_lineage_by_euids(
            container_euid,
            specimen_euid,
            relationship_type="contains",
        )

    def _find_by_idempotency_key(self, key: str):
        expected = str(key).strip()
        if not expected:
            return None
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "content",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "external_idempotency_key",
                )
                == expected,
            )
            .first()
        )

    def _validate_atlas_refs(
        self,
        refs: AtlasReferences,
        *,
        container_euid: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {
            "trf_euid": refs.trf_euid,
            "patient_id": refs.patient_id,
            "shipment_number": refs.shipment_number,
            "kit_barcode": refs.kit_barcode,
            "atlas_tenant_id": refs.atlas_tenant_id,
            "atlas_trf_euid": refs.atlas_trf_euid,
            "atlas_test_euid": refs.atlas_test_euid,
        }
        normalized = {
            key: str(value).strip()
            for key, value in payload.items()
            if value is not None and str(value).strip()
        }
        if not normalized:
            raise ValueError("At least one Atlas reference is required")

        validation_meta: dict[str, Any] = {}
        try:
            if container_euid and any(
                key in normalized
                for key in (
                    "trf_euid",
                    "patient_id",
                    "shipment_number",
                    "kit_barcode",
                )
            ):
                tenant_id = self.atlas.get_required_tenant_id()
                ctx_result = self.atlas.get_container_trf_context(
                    container_euid,
                    tenant_id=tenant_id,
                )
                self._validate_refs_against_container_context(
                    refs=normalized,
                    context=ctx_result.payload,
                )
                validation_meta["container_trf_context"] = {
                    "tenant_id": tenant_id,
                    "from_cache": ctx_result.from_cache,
                    "stale": ctx_result.stale,
                    "fetched_at": ctx_result.fetched_at.isoformat(),
                    "summary": self._build_container_context_summary(
                        ctx_result.payload
                    ),
                }

            if "trf_euid" in normalized:
                result = self.atlas.get_trf(normalized["trf_euid"])
                validation_meta["trf"] = {
                    "from_cache": result.from_cache,
                    "stale": result.stale,
                    "fetched_at": result.fetched_at.isoformat(),
                }
            if "patient_id" in normalized:
                result = self.atlas.get_patient(normalized["patient_id"])
                validation_meta["patient"] = {
                    "from_cache": result.from_cache,
                    "stale": result.stale,
                    "fetched_at": result.fetched_at.isoformat(),
                }
            if "shipment_number" in normalized:
                result = self.atlas.get_shipment(normalized["shipment_number"])
                validation_meta["shipment"] = {
                    "from_cache": result.from_cache,
                    "stale": result.stale,
                    "fetched_at": result.fetched_at.isoformat(),
                }
            if "kit_barcode" in normalized:
                result = self.atlas.get_testkit(normalized["kit_barcode"])
                validation_meta["testkit"] = {
                    "from_cache": result.from_cache,
                    "stale": result.stale,
                    "fetched_at": result.fetched_at.isoformat(),
                }
        except AtlasDependencyError as exc:
            raise RuntimeError(f"Atlas validation failed: {exc}") from exc

        return normalized, validation_meta

    def _validate_refs_against_container_context(
        self,
        *,
        refs: dict[str, str],
        context: dict[str, Any],
    ) -> None:
        trf = context.get("trf") if isinstance(context.get("trf"), dict) else {}
        patient = (
            context.get("patient") if isinstance(context.get("patient"), dict) else {}
        )
        links = context.get("links") if isinstance(context.get("links"), dict) else {}

        context_values = {
            "trf_euid": str(trf.get("trf_euid") or "").strip(),
            "patient_id": str(patient.get("patient_id") or "").strip(),
            "shipment_number": str(links.get("shipment_number") or "").strip(),
            "kit_barcode": str(links.get("testkit_barcode") or "").strip(),
        }

        for key, provided_value in refs.items():
            if key not in context_values:
                continue
            expected_value = context_values[key]
            if not expected_value:
                # Atlas may omit optional context links (for example testkit/package).
                continue
            if str(provided_value).strip() != expected_value:
                raise ValueError(
                    f"Atlas reference mismatch for '{key}': "
                    f"provided='{provided_value}' context='{expected_value}'"
                )

    def _build_container_context_summary(
        self, context: dict[str, Any]
    ) -> dict[str, Any]:
        trf = context.get("trf") if isinstance(context.get("trf"), dict) else {}
        patient = (
            context.get("patient") if isinstance(context.get("patient"), dict) else {}
        )
        links = context.get("links") if isinstance(context.get("links"), dict) else {}
        tests = context.get("tests") if isinstance(context.get("tests"), list) else []
        test_euids = []
        for entry in tests:
            if not isinstance(entry, dict):
                continue
            test_euid = str(entry.get("test_euid") or "").strip()
            if test_euid:
                test_euids.append(test_euid)

        return {
            "tenant_id": context.get("tenant_id"),
            "trf_euid": trf.get("trf_euid"),
            "patient_id": patient.get("patient_id"),
            "testkit_barcode": links.get("testkit_barcode"),
            "shipment_number": links.get("shipment_number"),
            "test_count": len(test_euids),
            "test_euids": test_euids,
        }

    def _to_response(self, specimen, *, created: bool) -> ExternalSpecimenResponse:
        props = self._props(specimen)
        atlas_refs = self._atlas_refs_for_specimen(specimen)
        container = self._linked_container_euid(specimen)
        return ExternalSpecimenResponse(
            specimen_euid=specimen.euid,
            container_euid=container,
            status=specimen.bstatus,
            atlas_refs=atlas_refs,
            properties=props,
            idempotency_key=props.get("external_idempotency_key"),
            created=created,
        )

    def _linked_container_euid(self, specimen) -> str | None:
        for lineage in get_child_lineages(specimen):
            if lineage.is_deleted:
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted:
                continue
            if parent.category == "container":
                return parent.euid
        return None

    def _normalize_template_code(self, code: str) -> str:
        clean = str(code or "").strip().strip("/")
        parts = clean.split("/")
        if len(parts) != 4:
            raise ValueError(
                f"Template code must be category/type/subtype/version: {code}"
            )
        return clean

    def _props(self, instance) -> dict[str, Any]:
        payload = instance.json_addl or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        props = payload.get("properties")
        if not isinstance(props, dict):
            props = {}
            payload["properties"] = props
            instance.json_addl = payload
        return props

    def _write_props(self, instance, props: dict[str, Any]) -> None:
        payload = instance.json_addl or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["properties"] = props
        instance.json_addl = payload
        flag_modified(instance, "json_addl")

    def _safe_get_by_euid(self, euid: str):
        try:
            return self.bobj.get_by_euid(euid)
        except Exception as exc:
            msg = str(exc).lower()
            if "not found" in msg or "no template found" in msg:
                return None
            raise

    def _atlas_refs_for_specimen(self, specimen) -> dict[str, str]:
        refs: dict[str, str] = {}
        for payload in self._reachable_atlas_reference_payloads(specimen):
            key, value = self._normalize_reference_payload(payload)
            if key and value:
                refs[key] = value
        return refs

    def _expand_parent_uids_to_specimen_uids(self, parent_uids: set[int]) -> set[int]:
        if not parent_uids:
            return set()

        instance_cls = self.bdb.Base.classes.generic_instance
        lineage_cls = self.bdb.Base.classes.generic_instance_lineage
        specimen_uids = {
            uid
            for (uid,) in (
                self.bdb.session.query(instance_cls.uid)
                .filter(
                    instance_cls.uid.in_(sorted(parent_uids)),
                    instance_cls.is_deleted.is_(False),
                    instance_cls.category == "content",
                )
                .all()
            )
            if uid is not None
        }
        specimen_uids.update(
            child_uid
            for (child_uid,) in (
                self.bdb.session.query(lineage_cls.child_instance_uid)
                .join(instance_cls, lineage_cls.child_instance_uid == instance_cls.uid)
                .filter(
                    lineage_cls.is_deleted.is_(False),
                    lineage_cls.parent_instance_uid.in_(sorted(parent_uids)),
                    lineage_cls.relationship_type == "contains",
                    instance_cls.is_deleted.is_(False),
                    instance_cls.category == "content",
                )
                .all()
            )
            if child_uid is not None
        )
        return specimen_uids

    def _reachable_atlas_reference_payloads(self, specimen) -> list[dict[str, Any]]:
        payloads: dict[tuple[str, str], dict[str, Any]] = {}
        visited: set[int | None] = set()
        to_visit = [specimen]
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)
            for payload in self._atlas_reference_payloads_for_instance(current):
                ref_key = (
                    str(payload.get("reference_type") or "").strip(),
                    str(payload.get("reference_value") or "").strip(),
                )
                if ref_key[0] and ref_key[1]:
                    payloads[ref_key] = payload
            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)
        return list(payloads.values())

    def _atlas_reference_payloads_for_instance(self, instance) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for lineage in get_parent_lineages(instance):
            if lineage.is_deleted:
                continue
            if lineage.relationship_type != self.EXTERNAL_REFERENCE_RELATIONSHIP:
                continue
            external_ref = lineage.child_instance
            if external_ref is None or external_ref.is_deleted:
                continue
            if (
                external_ref.category != "generic"
                or external_ref.type != "generic"
                or external_ref.subtype != "external_object_link"
            ):
                continue
            payload = self._props(external_ref)
            if str(payload.get("provider") or "").strip() != "atlas":
                continue
            payloads.append(payload)
        return payloads

    def _find_parent_uids_for_reference(
        self,
        *,
        reference_type: str,
        reference_value: str,
    ) -> set[int]:
        spec = self._REFERENCE_QUERY_SPECS.get(str(reference_type).strip())
        if spec is None:
            return set()

        lineage_cls = self.bdb.Base.classes.generic_instance_lineage
        instance_cls = self.bdb.Base.classes.generic_instance
        filters = [
            lineage_cls.is_deleted.is_(False),
            lineage_cls.relationship_type == self.EXTERNAL_REFERENCE_RELATIONSHIP,
            instance_cls.is_deleted.is_(False),
            instance_cls.category == "generic",
            instance_cls.type == "generic",
            instance_cls.subtype == "external_object_link",
            func.jsonb_extract_path_text(
                instance_cls.json_addl["properties"], "provider"
            )
            == "atlas",
            func.jsonb_extract_path_text(
                instance_cls.json_addl["properties"], str(spec["value_field"])
            )
            == str(reference_value).strip(),
        ]
        reference_types = spec.get("reference_types")
        query = self.bdb.session.query(lineage_cls.parent_instance_uid).join(
            instance_cls, lineage_cls.child_instance_uid == instance_cls.uid
        )
        if reference_types:
            query = query.filter(
                func.jsonb_extract_path_text(
                    instance_cls.json_addl["properties"], "reference_type"
                ).in_([str(item).strip() for item in reference_types])
            )
        rows = query.filter(*filters).all()
        return {parent_uid for (parent_uid,) in rows if parent_uid is not None}

    def _normalize_reference_payload(self, payload: dict[str, Any]) -> tuple[str, str]:
        reference_type = str(payload.get("reference_type") or "").strip()
        normalized = self._REFERENCE_RESPONSE_NORMALIZATION.get(reference_type)
        if normalized is not None:
            key, value_field = normalized
            value = str(payload.get(value_field) or payload.get("reference_value") or "").strip()
            return key, value
        return reference_type, str(payload.get("reference_value") or "").strip()

    def _replace_external_references(
        self,
        *,
        specimen,
        atlas_refs: dict[str, Any],
        atlas_validation: dict[str, Any],
    ) -> None:
        existing_refs = []
        for lineage in get_parent_lineages(specimen):
            if lineage.is_deleted:
                continue
            if lineage.relationship_type != self.EXTERNAL_REFERENCE_RELATIONSHIP:
                continue
            child = lineage.child_instance
            if child is None:
                continue
            existing_refs.append((lineage, child))

        for lineage, child in existing_refs:
            lineage.is_deleted = True
            child.is_deleted = True

        for reference_type, reference_value in sorted(atlas_refs.items()):
            value = str(reference_value or "").strip()
            if not value:
                continue
            validation_payload = atlas_validation.get(reference_type)
            ref_payload = {
                "properties": {
                    "provider": "atlas",
                    "reference_type": str(reference_type),
                    "reference_value": value,
                    "foreign_reference": value,
                    "validation": validation_payload
                    if isinstance(validation_payload, dict)
                    else {},
                }
            }
            ref_obj = self.bobj.create_instance_by_code(
                self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                {"json_addl": ref_payload},
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                specimen.euid,
                ref_obj.euid,
                relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
            )
