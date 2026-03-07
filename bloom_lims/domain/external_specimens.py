"""Domain service for external Atlas-driven specimen operations."""

from __future__ import annotations

import json
from typing import Any

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

    def __init__(self, *, app_username: str):
        self.bdb = BLOOMdb3(app_username=app_username)
        self.bobj = BloomObj(self.bdb)
        self.atlas = AtlasService()

    def close(self) -> None:
        self.bdb.close()

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
        specimen_props["atlas_refs"] = atlas_refs
        specimen_props["atlas_validation"] = atlas_meta
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
        if payload.atlas_refs is not None:
            atlas_refs, atlas_meta = self._validate_atlas_refs(
                payload.atlas_refs,
                container_euid=payload.container_euid,
            )
            specimen_props["atlas_refs"] = atlas_refs
            specimen_props["atlas_validation"] = atlas_meta
        self._write_props(specimen, specimen_props)

        if payload.container_euid:
            container = self._safe_get_by_euid(payload.container_euid)
            if container is None or container.is_deleted:
                raise ValueError(f"Container not found: {payload.container_euid}")
            if container.category != "container":
                raise ValueError(f"EUID is not a container: {payload.container_euid}")
            self._ensure_container_link(container.euid, specimen.euid)

        self.bdb.session.commit()
        return self._to_response(specimen, created=True)

    def find_by_references(self, refs: AtlasReferences) -> list[ExternalSpecimenResponse]:
        filters = {
            "order_number": refs.order_number,
            "patient_id": refs.patient_id,
            "shipment_number": refs.shipment_number or refs.package_number,
            "kit_barcode": refs.kit_barcode,
        }
        normalized_filters = {
            key: str(value).strip()
            for key, value in filters.items()
            if value is not None and str(value).strip()
        }
        if not normalized_filters:
            return []

        query = (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "content",
                self.bdb.Base.classes.generic_instance.is_deleted == False,
            )
            .all()
        )
        results: list[ExternalSpecimenResponse] = []
        for instance in query:
            props = self._props(instance)
            atlas_refs = props.get("atlas_refs")
            if not isinstance(atlas_refs, dict):
                continue
            is_match = True
            for key, expected in normalized_filters.items():
                actual = str(atlas_refs.get(key, "")).strip()
                if actual != expected:
                    is_match = False
                    break
            if is_match:
                results.append(self._to_response(instance, created=True))
        return results

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
        rows = (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "content",
                self.bdb.Base.classes.generic_instance.is_deleted == False,
            )
            .all()
        )
        for row in rows:
            props = self._props(row)
            if str(props.get("external_idempotency_key", "")).strip() == expected:
                return row
        return None

    def _validate_atlas_refs(
        self,
        refs: AtlasReferences,
        *,
        container_euid: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {
            "order_number": refs.order_number,
            "patient_id": refs.patient_id,
            "shipment_number": refs.shipment_number or refs.package_number,
            "package_number": refs.package_number,
            "kit_barcode": refs.kit_barcode,
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
            if container_euid:
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
                    "summary": self._build_container_context_summary(ctx_result.payload),
                }

            if "order_number" in normalized:
                result = self.atlas.get_order(normalized["order_number"])
                validation_meta["order"] = {
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
        order = context.get("order") if isinstance(context.get("order"), dict) else {}
        patient = context.get("patient") if isinstance(context.get("patient"), dict) else {}
        links = context.get("links") if isinstance(context.get("links"), dict) else {}

        context_values = {
            "order_number": str(order.get("order_number") or "").strip(),
            "patient_id": str(patient.get("patient_id") or "").strip(),
            "shipment_number": str(links.get("shipment_number") or links.get("package_number") or "").strip(),
            "package_number": str(links.get("package_number") or "").strip(),
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

    def _build_container_context_summary(self, context: dict[str, Any]) -> dict[str, Any]:
        order = context.get("order") if isinstance(context.get("order"), dict) else {}
        patient = context.get("patient") if isinstance(context.get("patient"), dict) else {}
        links = context.get("links") if isinstance(context.get("links"), dict) else {}
        test_orders = context.get("test_orders") if isinstance(context.get("test_orders"), list) else []
        test_order_ids = []
        for entry in test_orders:
            if not isinstance(entry, dict):
                continue
            test_order_id = str(entry.get("test_order_id") or "").strip()
            if test_order_id:
                test_order_ids.append(test_order_id)

        return {
            "tenant_id": context.get("tenant_id"),
            "order_number": order.get("order_number"),
            "patient_id": patient.get("patient_id"),
            "testkit_barcode": links.get("testkit_barcode"),
            "package_number": links.get("package_number"),
            "test_order_count": len(test_order_ids),
            "test_order_ids": test_order_ids,
        }

    def _to_response(self, specimen, *, created: bool) -> ExternalSpecimenResponse:
        props = self._props(specimen)
        atlas_refs = props.get("atlas_refs") if isinstance(props.get("atlas_refs"), dict) else {}
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
            raise ValueError(f"Template code must be category/type/subtype/version: {code}")
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
