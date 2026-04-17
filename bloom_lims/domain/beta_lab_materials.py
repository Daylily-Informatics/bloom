"""Internal material intake and update helpers for beta lab domain services."""

from __future__ import annotations

from bloom_lims.schemas.beta_lab import (
    BetaAcceptedMaterialCreateRequest,
    BetaMaterialResponse,
)
from bloom_lims.template_identity import template_semantic_category


class _BetaLabMaterialsMixin:
    def register_accepted_material(
        self,
        *,
        payload: BetaAcceptedMaterialCreateRequest,
        idempotency_key: str | None,
    ) -> BetaMaterialResponse:
        if idempotency_key:
            existing = self._find_content_record(
                beta_kind="accepted_material",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return self._material_response(existing, created=False)

        container = self._resolve_or_create_container(
            container_euid=payload.container_euid,
            container_template_code=payload.container_template_code,
            specimen_name=payload.specimen_name or "accepted-material",
        )
        specimen = self.bobj.create_instance_by_code(
            payload.specimen_template_code,
            {"json_addl": {"properties": payload.properties or {}}},
        )
        specimen.bstatus = payload.status or specimen.bstatus
        specimen_props = self._props(specimen)
        specimen_props["beta_kind"] = "accepted_material"
        if payload.specimen_name:
            specimen.name = payload.specimen_name
            specimen_props["name"] = payload.specimen_name
        if idempotency_key:
            specimen_props["idempotency_key"] = idempotency_key
        self._write_props(specimen, specimen_props)
        self._ensure_container_link(container.euid, specimen.euid)

        self._replace_container_entity_references(
            container,
            atlas_context=payload.atlas_context.model_dump(),
        )
        self._replace_fulfillment_item_references(
            container,
            atlas_context=payload.atlas_context.model_dump(),
        )
        self._replace_collection_event_reference(
            specimen,
            atlas_context=payload.atlas_context.model_dump(),
        )
        if self._has_collection_event_context(payload.atlas_context.model_dump()):
            self._delete_reference_type(
                specimen,
                reference_type=self.PATIENT_REFERENCE_TYPE,
            )
        else:
            self._replace_patient_reference(
                specimen,
                atlas_context=payload.atlas_context.model_dump(),
            )
        self._record_action(
            target_instance=specimen,
            action_key="register_accepted_material",
            captured_data={
                "specimen_template_code": payload.specimen_template_code,
                "specimen_name": payload.specimen_name,
                "container_euid": payload.container_euid,
                "container_template_code": payload.container_template_code,
                "status": payload.status,
                "atlas_context": payload.atlas_context.model_dump(),
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "specimen_euid": specimen.euid,
                "container_euid": container.euid if container is not None else None,
            },
        )
        self.bdb.session.commit()
        return self._material_response(specimen, created=True)

    def create_empty_tube(
        self,
        *,
        payload,
        idempotency_key: str | None,
    ):
        if idempotency_key:
            existing = self._find_container_record(
                beta_kind="atlas_tube",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return self._tube_response(existing, created=False)

        container = self._resolve_or_create_container(
            container_euid=None,
            container_template_code=payload.container_template_code,
            specimen_name="atlas-tube",
        )
        container.bstatus = payload.status or container.bstatus
        props = self._props(container)
        props["beta_kind"] = "atlas_tube"
        if idempotency_key:
            props["idempotency_key"] = idempotency_key
        if payload.properties:
            props.update(payload.properties)
        self._write_props(container, props)
        self._replace_container_entity_references(
            container,
            atlas_context=payload.atlas_context.model_dump(),
        )
        self._replace_fulfillment_item_references(
            container,
            atlas_context=payload.atlas_context.model_dump(),
        )
        self._record_action(
            target_instance=container,
            action_key="create_empty_tube",
            captured_data={
                "container_template_code": payload.container_template_code,
                "status": payload.status,
                "properties": payload.properties or {},
                "atlas_context": payload.atlas_context.model_dump(),
                "idempotency_key": idempotency_key or "",
            },
            result={"status": "success", "container_euid": container.euid},
        )
        self.bdb.session.commit()
        return self._tube_response(container, created=True)

    def update_tube(
        self,
        *,
        container_euid: str,
        payload,
    ):
        container = self._require_instance(container_euid)
        template = self._require_template(
            f"{container.category}/{container.type}/{container.subtype}/{container.version}"
        )
        if template_semantic_category(template) != "container":
            raise ValueError(f"EUID is not a container: {container_euid}")

        if payload.status is not None:
            container.bstatus = payload.status
        props = self._props(container)
        if payload.properties:
            props.update(payload.properties)
            self._write_props(container, props)
        if payload.atlas_context is not None:
            atlas_context = payload.atlas_context.model_dump()
            self._replace_container_entity_references(
                container, atlas_context=atlas_context
            )
            self._replace_fulfillment_item_references(
                container, atlas_context=atlas_context
            )

        self._record_action(
            target_instance=container,
            action_key="update_tube",
            captured_data={
                "container_euid": container_euid,
                "status": payload.status,
                "properties": payload.properties or {},
                "atlas_context": (
                    payload.atlas_context.model_dump()
                    if payload.atlas_context is not None
                    else None
                ),
            },
            result={
                "status": "success",
                "container_euid": container.euid,
                "current_status": container.bstatus,
            },
        )
        self.bdb.session.commit()
        return self._tube_response(container, created=True)

    def update_specimen(
        self,
        *,
        specimen_euid: str,
        payload,
    ):
        specimen = self._require_instance(specimen_euid)
        template = self._require_template(
            f"{specimen.category}/{specimen.type}/{specimen.subtype}/{specimen.version}"
        )
        if template_semantic_category(template) != "content":
            raise ValueError(f"EUID is not a specimen/content object: {specimen_euid}")

        if payload.status is not None:
            specimen.bstatus = payload.status
        props = self._props(specimen)
        if payload.properties:
            props.update(payload.properties)
            self._write_props(specimen, props)
        if payload.atlas_context is not None:
            atlas_context = payload.atlas_context.model_dump()
            self._replace_collection_event_reference(
                specimen, atlas_context=atlas_context
            )
            if self._has_collection_event_context(atlas_context):
                self._delete_reference_type(
                    specimen,
                    reference_type=self.PATIENT_REFERENCE_TYPE,
                )
            else:
                self._replace_patient_reference(specimen, atlas_context=atlas_context)

        self._record_action(
            target_instance=specimen,
            action_key="update_specimen",
            captured_data={
                "specimen_euid": specimen_euid,
                "status": payload.status,
                "properties": payload.properties or {},
                "atlas_context": (
                    payload.atlas_context.model_dump()
                    if payload.atlas_context is not None
                    else None
                ),
            },
            result={
                "status": "success",
                "specimen_euid": specimen.euid,
                "current_status": specimen.bstatus,
            },
        )
        self.bdb.session.commit()
        return self._material_response(specimen, created=True)

    def _material_response(self, specimen, *, created: bool) -> BetaMaterialResponse:
        atlas_context = dict(self._atlas_context_for_instance(specimen))
        container_euid = self._linked_container_euid(specimen)
        if container_euid:
            container = self._require_instance(container_euid)
            container_context = self._atlas_context_for_instance(container)
            for key, value in container_context.items():
                if key == "fulfillment_items":
                    if value and not atlas_context.get(key):
                        atlas_context[key] = value
                    continue
                if isinstance(value, str):
                    if value.strip() and not str(atlas_context.get(key) or "").strip():
                        atlas_context[key] = value
                    continue
                if value not in (None, {}, []) and key not in atlas_context:
                    atlas_context[key] = value
        return BetaMaterialResponse(
            specimen_euid=specimen.euid,
            container_euid=container_euid,
            status=specimen.bstatus,
            atlas_context=atlas_context,
            properties=self._props(specimen),
            idempotency_key=str(self._props(specimen).get("idempotency_key") or "")
            or None,
            current_queue=self._current_queue_for_instance(specimen),
            created=created,
        )

    def _tube_response(self, container, *, created: bool):
        return {
            "container_euid": container.euid,
            "status": container.bstatus,
            "atlas_context": self._atlas_context_for_instance(container),
            "properties": self._props(container),
            "idempotency_key": str(self._props(container).get("idempotency_key") or "")
            or None,
            "current_queue": self._current_queue_for_instance(container),
            "created": created,
        }
