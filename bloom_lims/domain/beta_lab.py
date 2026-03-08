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
    TESTKIT_REFERENCE_TYPE = "atlas_testkit"
    SHIPMENT_REFERENCE_TYPE = "atlas_shipment"
    ORGANIZATION_SITE_REFERENCE_TYPE = "atlas_organization_site"
    GENERIC_DATA_TEMPLATE_CODE = "generic/generic/generic/1.0"
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
                beta_kind="queue_event",
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
        current_queue = self._current_queue_for_instance(source)
        if current_queue not in {"extraction_prod", "extraction_rnd"}:
            raise ValueError(
                "Source specimen must be queued in extraction_prod or extraction_rnd "
                f"(current_queue={current_queue!r})"
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

        output = self.bobj.create_instance_by_code(
            self.EXTRACTION_TEMPLATE_BY_TYPE[payload.extraction_type],
            {
                "json_addl": {
                    "properties": {
                        "beta_kind": "extraction_output",
                        "extraction_type": payload.extraction_type,
                        "idempotency_key": idempotency_key or "",
                        "metadata": payload.metadata or {},
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
        self._replace_process_item_references(output, atlas_context=process_item_context)
        response = self._transition_material(
            material=output,
            queue_name="post_extract_qc",
            metadata={"stage": "extraction", "well_name": payload.well_name},
            idempotency_key=f"{idempotency_key}:post_extract_qc"
            if idempotency_key
            else None,
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
                "metadata": payload.metadata or {},
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
                "idempotency_key": idempotency_key or "",
                "occurred_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            output.euid,
            qc_record.euid,
            relationship_type="beta_post_extract_qc",
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
                metadata={"stage": "post_extract_qc"},
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
        expected_queue = self.LIB_PREP_QUEUE_BY_PLATFORM[payload.platform]
        current_queue = self._current_queue_for_instance(source)
        if current_queue != expected_queue:
            raise ValueError(
                "Extraction output must be queued for library prep "
                f"(expected={expected_queue!r} current_queue={current_queue!r})"
            )

        process_item_context = self._resolve_process_item_context(source)
        lib_output = self._create_data_record(
            beta_kind="library_prep_output",
            name=payload.output_name
            or f"{payload.platform.lower()}-lib-prep:{source.euid}",
            properties={
                "platform": payload.platform,
                "idempotency_key": idempotency_key or "",
                "metadata": payload.metadata or {},
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
        transition = self._transition_material(
            material=lib_output,
            queue_name=self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
            metadata={"stage": "library_prep"},
            idempotency_key=f"{idempotency_key}:queue" if idempotency_key else None,
        )
        self._record_action(
            target_instance=lib_output,
            action_key="create_library_prep",
            captured_data={
                "source_extraction_output_euid": payload.source_extraction_output_euid,
                "platform": payload.platform,
                "output_name": payload.output_name,
                "metadata": payload.metadata or {},
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
        for member in members:
            current_queue = self._current_queue_for_instance(member)
            if current_queue != expected_queue:
                raise ValueError(
                    "Library prep outputs must be queued for sequencing pool "
                    f"(expected={expected_queue!r} current_queue={current_queue!r})"
                )

        pool = self.bobj.create_instance_by_code(
            self.POOL_TEMPLATE_CODE,
            {
                "json_addl": {
                    "properties": {
                        "beta_kind": "sequencing_pool",
                        "platform": payload.platform,
                        "member_count": len(members),
                        "idempotency_key": idempotency_key or "",
                        "metadata": payload.metadata or {},
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

        transition = self._transition_material(
            material=pool,
            queue_name=self.START_RUN_QUEUE_BY_PLATFORM[payload.platform],
            metadata={"platform": payload.platform},
            idempotency_key=f"{idempotency_key}:queue" if idempotency_key else None,
        )
        self._record_action(
            target_instance=pool,
            action_key="create_pool",
            captured_data={
                "member_euids": [member.euid for member in members],
                "platform": payload.platform,
                "pool_name": payload.pool_name,
                "metadata": payload.metadata or {},
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
        expected_queue = self.START_RUN_QUEUE_BY_PLATFORM[payload.platform]
        current_queue = self._current_queue_for_instance(pool)
        if current_queue != expected_queue:
            raise ValueError(
                "Pool must be queued to start sequencing "
                f"(expected={expected_queue!r} current_queue={current_queue!r})"
            )

        run = self._create_data_record(
            beta_kind="sequencing_run",
            name=payload.run_name or f"{payload.platform.lower()}-run",
            properties={
                "platform": payload.platform,
                "flowcell_id": payload.flowcell_id,
                "status": payload.status,
                "idempotency_key": idempotency_key or "",
            },
        )
        run_props = self._props(run)
        run_props["run_folder"] = f"{run.euid}/"
        run_props["metadata"] = payload.metadata or {}
        self._write_props(run, run_props)
        self.bobj.create_generic_instance_lineage_by_euids(
            pool.euid,
            run.euid,
            relationship_type="beta_sequencing_run",
        )

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
            artifact_record = self._create_data_record(
                beta_kind="run_artifact",
                name=f"{run.euid}:{artifact.artifact_type}:{artifact.filename}",
                properties={
                    "artifact_type": artifact.artifact_type,
                    "bucket": artifact.bucket,
                    "filename": artifact.filename,
                    "lane": artifact.lane or "",
                    "library_barcode": artifact.library_barcode or "",
                    "metadata": artifact.metadata or {},
                    "s3_key": f"{run.euid}/{artifact.filename}",
                    "s3_uri": f"s3://{artifact.bucket}/{run.euid}/{artifact.filename}",
                },
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                run.euid,
                artifact_record.euid,
                relationship_type="beta_run_artifact",
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

        queue_def = self._ensure_queue_definition(normalized_queue)
        previous_queue = self._current_queue_for_instance(material)
        self._retire_queue_memberships(material)
        self.bobj.create_generic_instance_lineage_by_euids(
            queue_def.euid,
            material.euid,
            relationship_type="beta_queue_membership",
        )

        props = self._props(material)
        props["current_queue"] = normalized_queue
        props["queue_updated_at"] = self._timestamp()
        self._write_props(material, props)

        queue_event = self._create_data_record(
            beta_kind="queue_event",
            name=f"{normalized_queue}:{material.euid}",
            properties={
                "queue_name": normalized_queue,
                "previous_queue": previous_queue or "",
                "idempotency_key": idempotency_key or "",
                "metadata": metadata or {},
                "occurred_at": self._timestamp(),
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            material.euid,
            queue_event.euid,
            relationship_type="beta_queue_event",
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            queue_def.euid,
            queue_event.euid,
            relationship_type="beta_queue_event_queue",
        )
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
        material = self._first_parent(event, "beta_queue_event")
        queue = self._first_parent(event, "beta_queue_event_queue")
        return BetaQueueTransitionResponse(
            material_euid=material.euid if material is not None else "",
            queue_euid=queue.euid if queue is not None else "",
            queue_name=str(props.get("queue_name") or ""),
            previous_queue=str(props.get("previous_queue") or "") or None,
            current_queue=str(props.get("queue_name") or ""),
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
            beta_kind="queue_definition",
            property_key="queue_name",
            expected=queue_name,
        )
        if existing is not None:
            return existing

        return self._create_data_record(
            beta_kind="queue_definition",
            name=queue_name,
            properties={"queue_name": queue_name},
        )

    def _retire_queue_memberships(self, material) -> None:
        for lineage in get_child_lineages(material):
            if (
                lineage.is_deleted
                or lineage.relationship_type != "beta_queue_membership"
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
                or lineage.relationship_type != "beta_queue_membership"
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
        reference_fields = (
            (self.TRF_REFERENCE_TYPE, "atlas_trf_euid"),
            (self.TESTKIT_REFERENCE_TYPE, "atlas_testkit_euid"),
            (self.SHIPMENT_REFERENCE_TYPE, "atlas_shipment_euid"),
            (self.ORGANIZATION_SITE_REFERENCE_TYPE, "atlas_organization_site_euid"),
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

    def _atlas_context_for_instance(self, instance) -> dict[str, Any]:
        process_items = self._reachable_process_item_refs(instance)
        patient_ref = self._patient_ref_for_instance(instance)
        atlas_trf_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TRF_REFERENCE_TYPE,
            value_field="atlas_trf_euid",
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
        if not process_items:
            return {
                "atlas_tenant_id": "",
                "atlas_trf_euid": atlas_trf_euid,
                "atlas_testkit_euid": atlas_testkit_euid,
                "atlas_shipment_euid": atlas_shipment_euid,
                "atlas_organization_site_euid": atlas_organization_site_euid,
                "atlas_patient_euid": (
                    patient_ref["atlas_patient_euid"] if patient_ref is not None else ""
                ),
                "process_items": [],
            }
        first = process_items[0]
        return {
            "atlas_tenant_id": first["atlas_tenant_id"],
            "atlas_trf_euid": first["atlas_trf_euid"] or atlas_trf_euid,
            "atlas_testkit_euid": atlas_testkit_euid,
            "atlas_shipment_euid": atlas_shipment_euid,
            "atlas_organization_site_euid": atlas_organization_site_euid,
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
