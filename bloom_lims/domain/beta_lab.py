"""Queue-driven beta lab domain services for Bloom."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3, get_child_lineages, get_parent_lineages
from bloom_lims.domain.beta_actions import BloomBetaActionRecorder
from bloom_lims.schemas.beta_lab import (
    BetaAcceptedMaterialCreateRequest,
    BetaClaimResponse,
    BetaConsumeMaterialResponse,
    BetaExtractionCreateRequest,
    BetaExtractionResponse,
    BetaLibraryPrepCreateRequest,
    BetaLibraryPrepResponse,
    BetaMaterialResponse,
    BetaPoolCreateRequest,
    BetaPoolResponse,
    BetaPostExtractQCRequest,
    BetaPostExtractQCResponse,
    BetaQueueTransitionResponse,
    BetaReservationResponse,
    BetaRunCreateRequest,
    BetaRunResolutionResponse,
    BetaRunResponse,
)


class BetaLabService:
    """Implements the queue-centric Bloom beta wet-lab flow."""

    EXTERNAL_REFERENCE_TEMPLATE_CODE = "generic/generic/external_object_link/1.0"
    EXTERNAL_REFERENCE_RELATIONSHIP = "has_external_reference"
    PROCESS_ITEM_REFERENCE_TYPE = "atlas_test_process_item"
    PATIENT_REFERENCE_TYPE = "atlas_patient"
    TRF_REFERENCE_TYPE = "atlas_trf"
    TEST_REFERENCE_TYPE = "atlas_test"
    TESTKIT_REFERENCE_TYPE = "atlas_testkit"
    SHIPMENT_REFERENCE_TYPE = "atlas_shipment"
    ORGANIZATION_SITE_REFERENCE_TYPE = "atlas_organization_site"
    COLLECTION_EVENT_REFERENCE_TYPE = "atlas_collection_event"
    GENERIC_DATA_TEMPLATE_CODE = "generic/generic/generic/1.0"
    BETA_KIND_QUEUE_DEFINITION = "queue_definition"
    BETA_KIND_QUEUE_EVENT = "queue_event"
    BETA_KIND_WORK_ITEM = "beta_work_item"
    BETA_KIND_CLAIM = "beta_claim"
    BETA_KIND_RESERVATION = "beta_reservation"
    BETA_KIND_CONSUMPTION_EVENT = "beta_consumption_event"
    REL_QUEUE_MEMBERSHIP = "beta_queue_membership"
    REL_QUEUE_EVENT = "beta_queue_event"
    REL_QUEUE_EVENT_QUEUE = "beta_queue_event_queue"
    REL_QUEUE_WORK_ITEM = "beta_queue_work_item"
    REL_WORK_ITEM_SUBJECT = "beta_work_item_subject"
    REL_WORK_ITEM_CLAIM = "beta_work_item_claim"
    REL_MATERIAL_RESERVATION = "beta_material_reservation"
    REL_MATERIAL_CONSUMPTION = "beta_material_consumption"
    REL_USED_INSTRUMENT = "beta_used_instrument"
    REL_USED_REAGENT = "beta_used_reagent"
    POOL_TEMPLATE_CODE = "content/pool/generic/1.0"
    POOL_CONTAINER_TEMPLATE_CODE = "container/tube/tube-generic-10ml/1.0"
    EXTRACTION_TEMPLATE_BY_TYPE = {
        "cfdna": "content/sample/cfdna/1.0",
        "gdna": "content/sample/gdna/1.0",
    }
    LIB_PREP_QUEUE_BY_PLATFORM = {
        "ILMN": "ilmn_lib_prep",
        "ONT": "ont_lib_prep",
    }
    SEQ_POOL_QUEUE_BY_PLATFORM = {
        "ILMN": "ilmn_seq_pool",
        "ONT": "ont_seq_pool",
    }
    START_RUN_QUEUE_BY_PLATFORM = {
        "ILMN": "ilmn_start_seq_run",
        "ONT": "ont_start_seq_run",
    }
    CANONICAL_QUEUES = (
        "extraction_prod",
        "extraction_rnd",
        "post_extract_qc",
        "ilmn_lib_prep",
        "ont_lib_prep",
        "ilmn_seq_pool",
        "ont_seq_pool",
        "ilmn_start_seq_run",
        "ont_start_seq_run",
    )

    def __init__(self, *, app_username: str):
        self.bdb = BLOOMdb3(app_username=app_username)
        self.bobj = BloomObj(self.bdb)
        self.action_recorder = BloomBetaActionRecorder(self.bdb.session)

    def close(self) -> None:
        self.bdb.close()

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
        self._replace_process_item_references(
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
        self._replace_process_item_references(
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
        if container.category != "container":
            raise ValueError(f"EUID is not a container: {container_euid}")

        if payload.status is not None:
            container.bstatus = payload.status
        props = self._props(container)
        if payload.properties:
            props.update(payload.properties)
            self._write_props(container, props)
        if payload.atlas_context is not None:
            atlas_context = payload.atlas_context.model_dump()
            self._replace_container_entity_references(container, atlas_context=atlas_context)
            self._replace_process_item_references(container, atlas_context=atlas_context)

        self._record_action(
            target_instance=container,
            action_key="update_tube",
            captured_data={
                "container_euid": container_euid,
                "status": payload.status,
                "properties": payload.properties or {},
                "atlas_context": (
                    payload.atlas_context.model_dump() if payload.atlas_context is not None else None
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
        if specimen.category != "content":
            raise ValueError(f"EUID is not a specimen/content object: {specimen_euid}")

        if payload.status is not None:
            specimen.bstatus = payload.status
        props = self._props(specimen)
        if payload.properties:
            props.update(payload.properties)
            self._write_props(specimen, props)
        if payload.atlas_context is not None:
            atlas_context = payload.atlas_context.model_dump()
            self._replace_collection_event_reference(specimen, atlas_context=atlas_context)
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
                    payload.atlas_context.model_dump() if payload.atlas_context is not None else None
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

    def move_material_to_queue(
        self,
        *,
        material_euid: str,
        queue_name: str,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaQueueTransitionResponse:
        material = self._require_instance(material_euid)
        replay = False
        if idempotency_key:
            existing = self._find_operation_record(
                beta_kind=self.BETA_KIND_QUEUE_EVENT,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                replay = True
                return self._queue_transition_response_from_event(
                    existing, replay=replay
                )

        response = self._transition_material(
            material=material,
            queue_name=queue_name,
            metadata=metadata or {},
            idempotency_key=idempotency_key,
            replay=replay,
        )
        self._record_action(
            target_instance=material,
            action_key="move_material_to_queue",
            captured_data={
                "material_euid": material_euid,
                "queue_name": queue_name,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "material_euid": response.material_euid,
                "queue_euid": response.queue_euid,
                "queue_name": response.queue_name,
                "current_queue": response.current_queue,
            },
        )
        self.bdb.session.commit()
        return response

    def claim_material_in_queue(
        self,
        *,
        material_euid: str,
        queue_name: str,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaClaimResponse:
        normalized_queue = str(queue_name or "").strip()
        if normalized_queue not in self.CANONICAL_QUEUES:
            raise ValueError(f"Unsupported beta queue: {queue_name}")
        if idempotency_key:
            existing = self._find_data_record_by_property(
                beta_kind=self.BETA_KIND_CLAIM,
                property_key="idempotency_key",
                expected=idempotency_key,
            )
            if existing is not None:
                return self._claim_response(existing, replay=True)

        material = self._require_instance(material_euid)
        self._assert_not_reserved(material)
        self._assert_not_consumed(material, stage_label="claim")
        current_queue = self._current_queue_for_instance(material)
        if current_queue != normalized_queue:
            raise ValueError(
                "Material must already be in requested queue before claim "
                f"(expected={normalized_queue!r} current_queue={current_queue!r})"
            )
        work_item = self._require_open_work_item(
            material=material,
            expected_queue=normalized_queue,
        )
        active_claim = self._active_claim_for_work_item(work_item)
        if active_claim is not None:
            raise ValueError(
                "Material already has an active claim in the requested queue "
                f"(claim_euid={active_claim.euid})"
            )
        claim = self._create_claim_record(
            material=material,
            queue_name=normalized_queue,
            work_item=work_item,
            metadata=metadata or {},
            idempotency_key=idempotency_key,
            implicit=False,
        )
        self._record_action(
            target_instance=material,
            action_key="claim_material_in_queue",
            captured_data={
                "material_euid": material_euid,
                "queue_name": normalized_queue,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "claim_euid": claim.euid,
                "queue_name": normalized_queue,
                "material_euid": material.euid,
            },
        )
        self.bdb.session.commit()
        return self._claim_response(claim, replay=False)

    def release_claim(
        self,
        *,
        claim_euid: str,
        reason: str | None,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaClaimResponse:
        claim = self._require_instance(claim_euid)
        if not self._is_data_kind(claim, self.BETA_KIND_CLAIM):
            raise ValueError(f"Bloom claim not found: {claim_euid}")
        claim_props = self._props(claim)
        if (
            idempotency_key
            and str(claim_props.get("last_release_idempotency_key") or "").strip()
            == str(idempotency_key).strip()
        ):
            return self._claim_response(claim, replay=True)

        release_status = str(reason or "").strip().lower() or "released"
        if release_status not in {"released", "completed", "abandoned"}:
            release_status = "released"
        claim_props["status"] = release_status
        claim_props["released_at"] = self._timestamp()
        claim_props["release_reason"] = str(reason or "").strip() or release_status
        claim_props["release_metadata"] = self.normalize_execution_metadata(
            metadata or {}
        )
        claim_props["last_release_idempotency_key"] = idempotency_key or ""
        self._write_props(claim, claim_props)
        self._record_action(
            target_instance=claim,
            action_key="release_claim",
            captured_data={
                "claim_euid": claim_euid,
                "reason": reason,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={"status": "success", "claim_euid": claim.euid},
        )
        self.bdb.session.commit()
        return self._claim_response(claim, replay=False)

    def reserve_material(
        self,
        *,
        material_euid: str,
        reason: str | None,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaReservationResponse:
        if idempotency_key:
            existing = self._find_data_record_by_property(
                beta_kind=self.BETA_KIND_RESERVATION,
                property_key="idempotency_key",
                expected=idempotency_key,
            )
            if existing is not None:
                return self._reservation_response(existing, replay=True)

        material = self._require_instance(material_euid)
        active_reservation = self._active_reservation_for_material(material)
        if active_reservation is not None:
            raise ValueError(
                "Material already has an active reservation "
                f"(reservation_euid={active_reservation.euid})"
            )

        metadata_payload = self.normalize_execution_metadata(metadata or {})
        reservation = self._create_data_record(
            beta_kind=self.BETA_KIND_RESERVATION,
            name=f"reservation:{material.euid}",
            properties={
                "material_euid": material.euid,
                "status": "active",
                "reason": str(reason or "").strip(),
                "idempotency_key": idempotency_key or "",
                "metadata": metadata_payload,
                "reserved_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            material.euid,
            reservation.euid,
            relationship_type=self.REL_MATERIAL_RESERVATION,
        )
        self._attach_execution_metadata_lineage(
            reservation,
            metadata_payload,
        )
        self._record_action(
            target_instance=material,
            action_key="reserve_material",
            captured_data={
                "material_euid": material_euid,
                "reason": reason,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "reservation_euid": reservation.euid,
                "material_euid": material.euid,
            },
        )
        self.bdb.session.commit()
        return self._reservation_response(reservation, replay=False)

    def release_reservation(
        self,
        *,
        reservation_euid: str,
        reason: str | None,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaReservationResponse:
        reservation = self._require_instance(reservation_euid)
        if not self._is_data_kind(reservation, self.BETA_KIND_RESERVATION):
            raise ValueError(f"Bloom reservation not found: {reservation_euid}")
        reservation_props = self._props(reservation)
        if (
            idempotency_key
            and str(reservation_props.get("last_release_idempotency_key") or "").strip()
            == str(idempotency_key).strip()
        ):
            return self._reservation_response(reservation, replay=True)
        reservation_props["status"] = "released"
        reservation_props["released_at"] = self._timestamp()
        reservation_props["release_reason"] = str(reason or "").strip()
        reservation_props["release_metadata"] = self.normalize_execution_metadata(
            metadata or {}
        )
        reservation_props["last_release_idempotency_key"] = idempotency_key or ""
        self._write_props(reservation, reservation_props)
        self._record_action(
            target_instance=reservation,
            action_key="release_reservation",
            captured_data={
                "reservation_euid": reservation_euid,
                "reason": reason,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={"status": "success", "reservation_euid": reservation.euid},
        )
        self.bdb.session.commit()
        return self._reservation_response(reservation, replay=False)

    def consume_material(
        self,
        *,
        material_euid: str,
        reason: str | None,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaConsumeMaterialResponse:
        if idempotency_key:
            existing = self._find_data_record_by_property(
                beta_kind=self.BETA_KIND_CONSUMPTION_EVENT,
                property_key="idempotency_key",
                expected=idempotency_key,
            )
            if existing is not None:
                return self._consumption_response(existing, replay=True)

        material = self._require_instance(material_euid)
        if self._is_consumed(material):
            raise ValueError(f"Material is already consumed: {material.euid}")
        metadata_payload = self.normalize_execution_metadata(metadata or {})
        event = self._create_data_record(
            beta_kind=self.BETA_KIND_CONSUMPTION_EVENT,
            name=f"consumption:{material.euid}",
            properties={
                "material_euid": material.euid,
                "reason": str(reason or "").strip(),
                "idempotency_key": idempotency_key or "",
                "metadata": metadata_payload,
                "occurred_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            material.euid,
            event.euid,
            relationship_type=self.REL_MATERIAL_CONSUMPTION,
        )
        self._attach_execution_metadata_lineage(event, metadata_payload)
        material_props = self._props(material)
        material_props["consumed_at"] = self._timestamp()
        material_props["consumed_event_euid"] = event.euid
        self._write_props(material, material_props)
        self._record_action(
            target_instance=material,
            action_key="consume_material",
            captured_data={
                "material_euid": material_euid,
                "reason": reason,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "material_euid": material.euid,
                "consumption_event_euid": event.euid,
            },
        )
        self.bdb.session.commit()
        return self._consumption_response(event, replay=False)

    def create_extraction(
        self,
        *,
        payload: BetaExtractionCreateRequest,
        idempotency_key: str | None,
    ) -> BetaExtractionResponse:
        if idempotency_key:
            existing = self._find_content_record(
                beta_kind="extraction_output",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return self._extraction_response(existing, replay=True)

        source = self._require_instance(payload.source_specimen_euid)
        self._assert_not_reserved(source)
        self._assert_not_consumed(source, stage_label="extraction")
        current_queue = self._current_queue_for_instance(source)
        if current_queue not in {"extraction_prod", "extraction_rnd"}:
            raise ValueError(
                "Source specimen must be queued in extraction_prod or extraction_rnd "
                f"(current_queue={current_queue!r})"
            )
        claim = self._resolve_stage_claim(
            material=source,
            expected_queues={"extraction_prod", "extraction_rnd"},
            claim_euid=payload.claim_euid,
            stage_label="extraction",
        )

        process_item_context = self._resolve_process_item_context(
            source,
            target_process_item_euid=payload.atlas_test_process_item_euid,
        )
        plate = self._resolve_or_create_plate(
            plate_euid=payload.plate_euid,
            plate_template_code=payload.plate_template_code,
            plate_name=payload.plate_name,
        )
        well = self._require_plate_well(plate, payload.well_name)

        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})
        output = self.bobj.create_instance_by_code(
            self.EXTRACTION_TEMPLATE_BY_TYPE[payload.extraction_type],
            {
                "json_addl": {
                    "properties": {
                        "beta_kind": "extraction_output",
                        "extraction_type": payload.extraction_type,
                        "idempotency_key": idempotency_key or "",
                        "metadata": normalized_metadata,
                    }
                }
            },
        )
        output_props = self._props(output)
        output_name = payload.output_name or f"{source.name or source.euid} extract"
        output.name = output_name
        output_props["name"] = output_name
        self._write_props(output, output_props)
        self.bobj.create_generic_instance_lineage_by_euids(
            source.euid,
            output.euid,
            relationship_type="beta_extraction_output",
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            well.euid,
            output.euid,
            relationship_type="contains",
        )
        self._attach_execution_metadata_lineage(output, normalized_metadata)
        self._replace_process_item_references(output, atlas_context=process_item_context)
        response = self._transition_material(
            material=output,
            queue_name="post_extract_qc",
            metadata={
                "stage": "extraction",
                "well_name": payload.well_name,
                **normalized_metadata,
            },
            idempotency_key=f"{idempotency_key}:post_extract_qc"
            if idempotency_key
            else None,
        )
        if payload.consume_source:
            self._consume_material_instance(
                source,
                reason="stage:extraction",
                metadata={"stage": "extraction", **normalized_metadata},
            )
        self._set_claim_status(
            claim,
            status="completed",
            reason="stage:extraction",
            metadata={"stage": "extraction"},
        )
        self._record_action(
            target_instance=output,
            action_key="create_extraction",
            captured_data={
                "source_specimen_euid": payload.source_specimen_euid,
                "plate_euid": payload.plate_euid,
                "plate_template_code": payload.plate_template_code,
                "plate_name": payload.plate_name,
                "well_name": payload.well_name,
                "extraction_type": payload.extraction_type,
                "output_name": payload.output_name,
                "atlas_test_process_item_euid": payload.atlas_test_process_item_euid,
                "metadata": normalized_metadata,
                "claim_euid": payload.claim_euid,
                "consume_source": bool(payload.consume_source),
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "source_specimen_euid": source.euid,
                "extraction_output_euid": output.euid,
                "plate_euid": plate.euid,
                "well_euid": well.euid,
                "current_queue": response.current_queue,
            },
        )
        self.bdb.session.commit()
        return BetaExtractionResponse(
            source_specimen_euid=source.euid,
            plate_euid=plate.euid,
            well_euid=well.euid,
            well_name=payload.well_name,
            extraction_output_euid=output.euid,
            atlas_test_process_item_euid=process_item_context[
                "atlas_test_process_item_euid"
            ],
            current_queue=response.current_queue,
            idempotent_replay=False,
        )

    def record_post_extract_qc(
        self,
        *,
        payload: BetaPostExtractQCRequest,
        idempotency_key: str | None,
    ) -> BetaPostExtractQCResponse:
        output = self._require_instance(payload.extraction_output_euid)
        self._assert_not_reserved(output)
        self._assert_not_consumed(output, stage_label="post_extract_qc")
        if idempotency_key:
            existing = self._find_operation_record(
                beta_kind="post_extract_qc_result",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return BetaPostExtractQCResponse(
                    extraction_output_euid=payload.extraction_output_euid,
                    qc_passed=bool(self._props(existing).get("passed")),
                    current_queue=self._current_queue_for_instance(output),
                    idempotent_replay=True,
                )

        current_queue = self._current_queue_for_instance(output)
        if current_queue != "post_extract_qc":
            raise ValueError(
                "Extraction output must be queued in post_extract_qc "
                f"(current_queue={current_queue!r})"
            )

        qc_record = self._create_data_record(
            beta_kind="post_extract_qc_result",
            name=f"post-extract-qc:{output.euid}",
            properties={
                "passed": bool(payload.passed),
                "next_queue": payload.next_queue or "",
                "metrics": payload.metrics or {},
                "metadata": self.normalize_execution_metadata(payload.metadata or {}),
                "idempotency_key": idempotency_key or "",
                "occurred_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            output.euid,
            qc_record.euid,
            relationship_type="beta_post_extract_qc",
        )
        self._attach_execution_metadata_lineage(
            qc_record,
            self.normalize_execution_metadata(payload.metadata or {}),
        )
        output_props = self._props(output)
        output_props["qc"] = {
            "passed": bool(payload.passed),
            "metrics": payload.metrics or {},
            "occurred_at": self._timestamp(),
        }
        self._write_props(output, output_props)

        next_queue = None
        if payload.passed and payload.next_queue:
            transition = self._transition_material(
                material=output,
                queue_name=payload.next_queue,
                metadata={
                    "stage": "post_extract_qc",
                    **self.normalize_execution_metadata(payload.metadata or {}),
                },
                idempotency_key=f"{idempotency_key}:queue" if idempotency_key else None,
            )
            next_queue = transition.current_queue

        self._record_action(
            target_instance=output,
            action_key="record_post_extract_qc",
            captured_data={
                "extraction_output_euid": payload.extraction_output_euid,
                "passed": bool(payload.passed),
                "next_queue": payload.next_queue,
                "metrics": payload.metrics or {},
                "metadata": payload.metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "extraction_output_euid": output.euid,
                "qc_passed": bool(payload.passed),
                "current_queue": next_queue,
            },
        )
        self.bdb.session.commit()
        return BetaPostExtractQCResponse(
            extraction_output_euid=output.euid,
            qc_passed=bool(payload.passed),
            current_queue=next_queue,
            idempotent_replay=False,
        )

    def create_library_prep(
        self,
        *,
        payload: BetaLibraryPrepCreateRequest,
        idempotency_key: str | None,
    ) -> BetaLibraryPrepResponse:
        if idempotency_key:
            existing = self._find_data_record(
                beta_kind="library_prep_output",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                source = self._first_parent(existing, "beta_library_prep_output")
                process_item_context = self._resolve_process_item_context(existing)
                return BetaLibraryPrepResponse(
                    source_extraction_output_euid=source.euid if source is not None else "",
                    library_prep_output_euid=existing.euid,
                    atlas_test_process_item_euid=process_item_context[
                        "atlas_test_process_item_euid"
                    ],
                    current_queue=self._current_queue_for_instance(existing) or "",
                    idempotent_replay=True,
                )

        source = self._require_instance(payload.source_extraction_output_euid)
        self._assert_not_reserved(source)
        self._assert_not_consumed(source, stage_label="library_prep")
        expected_queue = self.LIB_PREP_QUEUE_BY_PLATFORM[payload.platform]
        current_queue = self._current_queue_for_instance(source)
        if current_queue != expected_queue:
            raise ValueError(
                "Extraction output must be queued for library prep "
                f"(expected={expected_queue!r} current_queue={current_queue!r})"
            )
        claim = self._resolve_stage_claim(
            material=source,
            expected_queues={expected_queue},
            claim_euid=payload.claim_euid,
            stage_label="library_prep",
        )

        process_item_context = self._resolve_process_item_context(source)
        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})
        lib_output = self._create_data_record(
            beta_kind="library_prep_output",
            name=payload.output_name
            or f"{payload.platform.lower()}-lib-prep:{source.euid}",
            properties={
                "platform": payload.platform,
                "idempotency_key": idempotency_key or "",
                "metadata": normalized_metadata,
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            source.euid,
            lib_output.euid,
            relationship_type="beta_library_prep_output",
        )
        self._replace_process_item_references(
            lib_output,
            atlas_context=process_item_context,
        )
        self._attach_execution_metadata_lineage(lib_output, normalized_metadata)
        transition = self._transition_material(
            material=lib_output,
            queue_name=self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
            metadata={"stage": "library_prep", **normalized_metadata},
            idempotency_key=f"{idempotency_key}:queue" if idempotency_key else None,
        )
        if payload.consume_source:
            self._consume_material_instance(
                source,
                reason="stage:library_prep",
                metadata={"stage": "library_prep", **normalized_metadata},
            )
        self._set_claim_status(
            claim,
            status="completed",
            reason="stage:library_prep",
            metadata={"stage": "library_prep"},
        )
        self._record_action(
            target_instance=lib_output,
            action_key="create_library_prep",
            captured_data={
                "source_extraction_output_euid": payload.source_extraction_output_euid,
                "platform": payload.platform,
                "output_name": payload.output_name,
                "metadata": normalized_metadata,
                "claim_euid": payload.claim_euid,
                "consume_source": bool(payload.consume_source),
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "source_extraction_output_euid": source.euid,
                "library_prep_output_euid": lib_output.euid,
                "current_queue": transition.current_queue,
            },
        )
        self.bdb.session.commit()
        return BetaLibraryPrepResponse(
            source_extraction_output_euid=source.euid,
            library_prep_output_euid=lib_output.euid,
            atlas_test_process_item_euid=process_item_context[
                "atlas_test_process_item_euid"
            ],
            current_queue=transition.current_queue,
            idempotent_replay=False,
        )

    def create_pool(
        self,
        *,
        payload: BetaPoolCreateRequest,
        idempotency_key: str | None,
    ) -> BetaPoolResponse:
        if idempotency_key:
            existing = self._find_content_record(
                beta_kind="sequencing_pool",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return BetaPoolResponse(
                    pool_euid=existing.euid,
                    pool_container_euid=self._linked_container_euid(existing) or "",
                    current_queue=self._current_queue_for_instance(existing) or "",
                    member_euids=self._member_euids_for_pool(existing),
                    idempotent_replay=True,
                )

        members = [self._require_instance(euid) for euid in payload.member_euids]
        expected_queue = self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform]
        claims = []
        if payload.claim_euid:
            if len(members) != 1:
                raise ValueError(
                    "claim_euid for pooling requires exactly one member; omit claim_euid "
                    "for multi-member pooling to use implicit claims"
                )
            claims.append(
                self._resolve_stage_claim(
                    material=members[0],
                    expected_queues={expected_queue},
                    claim_euid=payload.claim_euid,
                    stage_label="pool",
                )
            )
        else:
            for member in members:
                claims.append(
                    self._resolve_stage_claim(
                        material=member,
                        expected_queues={expected_queue},
                        claim_euid=None,
                        stage_label="pool",
                    )
                )
        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})

        pool = self.bobj.create_instance_by_code(
            self.POOL_TEMPLATE_CODE,
            {
                "json_addl": {
                    "properties": {
                        "beta_kind": "sequencing_pool",
                        "platform": payload.platform,
                        "member_count": len(members),
                        "idempotency_key": idempotency_key or "",
                        "metadata": normalized_metadata,
                    }
                }
            },
        )
        pool_props = self._props(pool)
        pool_name = payload.pool_name or f"{payload.platform.lower()}-pool"
        pool.name = pool_name
        pool_props["name"] = pool_name
        self._write_props(pool, pool_props)

        pool_container = self.bobj.create_instance_by_code(
            payload.pool_container_template_code or self.POOL_CONTAINER_TEMPLATE_CODE,
            {"json_addl": {"properties": {"name": f"{pool_name} tube"}}},
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            pool_container.euid,
            pool.euid,
            relationship_type="contains",
        )
        for member in members:
            self.bobj.create_generic_instance_lineage_by_euids(
                member.euid,
                pool.euid,
                relationship_type="beta_pool_member",
            )
        self._attach_execution_metadata_lineage(pool, normalized_metadata)

        transition = self._transition_material(
            material=pool,
            queue_name=self.START_RUN_QUEUE_BY_PLATFORM[payload.platform],
            metadata={"platform": payload.platform, **normalized_metadata},
            idempotency_key=f"{idempotency_key}:queue" if idempotency_key else None,
        )
        if payload.consume_members:
            for member in members:
                self._consume_material_instance(
                    member,
                    reason="stage:pool",
                    metadata={"stage": "pool", **normalized_metadata},
                )
        for claim in claims:
            self._set_claim_status(
                claim,
                status="completed",
                reason="stage:pool",
                metadata={"stage": "pool"},
            )
        self._record_action(
            target_instance=pool,
            action_key="create_pool",
            captured_data={
                "member_euids": [member.euid for member in members],
                "platform": payload.platform,
                "pool_name": payload.pool_name,
                "metadata": normalized_metadata,
                "claim_euid": payload.claim_euid,
                "consume_members": bool(payload.consume_members),
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "pool_euid": pool.euid,
                "pool_container_euid": pool_container.euid,
                "current_queue": transition.current_queue,
                "member_count": len(members),
            },
        )
        self.bdb.session.commit()
        return BetaPoolResponse(
            pool_euid=pool.euid,
            pool_container_euid=pool_container.euid,
            current_queue=transition.current_queue,
            member_euids=[member.euid for member in members],
            idempotent_replay=False,
        )

    def create_run(
        self,
        *,
        payload: BetaRunCreateRequest,
        idempotency_key: str | None,
    ) -> BetaRunResponse:
        if idempotency_key:
            existing = self._find_data_record(
                beta_kind="sequencing_run",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                existing_props = self._props(existing)
                return BetaRunResponse(
                    run_euid=existing.euid,
                    pool_euid=self._pool_euid_for_run(existing) or "",
                    flowcell_id=str(existing_props.get("flowcell_id") or ""),
                    run_folder=str(
                        existing_props.get("run_folder") or f"{existing.euid}/"
                    ),
                    status=str(existing_props.get("status") or ""),
                    artifact_count=self._count_children(existing, "beta_run_artifact"),
                    assignment_count=self._count_children(
                        existing, "beta_sequenced_library_assignment"
                    ),
                    idempotent_replay=True,
                )

        pool = self._require_instance(payload.pool_euid)
        self._assert_not_reserved(pool)
        self._assert_not_consumed(pool, stage_label="start_run")
        expected_queue = self.START_RUN_QUEUE_BY_PLATFORM[payload.platform]
        current_queue = self._current_queue_for_instance(pool)
        if current_queue != expected_queue:
            raise ValueError(
                "Pool must be queued to start sequencing "
                f"(expected={expected_queue!r} current_queue={current_queue!r})"
            )
        claim = self._resolve_stage_claim(
            material=pool,
            expected_queues={expected_queue},
            claim_euid=payload.claim_euid,
            stage_label="start_run",
        )
        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})

        run = self._create_data_record(
            beta_kind="sequencing_run",
            name=payload.run_name or f"{payload.platform.lower()}-run",
            properties={
                "platform": payload.platform,
                "flowcell_id": payload.flowcell_id,
                "status": payload.status,
                "idempotency_key": idempotency_key or "",
                "metadata": normalized_metadata,
            },
        )
        run_props = self._props(run)
        run_props["run_folder"] = f"{run.euid}/"
        self._write_props(run, run_props)
        self.bobj.create_generic_instance_lineage_by_euids(
            pool.euid,
            run.euid,
            relationship_type="beta_sequencing_run",
        )
        self._attach_execution_metadata_lineage(run, normalized_metadata)

        for assignment in payload.assignments:
            source = self._require_instance(assignment.library_prep_output_euid)
            process_item_context = self._resolve_process_item_context(source)
            assignment_record = self._create_data_record(
                beta_kind="sequenced_library_assignment",
                name=f"{run.euid}:{assignment.lane}:{assignment.library_barcode}",
                properties={
                    "flowcell_id": payload.flowcell_id,
                    "lane": assignment.lane,
                    "library_barcode": assignment.library_barcode,
                },
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                run.euid,
                assignment_record.euid,
                relationship_type="beta_sequenced_library_assignment",
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                source.euid,
                assignment_record.euid,
                relationship_type="beta_assignment_source",
            )
            self._replace_process_item_references(
                assignment_record,
                atlas_context=process_item_context,
            )

        for artifact in payload.artifacts:
            artifact_metadata = self.normalize_execution_metadata(artifact.metadata or {})
            artifact_record = self._create_data_record(
                beta_kind="run_artifact",
                name=f"{run.euid}:{artifact.artifact_type}:{artifact.filename}",
                properties={
                    "artifact_type": artifact.artifact_type,
                    "bucket": artifact.bucket,
                    "filename": artifact.filename,
                    "lane": artifact.lane or "",
                    "library_barcode": artifact.library_barcode or "",
                    "metadata": artifact_metadata,
                    "s3_key": f"{run.euid}/{artifact.filename}",
                    "s3_uri": f"s3://{artifact.bucket}/{run.euid}/{artifact.filename}",
                },
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                run.euid,
                artifact_record.euid,
                relationship_type="beta_run_artifact",
            )
            self._attach_execution_metadata_lineage(artifact_record, artifact_metadata)

        if payload.consume_pool:
            self._consume_material_instance(
                pool,
                reason="stage:start_run",
                metadata={"stage": "start_run", **normalized_metadata},
            )
        self._set_claim_status(
            claim,
            status="completed",
            reason="stage:start_run",
            metadata={"stage": "start_run"},
        )

        self._record_action(
            target_instance=run,
            action_key="create_run",
            captured_data={
                "pool_euid": payload.pool_euid,
                "platform": payload.platform,
                "flowcell_id": payload.flowcell_id,
                "run_name": payload.run_name,
                "status": payload.status,
                "metadata": normalized_metadata,
                "claim_euid": payload.claim_euid,
                "consume_pool": bool(payload.consume_pool),
                "assignments": [assignment.model_dump() for assignment in payload.assignments],
                "artifacts": [artifact.model_dump() for artifact in payload.artifacts],
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "run_euid": run.euid,
                "pool_euid": pool.euid,
                "assignment_count": len(payload.assignments),
                "artifact_count": len(payload.artifacts),
            },
        )
        self.bdb.session.commit()
        return BetaRunResponse(
            run_euid=run.euid,
            pool_euid=pool.euid,
            flowcell_id=payload.flowcell_id,
            run_folder=str(run_props["run_folder"]),
            status=payload.status,
            artifact_count=len(payload.artifacts),
            assignment_count=len(payload.assignments),
            idempotent_replay=False,
        )

    def resolve_run_assignment(
        self,
        *,
        run_euid: str,
        flowcell_id: str,
        lane: str,
        library_barcode: str,
    ) -> BetaRunResolutionResponse:
        run = self._require_instance(run_euid)
        normalized_flowcell_id = str(flowcell_id or "").strip()
        normalized_lane = str(lane or "").strip()
        normalized_library_barcode = str(library_barcode or "").strip()
        if not normalized_flowcell_id:
            raise ValueError("flowcell_id is required")
        if not normalized_lane:
            raise ValueError("lane is required")
        if not normalized_library_barcode:
            raise ValueError("library_barcode is required")

        for lineage in get_parent_lineages(run):
            if (
                lineage.is_deleted
                or lineage.relationship_type != "beta_sequenced_library_assignment"
            ):
                continue
            assignment = lineage.child_instance
            if assignment is None or assignment.is_deleted:
                continue
            props = self._props(assignment)
            if str(props.get("flowcell_id") or "").strip() != normalized_flowcell_id:
                continue
            if str(props.get("lane") or "").strip() != normalized_lane:
                continue
            if (
                str(props.get("library_barcode") or "").strip()
                != normalized_library_barcode
            ):
                continue
            process_item_context = self._resolve_process_item_context(assignment)
            return BetaRunResolutionResponse(
                run_euid=run.euid,
                flowcell_id=normalized_flowcell_id,
                lane=normalized_lane,
                library_barcode=normalized_library_barcode,
                sequenced_library_assignment_euid=assignment.euid,
                atlas_tenant_id=process_item_context["atlas_tenant_id"],
                atlas_trf_euid=process_item_context["atlas_trf_euid"],
                atlas_test_euid=process_item_context["atlas_test_euid"],
                atlas_test_process_item_euid=process_item_context[
                    "atlas_test_process_item_euid"
                ],
            )

        raise ValueError(
            "Sequenced library assignment not found for "
            f"run_euid={run_euid} flowcell_id={normalized_flowcell_id} "
            f"lane={normalized_lane} library_barcode={normalized_library_barcode}"
        )

    def _transition_material(
        self,
        *,
        material,
        queue_name: str,
        metadata: dict[str, Any],
        idempotency_key: str | None,
        replay: bool = False,
    ) -> BetaQueueTransitionResponse:
        normalized_queue = str(queue_name or "").strip()
        if normalized_queue not in self.CANONICAL_QUEUES:
            raise ValueError(f"Unsupported beta queue: {queue_name}")

        normalized_metadata = self.normalize_execution_metadata(metadata or {})
        queue_def = self._ensure_queue_definition(normalized_queue)
        previous_queue = self._current_queue_for_instance(material)
        self._retire_queue_memberships(material)
        self.bobj.create_generic_instance_lineage_by_euids(
            queue_def.euid,
            material.euid,
            relationship_type=self.REL_QUEUE_MEMBERSHIP,
        )

        props = self._props(material)
        props["current_queue"] = normalized_queue
        props["queue_updated_at"] = self._timestamp()
        self._write_props(material, props)
        self._close_open_work_items(material, except_queue=normalized_queue)
        self._upsert_open_work_item(
            material=material,
            queue_def=queue_def,
            queue_name=normalized_queue,
            metadata=normalized_metadata,
        )

        queue_event = self._create_data_record(
            beta_kind=self.BETA_KIND_QUEUE_EVENT,
            name=f"{normalized_queue}:{material.euid}",
            properties={
                "queue_name": normalized_queue,
                "previous_queue": previous_queue or "",
                "idempotency_key": idempotency_key or "",
                "metadata": normalized_metadata,
                "occurred_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            material.euid,
            queue_event.euid,
            relationship_type=self.REL_QUEUE_EVENT,
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            queue_def.euid,
            queue_event.euid,
            relationship_type=self.REL_QUEUE_EVENT_QUEUE,
        )
        self._attach_execution_metadata_lineage(queue_event, normalized_metadata)
        self.bdb.session.flush()
        return BetaQueueTransitionResponse(
            material_euid=material.euid,
            queue_euid=queue_def.euid,
            queue_name=normalized_queue,
            previous_queue=previous_queue,
            current_queue=normalized_queue,
            idempotent_replay=replay,
        )

    def _queue_transition_response_from_event(
        self,
        event,
        *,
        replay: bool,
    ) -> BetaQueueTransitionResponse:
        props = self._props(event)
        material = self._first_parent(event, self.REL_QUEUE_EVENT)
        queue = self._first_parent(event, self.REL_QUEUE_EVENT_QUEUE)
        return BetaQueueTransitionResponse(
            material_euid=material.euid if material is not None else "",
            queue_euid=queue.euid if queue is not None else "",
            queue_name=str(props.get("queue_name") or ""),
            previous_queue=str(props.get("previous_queue") or "") or None,
            current_queue=str(props.get("queue_name") or ""),
            idempotent_replay=replay,
        )

    def normalize_execution_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        raw = metadata if isinstance(metadata, dict) else {}
        normalized: dict[str, Any] = {}
        for key, value in raw.items():
            if value is None:
                continue
            if isinstance(value, str):
                clean_value = value.strip()
                if not clean_value:
                    continue
                normalized[key] = clean_value
                continue
            normalized[key] = value

        operator = normalized.get("operator")
        if operator is not None and not isinstance(operator, str):
            raise ValueError("metadata.operator must be a string when provided")
        method_version = normalized.get("method_version")
        if method_version is not None and not isinstance(method_version, str):
            raise ValueError("metadata.method_version must be a string when provided")

        instrument_euid = normalized.get("instrument_euid")
        if instrument_euid is not None:
            instrument = self._require_instance(str(instrument_euid))
            if instrument.category != "equipment":
                raise ValueError(
                    "metadata.instrument_euid must reference an equipment object"
                )
            normalized["instrument_euid"] = instrument.euid

        reagent_euid = normalized.get("reagent_euid")
        if reagent_euid is not None:
            reagent = self._require_instance(str(reagent_euid))
            if reagent.category != "content" or (
                str(reagent.type or "").strip() != "reagent"
                and "reagent" not in str(reagent.subtype or "").strip()
            ):
                raise ValueError(
                    "metadata.reagent_euid must reference a reagent content object"
                )
            normalized["reagent_euid"] = reagent.euid

        return normalized

    def _attach_execution_metadata_lineage(
        self,
        target_instance,
        metadata: dict[str, Any] | None,
    ) -> None:
        payload = metadata if isinstance(metadata, dict) else {}
        instrument_euid = str(payload.get("instrument_euid") or "").strip()
        if instrument_euid:
            instrument = self._require_instance(instrument_euid)
            self.bobj.create_generic_instance_lineage_by_euids(
                target_instance.euid,
                instrument.euid,
                relationship_type=self.REL_USED_INSTRUMENT,
            )
        reagent_euid = str(payload.get("reagent_euid") or "").strip()
        if reagent_euid:
            reagent = self._require_instance(reagent_euid)
            self.bobj.create_generic_instance_lineage_by_euids(
                target_instance.euid,
                reagent.euid,
                relationship_type=self.REL_USED_REAGENT,
            )

    def _is_data_kind(self, instance, beta_kind: str) -> bool:
        if instance is None or instance.is_deleted:
            return False
        if instance.category != "generic" or instance.type != "generic" or instance.subtype != "generic":
            return False
        return str(self._props(instance).get("beta_kind") or "").strip() == str(beta_kind).strip()

    def _work_items_for_material(self, material) -> list[Any]:
        items: list[Any] = []
        for lineage in get_parent_lineages(material):
            if lineage.is_deleted or lineage.relationship_type != self.REL_WORK_ITEM_SUBJECT:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted or not self._is_data_kind(child, self.BETA_KIND_WORK_ITEM):
                continue
            items.append(child)
        return items

    def _close_open_work_items(
        self,
        material,
        *,
        except_queue: str | None = None,
    ) -> None:
        for work_item in self._work_items_for_material(material):
            props = self._props(work_item)
            status = str(props.get("status") or "").strip().lower()
            queue_name = str(props.get("queue_name") or "").strip()
            if status not in {"open", "active"}:
                continue
            if except_queue and queue_name == except_queue:
                continue
            props["status"] = "closed"
            props["closed_at"] = self._timestamp()
            props["close_reason"] = "queue_transition"
            self._write_props(work_item, props)

    def _upsert_open_work_item(
        self,
        *,
        material,
        queue_def,
        queue_name: str,
        metadata: dict[str, Any] | None,
    ):
        for work_item in self._work_items_for_material(material):
            props = self._props(work_item)
            status = str(props.get("status") or "").strip().lower()
            item_queue = str(props.get("queue_name") or "").strip()
            if status in {"open", "active"} and item_queue == queue_name:
                props["status"] = "open"
                props["last_seen_at"] = self._timestamp()
                props["metadata"] = metadata or {}
                self._write_props(work_item, props)
                return work_item

        work_item = self._create_data_record(
            beta_kind=self.BETA_KIND_WORK_ITEM,
            name=f"work-item:{queue_name}:{material.euid}",
            properties={
                "material_euid": material.euid,
                "queue_name": queue_name,
                "status": "open",
                "metadata": metadata or {},
                "opened_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            queue_def.euid,
            work_item.euid,
            relationship_type=self.REL_QUEUE_WORK_ITEM,
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            material.euid,
            work_item.euid,
            relationship_type=self.REL_WORK_ITEM_SUBJECT,
        )
        self._attach_execution_metadata_lineage(work_item, metadata or {})
        return work_item

    def _require_open_work_item(
        self,
        *,
        material,
        expected_queue: str,
    ):
        queue_name = str(expected_queue or "").strip()
        for work_item in self._work_items_for_material(material):
            props = self._props(work_item)
            if str(props.get("queue_name") or "").strip() != queue_name:
                continue
            status = str(props.get("status") or "").strip().lower()
            if status not in {"open", "active"}:
                continue
            return work_item
        queue_def = self._ensure_queue_definition(queue_name)
        return self._upsert_open_work_item(
            material=material,
            queue_def=queue_def,
            queue_name=queue_name,
            metadata={},
        )

    def _active_claim_for_work_item(self, work_item):
        for lineage in get_parent_lineages(work_item):
            if lineage.is_deleted or lineage.relationship_type != self.REL_WORK_ITEM_CLAIM:
                continue
            claim = lineage.child_instance
            if claim is None or claim.is_deleted or not self._is_data_kind(claim, self.BETA_KIND_CLAIM):
                continue
            status = str(self._props(claim).get("status") or "").strip().lower()
            if status == "active":
                return claim
        return None

    def _active_reservation_for_material(self, material):
        for lineage in get_parent_lineages(material):
            if lineage.is_deleted or lineage.relationship_type != self.REL_MATERIAL_RESERVATION:
                continue
            reservation = lineage.child_instance
            if (
                reservation is None
                or reservation.is_deleted
                or not self._is_data_kind(reservation, self.BETA_KIND_RESERVATION)
            ):
                continue
            status = str(self._props(reservation).get("status") or "").strip().lower()
            if status == "active":
                return reservation
        return None

    def _assert_not_reserved(self, material) -> None:
        active_reservation = self._active_reservation_for_material(material)
        if active_reservation is not None:
            raise ValueError(
                "Material has an active reservation and cannot be claimed or staged "
                f"(reservation_euid={active_reservation.euid})"
            )

    def _is_consumed(self, material) -> bool:
        props = self._props(material)
        consumed_event = str(props.get("consumed_event_euid") or "").strip()
        if consumed_event:
            return True
        for lineage in get_parent_lineages(material):
            if lineage.is_deleted or lineage.relationship_type != self.REL_MATERIAL_CONSUMPTION:
                continue
            event = lineage.child_instance
            if event is None or event.is_deleted:
                continue
            if self._is_data_kind(event, self.BETA_KIND_CONSUMPTION_EVENT):
                return True
        return False

    def _assert_not_consumed(self, material, *, stage_label: str) -> None:
        if self._is_consumed(material):
            raise ValueError(
                "Consumed material cannot be reused for stage operations "
                f"(stage={stage_label} material_euid={material.euid})"
            )

    def _create_claim_record(
        self,
        *,
        material,
        queue_name: str,
        work_item,
        metadata: dict[str, Any],
        idempotency_key: str | None,
        implicit: bool,
    ):
        metadata_payload = self.normalize_execution_metadata(metadata or {})
        claim = self._create_data_record(
            beta_kind=self.BETA_KIND_CLAIM,
            name=f"claim:{queue_name}:{material.euid}",
            properties={
                "material_euid": material.euid,
                "queue_name": queue_name,
                "work_item_euid": work_item.euid,
                "status": "active",
                "metadata": metadata_payload,
                "idempotency_key": idempotency_key or "",
                "implicit": bool(implicit),
                "claimed_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            work_item.euid,
            claim.euid,
            relationship_type=self.REL_WORK_ITEM_CLAIM,
        )
        self._attach_execution_metadata_lineage(claim, metadata_payload)
        return claim

    def _set_claim_status(
        self,
        claim,
        *,
        status: str,
        reason: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        claim_props = self._props(claim)
        claim_props["status"] = str(status or "").strip() or "completed"
        claim_props["released_at"] = self._timestamp()
        claim_props["release_reason"] = str(reason or "").strip()
        claim_props["release_metadata"] = self.normalize_execution_metadata(metadata or {})
        self._write_props(claim, claim_props)

    def _resolve_stage_claim(
        self,
        *,
        material,
        expected_queues: set[str],
        claim_euid: str | None,
        stage_label: str,
    ):
        self._assert_not_reserved(material)
        self._assert_not_consumed(material, stage_label=stage_label)
        current_queue = self._current_queue_for_instance(material)
        if current_queue not in expected_queues:
            expected = ", ".join(sorted(expected_queues))
            raise ValueError(
                f"Source material must be queued in one of [{expected}] "
                f"(current_queue={current_queue!r})"
            )
        if claim_euid:
            claim = self._require_instance(claim_euid)
            if not self._is_data_kind(claim, self.BETA_KIND_CLAIM):
                raise ValueError(f"Bloom claim not found: {claim_euid}")
            claim_props = self._props(claim)
            claim_status = str(claim_props.get("status") or "").strip().lower()
            if claim_status != "active":
                raise ValueError(
                    f"Claim is not active and cannot be used: {claim_euid}"
                )
            work_item = self._first_parent(claim, self.REL_WORK_ITEM_CLAIM)
            if work_item is None:
                raise ValueError(f"Claim is not linked to a work item: {claim_euid}")
            claim_material = self._first_parent(work_item, self.REL_WORK_ITEM_SUBJECT)
            if claim_material is None or claim_material.euid != material.euid:
                raise ValueError(
                    "claim_euid does not match source material "
                    f"(claim_euid={claim_euid} material_euid={material.euid})"
                )
            claim_queue = str(claim_props.get("queue_name") or "").strip()
            if claim_queue != current_queue:
                raise ValueError(
                    "claim_euid queue does not match source queue "
                    f"(claim_queue={claim_queue!r} current_queue={current_queue!r})"
                )
            return claim

        work_item = self._require_open_work_item(material=material, expected_queue=current_queue or "")
        active_claim = self._active_claim_for_work_item(work_item)
        if active_claim is not None:
            raise ValueError(
                "Source material already has an active claim; supply claim_euid explicitly "
                f"(claim_euid={active_claim.euid})"
            )
        return self._create_claim_record(
            material=material,
            queue_name=current_queue or "",
            work_item=work_item,
            metadata={"stage": stage_label, "implicit_claim": True},
            idempotency_key=None,
            implicit=True,
        )

    def _consume_material_instance(
        self,
        material,
        *,
        reason: str,
        metadata: dict[str, Any] | None,
    ):
        if self._is_consumed(material):
            raise ValueError(f"Material is already consumed: {material.euid}")
        metadata_payload = self.normalize_execution_metadata(metadata or {})
        event = self._create_data_record(
            beta_kind=self.BETA_KIND_CONSUMPTION_EVENT,
            name=f"consumption:{material.euid}",
            properties={
                "material_euid": material.euid,
                "reason": str(reason or "").strip(),
                "idempotency_key": "",
                "metadata": metadata_payload,
                "occurred_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            material.euid,
            event.euid,
            relationship_type=self.REL_MATERIAL_CONSUMPTION,
        )
        self._attach_execution_metadata_lineage(event, metadata_payload)
        material_props = self._props(material)
        material_props["consumed_at"] = self._timestamp()
        material_props["consumed_event_euid"] = event.euid
        self._write_props(material, material_props)
        return event

    def _claim_response(self, claim, *, replay: bool) -> BetaClaimResponse:
        claim_props = self._props(claim)
        work_item = self._first_parent(claim, self.REL_WORK_ITEM_CLAIM)
        material = (
            self._first_parent(work_item, self.REL_WORK_ITEM_SUBJECT)
            if work_item is not None
            else None
        )
        return BetaClaimResponse(
            claim_euid=claim.euid,
            material_euid=material.euid if material is not None else str(claim_props.get("material_euid") or ""),
            queue_name=str(claim_props.get("queue_name") or ""),
            work_item_euid=work_item.euid if work_item is not None else str(claim_props.get("work_item_euid") or ""),
            status=str(claim_props.get("status") or ""),
            metadata=claim_props.get("metadata") if isinstance(claim_props.get("metadata"), dict) else {},
            idempotent_replay=replay,
        )

    def _reservation_response(self, reservation, *, replay: bool) -> BetaReservationResponse:
        reservation_props = self._props(reservation)
        material = self._first_parent(reservation, self.REL_MATERIAL_RESERVATION)
        return BetaReservationResponse(
            reservation_euid=reservation.euid,
            material_euid=material.euid if material is not None else str(reservation_props.get("material_euid") or ""),
            status=str(reservation_props.get("status") or ""),
            metadata=(
                reservation_props.get("metadata")
                if isinstance(reservation_props.get("metadata"), dict)
                else {}
            ),
            idempotent_replay=replay,
        )

    def _consumption_response(
        self,
        consumption_event,
        *,
        replay: bool,
    ) -> BetaConsumeMaterialResponse:
        props = self._props(consumption_event)
        material = self._first_parent(consumption_event, self.REL_MATERIAL_CONSUMPTION)
        return BetaConsumeMaterialResponse(
            consumption_event_euid=consumption_event.euid,
            material_euid=material.euid if material is not None else str(props.get("material_euid") or ""),
            consumed=True,
            metadata=props.get("metadata") if isinstance(props.get("metadata"), dict) else {},
            idempotent_replay=replay,
        )

    def _extraction_response(
        self, extraction_output, *, replay: bool
    ) -> BetaExtractionResponse:
        source = self._first_parent(extraction_output, "beta_extraction_output")
        well = self._first_parent(extraction_output, "contains")
        plate = self._first_parent(well, "contains") if well is not None else None
        process_item_context = self._resolve_process_item_context(extraction_output)
        return BetaExtractionResponse(
            source_specimen_euid=source.euid if source is not None else "",
            plate_euid=plate.euid if plate is not None else "",
            well_euid=well.euid if well is not None else "",
            well_name=self._well_name(well),
            extraction_output_euid=extraction_output.euid,
            atlas_test_process_item_euid=process_item_context[
                "atlas_test_process_item_euid"
            ],
            current_queue=self._current_queue_for_instance(extraction_output) or "",
            idempotent_replay=replay,
        )

    def _resolve_or_create_plate(
        self,
        *,
        plate_euid: str | None,
        plate_template_code: str,
        plate_name: str | None,
    ):
        if plate_euid:
            plate = self._require_instance(plate_euid)
            if plate.category != "container":
                raise ValueError(f"EUID is not a container plate: {plate_euid}")
            return plate

        template = self._require_template(plate_template_code)
        created = self.bobj.create_instances(template.euid)
        plate = created[0][0]
        props = self._props(plate)
        resolved_name = plate_name or props.get("name") or plate.name
        if resolved_name:
            plate.name = str(resolved_name)
            props["name"] = str(resolved_name)
            self._write_props(plate, props)
        return plate

    def _resolve_or_create_container(
        self,
        *,
        container_euid: str | None,
        container_template_code: str,
        specimen_name: str,
    ):
        if container_euid:
            container = self._require_instance(container_euid)
            if container.category != "container":
                raise ValueError(f"EUID is not a container: {container_euid}")
            return container

        container = self.bobj.create_instance_by_code(
            container_template_code,
            {"json_addl": {"properties": {"name": f"{specimen_name} container"}}},
        )
        if container is None:
            raise ValueError("Failed to create container for specimen")
        return container

    def _ensure_container_link(self, container_euid: str, specimen_euid: str) -> None:
        container = self._require_instance(container_euid)
        specimen = self._require_instance(specimen_euid)
        for lineage in get_parent_lineages(container):
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if child.uid == specimen.uid and lineage.relationship_type == "contains":
                return
        self.bobj.create_generic_instance_lineage_by_euids(
            container_euid,
            specimen_euid,
            relationship_type="contains",
        )

    def _require_plate_well(self, plate, well_name: str):
        expected = str(well_name or "").strip().upper()
        for lineage in get_parent_lineages(plate):
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted or child.category != "container":
                continue
            address = (
                child.json_addl.get("cont_address")
                if isinstance(child.json_addl, dict)
                else {}
            )
            candidate = str((address or {}).get("name") or "").strip().upper()
            if not candidate:
                candidate = str(self._props(child).get("name") or "").strip().upper()
            if candidate == expected:
                return child
        raise ValueError(f"Well not found on plate {plate.euid}: {well_name}")

    def _ensure_queue_definition(self, queue_name: str):
        existing = self._find_data_record_by_property(
            beta_kind=self.BETA_KIND_QUEUE_DEFINITION,
            property_key="queue_name",
            expected=queue_name,
        )
        if existing is not None:
            return existing

        return self._create_data_record(
            beta_kind=self.BETA_KIND_QUEUE_DEFINITION,
            name=queue_name,
            properties={"queue_name": queue_name},
        )

    def _retire_queue_memberships(self, material) -> None:
        for lineage in get_child_lineages(material):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.REL_QUEUE_MEMBERSHIP
            ):
                continue
            lineage.is_deleted = True

    def _current_queue_for_instance(self, instance) -> str | None:
        props = self._props(instance)
        current_queue = str(props.get("current_queue") or "").strip()
        if current_queue:
            return current_queue
        for lineage in get_child_lineages(instance):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.REL_QUEUE_MEMBERSHIP
            ):
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted:
                continue
            parent_props = self._props(parent)
            queue_name = str(parent_props.get("queue_name") or "").strip()
            if queue_name:
                return queue_name
        # Queue membership is tracked on the physical container for ingress material.
        # If content lacks direct queue state, fall back to its containing container.
        for lineage in get_child_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != "contains":
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted or parent.category != "container":
                continue
            container_queue = self._current_queue_for_instance(parent)
            if container_queue:
                return container_queue
        return None

    def _resolve_process_item_context(
        self,
        instance,
        *,
        target_process_item_euid: str | None = None,
    ) -> dict[str, str]:
        matches = {
            ref["atlas_test_process_item_euid"]: ref
            for ref in self._reachable_process_item_refs(instance)
        }
        target = str(target_process_item_euid or "").strip()
        if target:
            if target in matches:
                return matches[target]
            raise ValueError(
                "No Atlas test process item could be resolved from "
                f"Bloom lineage for {instance.euid}: {target}"
            )
        if len(matches) == 1:
            return next(iter(matches.values()))
        if len(matches) > 1:
            raise ValueError(
                "Multiple Atlas test process items are reachable from "
                f"{instance.euid}; choose one explicitly before sequencing"
            )
        raise ValueError(
            "No Atlas test process item could be resolved from "
            f"Bloom lineage for {instance.euid}"
        )

    def _reachable_process_item_refs(self, instance) -> list[dict[str, str]]:
        visited: set[int] = set()
        to_visit = [instance]
        refs: dict[str, dict[str, str]] = {}
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)
            for ref in self._process_item_refs_for_instance(current):
                refs[ref["atlas_test_process_item_euid"]] = ref
            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)
        return list(refs.values())

    def _process_item_refs_for_instance(self, instance) -> list[dict[str, str]]:
        refs: dict[str, dict[str, str]] = {}
        for payload in self._atlas_reference_payloads_for_instance(instance):
            ref_type = str(payload.get("reference_type") or "").strip()
            if ref_type != self.PROCESS_ITEM_REFERENCE_TYPE:
                continue
            process_item_euid = str(payload.get("atlas_test_process_item_euid") or "").strip()
            atlas_test_euid = str(payload.get("atlas_test_euid") or "").strip()
            atlas_tenant_id = str(payload.get("atlas_tenant_id") or "").strip()
            atlas_trf_euid = str(payload.get("atlas_trf_euid") or "").strip()
            if not (
                process_item_euid
                and atlas_test_euid
                and atlas_tenant_id
                and atlas_trf_euid
            ):
                continue
            refs[process_item_euid] = {
                "atlas_tenant_id": atlas_tenant_id,
                "atlas_trf_euid": atlas_trf_euid,
                "atlas_test_euid": atlas_test_euid,
                "atlas_test_process_item_euid": process_item_euid,
            }
        return list(refs.values())

    def _atlas_reference_payloads_for_instance(self, instance) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for lineage in get_parent_lineages(instance):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.EXTERNAL_REFERENCE_RELATIONSHIP
            ):
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

    def _patient_ref_for_instance(self, instance) -> dict[str, str] | None:
        for payload in self._atlas_reference_payloads_for_instance(instance):
            ref_type = str(payload.get("reference_type") or "").strip()
            if ref_type != self.PATIENT_REFERENCE_TYPE:
                continue
            atlas_patient_euid = str(payload.get("atlas_patient_euid") or "").strip()
            if not atlas_patient_euid:
                atlas_patient_euid = str(payload.get("reference_value") or "").strip()
            atlas_tenant_id = str(payload.get("atlas_tenant_id") or "").strip()
            if not (atlas_patient_euid and atlas_tenant_id):
                continue
            return {
                "atlas_tenant_id": atlas_tenant_id,
                "atlas_patient_euid": atlas_patient_euid,
            }
        return None

    def _collection_event_ref_for_instance(self, instance) -> dict[str, Any] | None:
        for payload in self._atlas_reference_payloads_for_instance(instance):
            ref_type = str(payload.get("reference_type") or "").strip()
            if ref_type != self.COLLECTION_EVENT_REFERENCE_TYPE:
                continue
            collection_event_euid = str(
                payload.get("atlas_collection_event_euid") or payload.get("reference_value") or ""
            ).strip()
            atlas_tenant_id = str(payload.get("atlas_tenant_id") or "").strip()
            if not (collection_event_euid and atlas_tenant_id):
                continue
            snapshot = payload.get("collection_event_snapshot")
            return {
                "atlas_tenant_id": atlas_tenant_id,
                "atlas_collection_event_euid": collection_event_euid,
                "collection_event_snapshot": snapshot if isinstance(snapshot, dict) else {},
            }
        return None

    @staticmethod
    def _has_collection_event_context(atlas_context: dict[str, Any]) -> bool:
        collection_event_euid = str(atlas_context.get("atlas_collection_event_euid") or "").strip()
        if collection_event_euid:
            return True
        snapshot = atlas_context.get("collection_event_snapshot")
        return bool(
            isinstance(snapshot, dict)
            and str(snapshot.get("collection_event_euid") or "").strip()
        )

    def _replace_process_item_references(self, instance, *, atlas_context: dict[str, Any]) -> None:
        self._delete_reference_type(
            instance,
            reference_type=self.PROCESS_ITEM_REFERENCE_TYPE,
        )

        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        atlas_trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()
        process_items = list(atlas_context.get("process_items") or [])

        for process_item in process_items:
            atlas_test_euid = str(process_item.get("atlas_test_euid") or "").strip()
            atlas_test_process_item_euid = str(
                process_item.get("atlas_test_process_item_euid") or ""
            ).strip()
            if not (
                atlas_tenant_id
                and atlas_trf_euid
                and atlas_test_euid
                and atlas_test_process_item_euid
            ):
                continue
            ref_obj = self.bobj.create_instance_by_code(
                self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                {
                    "json_addl": {
                        "properties": {
                            "provider": "atlas",
                            "reference_type": self.PROCESS_ITEM_REFERENCE_TYPE,
                            "reference_value": atlas_test_process_item_euid,
                            "foreign_reference": atlas_test_process_item_euid,
                            "atlas_tenant_id": atlas_tenant_id,
                            "atlas_trf_euid": atlas_trf_euid,
                            "atlas_test_euid": atlas_test_euid,
                            "atlas_test_process_item_euid": atlas_test_process_item_euid,
                            "validation": {},
                        }
                    }
                },
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                instance.euid,
                ref_obj.euid,
                relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
            )

    def _replace_container_entity_references(
        self,
        instance,
        *,
        atlas_context: dict[str, Any],
    ) -> None:
        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        atlas_trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()
        atlas_test_euid = str(atlas_context.get("atlas_test_euid") or "").strip()
        atlas_test_euids: list[str] = []
        seen_tests: set[str] = set()
        if atlas_test_euid:
            seen_tests.add(atlas_test_euid)
            atlas_test_euids.append(atlas_test_euid)
        for value in list(atlas_context.get("atlas_test_euids") or []):
            clean_value = str(value or "").strip()
            if not clean_value or clean_value in seen_tests:
                continue
            seen_tests.add(clean_value)
            atlas_test_euids.append(clean_value)
        process_items = list(atlas_context.get("process_items") or [])
        for process_item in process_items:
            candidate = str(process_item.get("atlas_test_euid") or "").strip()
            if not candidate or candidate in seen_tests:
                continue
            seen_tests.add(candidate)
            atlas_test_euids.append(candidate)
        if not atlas_test_euid and atlas_test_euids:
            atlas_test_euid = atlas_test_euids[0]
        reference_fields = (
            (self.TRF_REFERENCE_TYPE, "atlas_trf_euid"),
            (self.TESTKIT_REFERENCE_TYPE, "atlas_testkit_euid"),
            (self.SHIPMENT_REFERENCE_TYPE, "atlas_shipment_euid"),
            (self.ORGANIZATION_SITE_REFERENCE_TYPE, "atlas_organization_site_euid"),
        )
        self._delete_reference_type(instance, reference_type=self.TEST_REFERENCE_TYPE)
        if atlas_tenant_id:
            for reference_value in atlas_test_euids:
                properties = {
                    "provider": "atlas",
                    "reference_type": self.TEST_REFERENCE_TYPE,
                    "reference_value": reference_value,
                    "foreign_reference": reference_value,
                    "atlas_tenant_id": atlas_tenant_id,
                    "atlas_test_euid": reference_value,
                    "validation": {},
                }
                if atlas_trf_euid:
                    properties["atlas_trf_euid"] = atlas_trf_euid
                ref_obj = self.bobj.create_instance_by_code(
                    self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                    {"json_addl": {"properties": properties}},
                )
                self.bobj.create_generic_instance_lineage_by_euids(
                    instance.euid,
                    ref_obj.euid,
                    relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
                )
        for reference_type, field_name in reference_fields:
            self._delete_reference_type(instance, reference_type=reference_type)
            if not atlas_tenant_id:
                continue
            reference_value = str(atlas_context.get(field_name) or "").strip()
            if not reference_value:
                continue
            properties = {
                "provider": "atlas",
                "reference_type": reference_type,
                "reference_value": reference_value,
                "foreign_reference": reference_value,
                "atlas_tenant_id": atlas_tenant_id,
                "validation": {},
            }
            if atlas_trf_euid:
                properties["atlas_trf_euid"] = atlas_trf_euid
            properties[field_name] = reference_value
            ref_obj = self.bobj.create_instance_by_code(
                self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                {"json_addl": {"properties": properties}},
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                instance.euid,
                ref_obj.euid,
                relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
            )

    def _replace_collection_event_reference(self, instance, *, atlas_context: dict[str, Any]) -> None:
        self._delete_reference_type(
            instance,
            reference_type=self.COLLECTION_EVENT_REFERENCE_TYPE,
        )
        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        collection_event_euid = str(atlas_context.get("atlas_collection_event_euid") or "").strip()
        if not collection_event_euid:
            snapshot = atlas_context.get("collection_event_snapshot")
            if isinstance(snapshot, dict):
                collection_event_euid = str(snapshot.get("collection_event_euid") or "").strip()
        if not (atlas_tenant_id and collection_event_euid):
            return
        snapshot_payload = atlas_context.get("collection_event_snapshot")
        if not isinstance(snapshot_payload, dict):
            snapshot_payload = {}
        ref_obj = self.bobj.create_instance_by_code(
            self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
            {
                "json_addl": {
                    "properties": {
                        "provider": "atlas",
                        "reference_type": self.COLLECTION_EVENT_REFERENCE_TYPE,
                        "reference_value": collection_event_euid,
                        "foreign_reference": collection_event_euid,
                        "atlas_tenant_id": atlas_tenant_id,
                        "atlas_collection_event_euid": collection_event_euid,
                        "atlas_trf_euid": str(atlas_context.get("atlas_trf_euid") or "").strip(),
                        "collection_event_snapshot": snapshot_payload,
                        "validation": {},
                    }
                }
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            instance.euid,
            ref_obj.euid,
            relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
        )

    def _replace_patient_reference(self, instance, *, atlas_context: dict[str, Any]) -> None:
        self._delete_reference_type(
            instance,
            reference_type=self.PATIENT_REFERENCE_TYPE,
        )
        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        atlas_patient_euid = str(atlas_context.get("atlas_patient_euid") or "").strip()
        atlas_trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()
        if not (atlas_tenant_id and atlas_patient_euid):
            return
        ref_obj = self.bobj.create_instance_by_code(
            self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
            {
                "json_addl": {
                    "properties": {
                        "provider": "atlas",
                        "reference_type": self.PATIENT_REFERENCE_TYPE,
                        "reference_value": atlas_patient_euid,
                        "foreign_reference": atlas_patient_euid,
                        "atlas_tenant_id": atlas_tenant_id,
                        "atlas_patient_euid": atlas_patient_euid,
                        "atlas_trf_euid": atlas_trf_euid,
                        "validation": {},
                    }
                }
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            instance.euid,
            ref_obj.euid,
            relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
        )

    def _delete_reference_type(self, instance, *, reference_type: str) -> None:
        existing_refs = []
        for lineage in get_parent_lineages(instance):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.EXTERNAL_REFERENCE_RELATIONSHIP
            ):
                continue
            child = lineage.child_instance
            if child is None:
                continue
            existing_refs.append((lineage, child))

        for lineage, child in existing_refs:
            payload = self._props(child)
            if str(payload.get("reference_type") or "").strip() != str(reference_type).strip():
                continue
            lineage.is_deleted = True
            child.is_deleted = True

    def _find_operation_record(self, *, beta_kind: str, idempotency_key: str):
        return self._find_data_record_by_property(
            beta_kind=beta_kind,
            property_key="idempotency_key",
            expected=idempotency_key,
        )

    def _find_data_record(self, *, beta_kind: str, idempotency_key: str):
        return self._find_data_record_by_property(
            beta_kind=beta_kind,
            property_key="idempotency_key",
            expected=idempotency_key,
        )

    def _find_content_record(self, *, beta_kind: str, idempotency_key: str):
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "content",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "beta_kind",
                )
                == beta_kind,
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "idempotency_key",
                )
                == str(idempotency_key).strip(),
            )
            .first()
        )

    def _find_container_record(self, *, beta_kind: str, idempotency_key: str):
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "container",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "beta_kind",
                )
                == beta_kind,
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "idempotency_key",
                )
                == str(idempotency_key).strip(),
            )
            .first()
        )

    def _find_data_record_by_property(
        self,
        *,
        beta_kind: str,
        property_key: str,
        expected: str,
    ):
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "generic",
                self.bdb.Base.classes.generic_instance.type == "generic",
                self.bdb.Base.classes.generic_instance.subtype == "generic",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "beta_kind",
                )
                == beta_kind,
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    property_key,
                )
                == str(expected).strip(),
            )
            .first()
        )

    def _create_data_record(
        self,
        *,
        beta_kind: str,
        name: str,
        properties: dict[str, Any],
    ):
        payload = {"beta_kind": beta_kind, **(properties or {})}
        record = self.bobj.create_instance_by_code(
            self.GENERIC_DATA_TEMPLATE_CODE,
            {"json_addl": {"properties": payload}},
        )
        props = self._props(record)
        record.name = name
        props["name"] = name
        self._write_props(record, props)
        return record

    def _linked_container_euid(self, instance) -> str | None:
        for lineage in get_child_lineages(instance):
            if lineage.is_deleted:
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted or parent.category != "container":
                continue
            return parent.euid
        return None

    def _record_action(
        self,
        *,
        target_instance,
        action_key: str,
        captured_data: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self.action_recorder.record(
            target_instance=target_instance,
            action_key=action_key,
            captured_data=captured_data,
            result=result,
            executed_by=self.bdb.app_username,
        )

    def _material_response(self, specimen, *, created: bool) -> BetaMaterialResponse:
        return BetaMaterialResponse(
            specimen_euid=specimen.euid,
            container_euid=self._linked_container_euid(specimen),
            status=specimen.bstatus,
            atlas_context=self._atlas_context_for_instance(specimen),
            properties=self._props(specimen),
            idempotency_key=str(self._props(specimen).get("idempotency_key") or "") or None,
            current_queue=self._current_queue_for_instance(specimen),
            created=created,
        )

    def _tube_response(self, container, *, created: bool):
        return {
            "container_euid": container.euid,
            "status": container.bstatus,
            "atlas_context": self._atlas_context_for_instance(container),
            "properties": self._props(container),
            "idempotency_key": str(self._props(container).get("idempotency_key") or "") or None,
            "current_queue": self._current_queue_for_instance(container),
            "created": created,
        }

    def _atlas_context_for_instance(self, instance) -> dict[str, Any]:
        process_items = self._reachable_process_item_refs(instance)
        patient_ref = self._patient_ref_for_instance(instance)
        collection_event_ref = self._collection_event_ref_for_instance(instance)
        atlas_trf_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TRF_REFERENCE_TYPE,
            value_field="atlas_trf_euid",
        )
        atlas_test_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TEST_REFERENCE_TYPE,
            value_field="atlas_test_euid",
        )
        direct_test_euids = self._reachable_reference_values(
            instance,
            reference_type=self.TEST_REFERENCE_TYPE,
            value_field="atlas_test_euid",
        )
        atlas_testkit_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TESTKIT_REFERENCE_TYPE,
            value_field="atlas_testkit_euid",
        )
        atlas_shipment_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.SHIPMENT_REFERENCE_TYPE,
            value_field="atlas_shipment_euid",
        )
        atlas_organization_site_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.ORGANIZATION_SITE_REFERENCE_TYPE,
            value_field="atlas_organization_site_euid",
        )
        atlas_test_euids: list[str] = []
        seen_test_euids: set[str] = set()
        for direct_test_euid in direct_test_euids:
            if direct_test_euid in seen_test_euids:
                continue
            seen_test_euids.add(direct_test_euid)
            atlas_test_euids.append(direct_test_euid)
        if atlas_test_euid and atlas_test_euid not in seen_test_euids:
            seen_test_euids.add(atlas_test_euid)
            atlas_test_euids.append(atlas_test_euid)
        for item in sorted(
            process_items,
            key=lambda item: item["atlas_test_process_item_euid"],
        ):
            candidate = str(item["atlas_test_euid"] or "").strip()
            if not candidate or candidate in seen_test_euids:
                continue
            seen_test_euids.add(candidate)
            atlas_test_euids.append(candidate)
        fallback_tenant_id = self._first_reachable_reference_value(
            instance,
            reference_type=self.TRF_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.TEST_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.TESTKIT_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.SHIPMENT_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.ORGANIZATION_SITE_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or (
            patient_ref["atlas_tenant_id"] if patient_ref is not None else ""
        ) or (
            collection_event_ref["atlas_tenant_id"] if collection_event_ref is not None else ""
        )
        if not process_items:
            return {
                "atlas_tenant_id": fallback_tenant_id,
                "atlas_trf_euid": atlas_trf_euid,
                "atlas_test_euid": atlas_test_euid,
                "atlas_test_euids": atlas_test_euids,
                "atlas_testkit_euid": atlas_testkit_euid,
                "atlas_shipment_euid": atlas_shipment_euid,
                "atlas_organization_site_euid": atlas_organization_site_euid,
                "atlas_collection_event_euid": (
                    collection_event_ref["atlas_collection_event_euid"]
                    if collection_event_ref is not None
                    else ""
                ),
                "collection_event_snapshot": (
                    collection_event_ref["collection_event_snapshot"]
                    if collection_event_ref is not None
                    else {}
                ),
                "atlas_patient_euid": (
                    patient_ref["atlas_patient_euid"] if patient_ref is not None else ""
                ),
                "process_items": [],
            }
        first = process_items[0]
        return {
            "atlas_tenant_id": first["atlas_tenant_id"],
            "atlas_trf_euid": first["atlas_trf_euid"] or atlas_trf_euid,
            "atlas_test_euid": atlas_test_euid or first["atlas_test_euid"],
            "atlas_test_euids": atlas_test_euids,
            "atlas_testkit_euid": atlas_testkit_euid,
            "atlas_shipment_euid": atlas_shipment_euid,
            "atlas_organization_site_euid": atlas_organization_site_euid,
            "atlas_collection_event_euid": (
                collection_event_ref["atlas_collection_event_euid"]
                if collection_event_ref is not None
                else ""
            ),
            "collection_event_snapshot": (
                collection_event_ref["collection_event_snapshot"]
                if collection_event_ref is not None
                else {}
            ),
            "atlas_patient_euid": (
                patient_ref["atlas_patient_euid"] if patient_ref is not None else ""
            ),
            "process_items": [
                {
                    "atlas_test_euid": item["atlas_test_euid"],
                    "atlas_test_process_item_euid": item["atlas_test_process_item_euid"],
                }
                for item in sorted(
                    process_items,
                    key=lambda item: item["atlas_test_process_item_euid"],
                )
            ],
        }

    def _first_reachable_reference_value(
        self,
        instance,
        *,
        reference_type: str,
        value_field: str,
    ) -> str:
        visited: set[int] = set()
        to_visit = [instance]
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)
            for payload in self._atlas_reference_payloads_for_instance(current):
                current_ref_type = str(payload.get("reference_type") or "").strip()
                if current_ref_type != str(reference_type).strip():
                    continue
                value = str(payload.get(value_field) or "").strip()
                if not value:
                    value = str(payload.get("reference_value") or "").strip()
                if value:
                    return value
            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)
        return ""

    def _reachable_reference_values(
        self,
        instance,
        *,
        reference_type: str,
        value_field: str,
    ) -> list[str]:
        visited: set[int] = set()
        to_visit = [instance]
        values: list[str] = []
        seen: set[str] = set()
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)
            for payload in self._atlas_reference_payloads_for_instance(current):
                current_ref_type = str(payload.get("reference_type") or "").strip()
                if current_ref_type != str(reference_type).strip():
                    continue
                value = str(payload.get(value_field) or "").strip()
                if not value:
                    value = str(payload.get("reference_value") or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                values.append(value)
            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)
        return values

    def _first_parent(self, instance, relationship_type: str):
        for lineage in get_child_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != relationship_type:
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted:
                continue
            return parent
        return None

    def _pool_euid_for_run(self, run) -> str | None:
        pool = self._first_parent(run, "beta_sequencing_run")
        return pool.euid if pool is not None else None

    def _well_name(self, well) -> str:
        if well is None:
            return ""
        address = well.json_addl.get("cont_address") if isinstance(well.json_addl, dict) else {}
        name = str((address or {}).get("name") or "").strip()
        if name:
            return name
        return str(self._props(well).get("name") or "").strip()

    def _member_euids_for_pool(self, pool) -> list[str]:
        member_euids: list[str] = []
        for lineage in get_child_lineages(pool):
            if lineage.is_deleted or lineage.relationship_type != "beta_pool_member":
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted:
                continue
            member_euids.append(parent.euid)
        return sorted(member_euids)

    def _count_children(self, instance, relationship_type: str) -> int:
        count = 0
        for lineage in get_parent_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != relationship_type:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            count += 1
        return count

    def _require_template(self, template_code: str):
        clean = str(template_code or "").strip().strip("/")
        parts = clean.split("/")
        if len(parts) != 4:
            raise ValueError(
                f"Template code must be category/type/subtype/version: {template_code}"
            )
        templates = self.bobj.query_template_by_component_v2(*parts)
        if not templates:
            raise ValueError(f"Template not found: {template_code}")
        return templates[0]

    def _require_instance(self, euid: str):
        instance = self._safe_get_by_euid(euid)
        if instance is None or instance.is_deleted:
            raise ValueError(f"Bloom object not found: {euid}")
        return instance

    def _safe_get_by_euid(self, euid: str):
        try:
            return self.bobj.get_by_euid(euid)
        except Exception as exc:
            msg = str(exc).lower()
            if "not found" in msg or "no template found" in msg:
                return None
            raise

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

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat()
