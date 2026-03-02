"""Domain service for external Atlas-driven specimen operations."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3
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

        atlas_refs, atlas_meta = self._validate_atlas_refs(payload.atlas_refs)

        specimen = self.bobj.create_instance_by_code(
            self._normalize_template_code(payload.specimen_template_code),
            {"json_addl": {"properties": payload.properties or {}}},
        )
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
        specimen = self.bobj.get_by_euid(specimen_euid)
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
        specimen = self.bobj.get_by_euid(specimen_euid)
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
            atlas_refs, atlas_meta = self._validate_atlas_refs(payload.atlas_refs)
            specimen_props["atlas_refs"] = atlas_refs
            specimen_props["atlas_validation"] = atlas_meta
        self._write_props(specimen, specimen_props)

        if payload.container_euid:
            container = self.bobj.get_by_euid(payload.container_euid)
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
            container = self.bobj.get_by_euid(container_euid)
            if container is None or container.is_deleted:
                raise ValueError(f"Container not found: {container_euid}")
            if container.category != "container":
                raise ValueError(f"EUID is not a container: {container_euid}")
            return container

        container = self.bobj.create_instance_by_code(
            self._normalize_template_code(container_template_code),
            {"json_addl": {"properties": {"name": f"{specimen_name} container"}}},
        )
        if container is None:
            raise ValueError("Failed to create container for specimen")
        return container

    def _ensure_container_link(self, container_euid: str, specimen_euid: str) -> None:
        container = self.bobj.get_by_euid(container_euid)
        specimen = self.bobj.get_by_euid(specimen_euid)
        if container is None or specimen is None:
            return
        for lineage in container.parent_of_lineages:
            if lineage.is_deleted:
                continue
            if lineage.child_instance_uuid == specimen.uuid:
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
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {
            "order_number": refs.order_number,
            "patient_id": refs.patient_id,
            "shipment_number": refs.shipment_number or refs.package_number,
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

    def _to_response(self, specimen, *, created: bool) -> ExternalSpecimenResponse:
        props = self._props(specimen)
        atlas_refs = props.get("atlas_refs") if isinstance(props.get("atlas_refs"), dict) else {}
        container = self._linked_container_euid(specimen)
        return ExternalSpecimenResponse(
            specimen_euid=specimen.euid,
            specimen_uuid=str(specimen.uuid),
            container_euid=container,
            status=specimen.bstatus,
            atlas_refs=atlas_refs,
            properties=props,
            idempotency_key=props.get("external_idempotency_key"),
            created=created,
        )

    def _linked_container_euid(self, specimen) -> str | None:
        for lineage in specimen.child_of_lineages:
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

