"""Internal stage and run helpers for beta lab domain services."""

from __future__ import annotations

from typing import Any

from bloom_lims.db import get_parent_lineages
from bloom_lims.integrations.dewey.client import DeweyClientError
from bloom_lims.schemas.beta_lab import (
    BetaExtractionCreateRequest,
    BetaExtractionResponse,
    BetaLibraryPrepCreateRequest,
    BetaLibraryPrepResponse,
    BetaPoolCreateRequest,
    BetaPoolResponse,
    BetaPostExtractQCRequest,
    BetaPostExtractQCResponse,
    BetaQueueTransitionResponse,
    BetaRunCreateRequest,
    BetaRunResolutionResponse,
    BetaRunResponse,
)


class _BetaLabStagesMixin:
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

        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})
        source = self._require_instance(payload.source_specimen_euid)
        self._assert_not_reserved(source)
        self._assert_not_consumed(source, stage_label="extraction")
        lease = self._resolve_stage_claim(
            material=source,
            expected_queues={"extraction_prod", "extraction_rnd"},
            claim_euid=payload.claim_euid,
            stage_label="extraction",
        )
        execution_subject = self.execution._subject_for_lease(lease) or source

        fulfillment_item_context = self._resolve_fulfillment_item_context(
            source,
            target_fulfillment_item_euid=payload.atlas_test_fulfillment_item_euid,
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
        self._replace_fulfillment_item_references(
            output, atlas_context=fulfillment_item_context
        )
        self.execution.queue_subject(
            subject_euid=output.euid,
            queue_key="post_extract_qc",
            next_action_key="record_post_extract_qc",
            idempotency_key=(
                f"{idempotency_key}:post_extract_qc"
                if idempotency_key
                else f"queue:post_extract_qc:{output.euid}"
            ),
            executed_by=self.bdb.app_username,
        )
        response = BetaQueueTransitionResponse(
            material_euid=output.euid,
            queue_euid=self.execution.get_queue("post_extract_qc").queue_euid,
            queue_name="post_extract_qc",
            previous_queue=None,
            current_queue="post_extract_qc",
            idempotent_replay=False,
        )
        if payload.consume_source:
            self._consume_material_instance(
                source,
                reason="stage:extraction",
                metadata={"stage": "extraction", **normalized_metadata},
            )
        self._complete_stage_execution(
            subject=execution_subject,
            lease=lease,
            action_key="create_extraction",
            idempotency_key=idempotency_key
            or f"complete:create_extraction:{execution_subject.euid}",
            result_payload={
                "output_euid": output.euid,
                "queue_name": "post_extract_qc",
                "well_name": payload.well_name,
            },
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
                "atlas_test_fulfillment_item_euid": payload.atlas_test_fulfillment_item_euid,
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
            atlas_test_fulfillment_item_euid=fulfillment_item_context[
                "atlas_test_fulfillment_item_euid"
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
            self._complete_stage_execution(
                subject=output,
                lease=self._resolve_stage_claim(
                    material=output,
                    expected_queues={"post_extract_qc"},
                    claim_euid=None,
                    stage_label="post_extract_qc",
                ),
                action_key="record_post_extract_qc",
                idempotency_key=idempotency_key
                or f"complete:post_extract_qc:{output.euid}",
                next_queue_key=payload.next_queue,
                next_action_key="create_library_prep",
                terminal=False,
                result_payload={
                    "passed": True,
                    "next_queue": payload.next_queue,
                    "metrics": payload.metrics or {},
                },
            )
            next_queue = payload.next_queue
        else:
            lease = self._resolve_stage_claim(
                material=output,
                expected_queues={"post_extract_qc"},
                claim_euid=None,
                stage_label="post_extract_qc",
            )
            self._complete_stage_execution(
                subject=output,
                lease=lease,
                action_key="record_post_extract_qc",
                idempotency_key=idempotency_key
                or f"complete:post_extract_qc:{output.euid}",
                terminal=True,
                result_payload={
                    "passed": False,
                    "metrics": payload.metrics or {},
                },
            )

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
            existing = self._find_library_prep_output_record(
                idempotency_key=idempotency_key
            )
            if existing is not None:
                source = self._first_parent(existing, "beta_library_prep_output")
                library_material = self._find_content_record(
                    beta_kind="library_material",
                    idempotency_key=idempotency_key,
                )
                library_well = (
                    self._first_parent(library_material, "contains")
                    if library_material is not None
                    else None
                )
                library_plate = (
                    self._first_parent(library_well, "contains")
                    if library_well is not None
                    else None
                )
                fulfillment_item_context = self._resolve_fulfillment_item_context(
                    existing
                )
                return BetaLibraryPrepResponse(
                    source_extraction_output_euid=source.euid if source is not None else "",
                    library_prep_output_euid=existing.euid,
                    library_material_euid=(
                        library_material.euid if library_material is not None else None
                    ),
                    library_container_euid=(
                        library_plate.euid if library_plate is not None else None
                    ),
                    library_plate_euid=library_plate.euid if library_plate is not None else None,
                    library_well_euid=library_well.euid if library_well is not None else None,
                    atlas_test_fulfillment_item_euid=fulfillment_item_context[
                        "atlas_test_fulfillment_item_euid"
                    ],
                    current_queue=(
                        self._current_queue_for_instance(library_material or existing)
                        or ""
                    ),
                    idempotent_replay=True,
                )

        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})
        source = self._require_instance(payload.source_extraction_output_euid)
        self._assert_not_reserved(source)
        self._assert_not_consumed(source, stage_label="library_prep")
        expected_queue = self.LIB_PREP_QUEUE_BY_PLATFORM[payload.platform]
        lease = self._resolve_stage_claim(
            material=source,
            expected_queues={expected_queue},
            claim_euid=payload.claim_euid,
            stage_label="library_prep",
        )

        fulfillment_item_context = self._resolve_fulfillment_item_context(source)
        source_well = self._first_parent(source, "contains")
        source_well_name = self._well_name(source_well) or "A1"
        lib_output = self.bobj.create_instance_by_code(
            self.LIBRARY_PREP_OUTPUT_TEMPLATE_CODE,
            {
                "json_addl": {
                    "properties": {
                        "platform": payload.platform,
                        "idempotency_key": idempotency_key or "",
                        "metadata": normalized_metadata,
                    }
                }
            },
        )
        lib_props = self._props(lib_output)
        lib_name = payload.output_name or f"{payload.platform.lower()}-lib-prep:{source.euid}"
        lib_output.name = lib_name
        lib_props["name"] = lib_name
        self._write_props(lib_output, lib_props)
        self.bobj.create_generic_instance_lineage_by_euids(
            source.euid,
            lib_output.euid,
            relationship_type="beta_library_prep_output",
        )
        extraction_type = (
            str(self._props(source).get("extraction_type") or "gdna").strip().lower()
        )
        library_material = self.bobj.create_instance_by_code(
            self.EXTRACTION_TEMPLATE_BY_TYPE.get(
                extraction_type, "content/sample/gdna/1.0"
            ),
            {
                "json_addl": {
                    "properties": {
                        "beta_kind": "library_material",
                        "platform": payload.platform,
                        "idempotency_key": idempotency_key or "",
                        "metadata": normalized_metadata,
                    }
                }
            },
        )
        library_material_props = self._props(library_material)
        library_material_name = (
            f"{payload.output_name} seq lib"
            if payload.output_name
            else f"{payload.platform.lower()}-seq-lib:{source.euid}"
        )
        library_material.name = library_material_name
        library_material_props["name"] = library_material_name
        self._write_props(library_material, library_material_props)
        self.bobj.create_generic_instance_lineage_by_euids(
            source.euid,
            library_material.euid,
            relationship_type="beta_library_material_output",
        )
        library_plate = self._resolve_or_create_plate(
            plate_euid=None,
            plate_template_code=self.LIBRARY_PLATE_TEMPLATE_CODE,
            plate_name=(
                f"{payload.output_name} plate"
                if payload.output_name
                else f"{payload.platform.lower()}-seq-lib-plate:{source.euid}"
            ),
        )
        library_plate_props = self._props(library_plate)
        library_plate_props["beta_kind"] = "library_plate"
        library_plate_props["idempotency_key"] = idempotency_key or ""
        self._write_props(library_plate, library_plate_props)
        library_well = self._require_plate_well(library_plate, source_well_name)
        library_well_props = self._props(library_well)
        library_well_props["beta_kind"] = "library_plate_well"
        library_well_props["idempotency_key"] = idempotency_key or ""
        self._write_props(library_well, library_well_props)
        self.bobj.create_generic_instance_lineage_by_euids(
            library_well.euid,
            library_material.euid,
            relationship_type="contains",
        )
        self._replace_fulfillment_item_references(
            lib_output,
            atlas_context=fulfillment_item_context,
        )
        self._replace_fulfillment_item_references(
            library_material,
            atlas_context=fulfillment_item_context,
        )
        self._attach_execution_metadata_lineage(lib_output, normalized_metadata)
        self._attach_execution_metadata_lineage(library_material, normalized_metadata)
        self.execution.queue_subject(
            subject_euid=lib_output.euid,
            queue_key=self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
            next_action_key="create_pool",
            idempotency_key=(
                f"{idempotency_key}:queue"
                if idempotency_key
                else f"queue:libprep:{lib_output.euid}"
            ),
            executed_by=self.bdb.app_username,
        )
        self.execution.queue_subject(
            subject_euid=library_material.euid,
            queue_key=self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
            next_action_key="create_pool",
            idempotency_key=(
                f"{idempotency_key}:queue:material"
                if idempotency_key
                else f"queue:libprep-material:{library_material.euid}"
            ),
            executed_by=self.bdb.app_username,
        )
        if payload.consume_source:
            self._consume_material_instance(
                source,
                reason="stage:library_prep",
                metadata={"stage": "library_prep", **normalized_metadata},
            )
        self._complete_stage_execution(
            subject=source,
            lease=lease,
            action_key="create_library_prep",
            idempotency_key=idempotency_key
            or f"complete:create_library_prep:{source.euid}",
            result_payload={
                "library_prep_output_euid": lib_output.euid,
                "queue_name": self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
            },
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
                "library_material_euid": library_material.euid,
                "library_container_euid": library_plate.euid,
                "library_plate_euid": library_plate.euid,
                "library_well_euid": library_well.euid,
                "current_queue": self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
            },
        )
        self.bdb.session.commit()
        return BetaLibraryPrepResponse(
            source_extraction_output_euid=source.euid,
            library_prep_output_euid=lib_output.euid,
            library_material_euid=library_material.euid,
            library_container_euid=library_plate.euid,
            library_plate_euid=library_plate.euid,
            library_well_euid=library_well.euid,
            atlas_test_fulfillment_item_euid=fulfillment_item_context[
                "atlas_test_fulfillment_item_euid"
            ],
            current_queue=self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
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

        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})
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

        self.execution.queue_subject(
            subject_euid=pool.euid,
            queue_key=self.START_RUN_QUEUE_BY_PLATFORM[payload.platform],
            next_action_key="create_run",
            idempotency_key=(
                f"{idempotency_key}:queue"
                if idempotency_key
                else f"queue:pool:{pool.euid}"
            ),
            executed_by=self.bdb.app_username,
        )
        if payload.consume_members:
            for member in members:
                self._consume_material_instance(
                    member,
                    reason="stage:pool",
                    metadata={"stage": "pool", **normalized_metadata},
                )
        for claim in claims:
            subject = self.execution._subject_for_lease(claim) or members[0]
            self._complete_stage_execution(
                subject=subject,
                lease=claim,
                action_key="create_pool",
                idempotency_key=f"{idempotency_key or 'complete:create_pool'}:{subject.euid}",
                result_payload={
                    "pool_euid": pool.euid,
                    "queue_name": self.START_RUN_QUEUE_BY_PLATFORM[payload.platform],
                },
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
                "current_queue": self.START_RUN_QUEUE_BY_PLATFORM[payload.platform],
                "member_count": len(members),
            },
        )
        self.bdb.session.commit()
        return BetaPoolResponse(
            pool_euid=pool.euid,
            pool_container_euid=pool_container.euid,
            current_queue=self.START_RUN_QUEUE_BY_PLATFORM[payload.platform],
            member_euids=[member.euid for member in members],
            idempotent_replay=False,
        )

    def _register_run_artifact_in_dewey(
        self,
        *,
        run_euid: str,
        artifact_type: str,
        storage_uri: str,
        lane: str | None,
        library_barcode: str | None,
        metadata: dict[str, Any],
    ) -> str | None:
        if self.dewey_client is None:
            return None
        dewey_metadata = {
            "producer_system": "bloom",
            "producer_object_euid": run_euid,
            "lane": str(lane or "").strip(),
            "library_barcode": str(library_barcode or "").strip(),
            **dict(metadata or {}),
        }
        try:
            return self.dewey_client.register_artifact(
                artifact_type=artifact_type,
                storage_uri=storage_uri,
                metadata=dewey_metadata,
                idempotency_key=f"{run_euid}:{artifact_type}:{storage_uri}",
            )
        except DeweyClientError as exc:
            raise ValueError(f"Failed registering run artifact in Dewey: {exc}") from exc

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
                    run_folder=str(existing_props.get("run_folder") or f"{existing.euid}/"),
                    status=str(existing_props.get("status") or ""),
                    artifact_count=self._count_children(existing, "beta_run_artifact"),
                    assignment_count=self._count_children(
                        existing, "beta_sequenced_library_assignment"
                    ),
                    idempotent_replay=True,
                )

        normalized_metadata = self.normalize_execution_metadata(payload.metadata or {})
        pool = self._require_instance(payload.pool_euid)
        self._assert_not_reserved(pool)
        self._assert_not_consumed(pool, stage_label="start_run")
        expected_queue = self.START_RUN_QUEUE_BY_PLATFORM[payload.platform]
        lease = self._resolve_stage_claim(
            material=pool,
            expected_queues={expected_queue},
            claim_euid=payload.claim_euid,
            stage_label="start_run",
        )

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
            fulfillment_item_context = self._resolve_fulfillment_item_context(source)
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
            self._replace_fulfillment_item_references(
                assignment_record,
                atlas_context=fulfillment_item_context,
            )

        for artifact in payload.artifacts:
            artifact_metadata = self.normalize_execution_metadata(artifact.metadata or {})
            s3_key = f"{run.euid}/{artifact.filename}"
            s3_uri = f"s3://{artifact.bucket}/{s3_key}"
            dewey_artifact_euid = self._register_run_artifact_in_dewey(
                run_euid=run.euid,
                artifact_type=artifact.artifact_type,
                storage_uri=s3_uri,
                lane=artifact.lane,
                library_barcode=artifact.library_barcode,
                metadata=artifact_metadata,
            )
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
                    "s3_key": s3_key,
                    "s3_uri": s3_uri,
                    "dewey_artifact_euid": dewey_artifact_euid or "",
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
        self._complete_stage_execution(
            subject=pool,
            lease=lease,
            action_key="create_run",
            idempotency_key=idempotency_key or f"complete:create_run:{pool.euid}",
            result_payload={
                "run_euid": run.euid,
                "status": payload.status,
            },
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
                "assignments": [
                    assignment.model_dump() for assignment in payload.assignments
                ],
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
            fulfillment_item_context = self._resolve_fulfillment_item_context(
                assignment
            )
            return BetaRunResolutionResponse(
                run_euid=run.euid,
                flowcell_id=normalized_flowcell_id,
                lane=normalized_lane,
                library_barcode=normalized_library_barcode,
                sequenced_library_assignment_euid=assignment.euid,
                atlas_tenant_id=fulfillment_item_context["atlas_tenant_id"],
                atlas_trf_euid=fulfillment_item_context["atlas_trf_euid"],
                atlas_test_euid=fulfillment_item_context["atlas_test_euid"],
                atlas_test_fulfillment_item_euid=fulfillment_item_context[
                    "atlas_test_fulfillment_item_euid"
                ],
            )

        raise ValueError(
            "Sequenced library assignment not found for "
            f"run_euid={run_euid} flowcell_id={normalized_flowcell_id} "
            f"lane={normalized_lane} library_barcode={normalized_library_barcode}"
        )

    def _extraction_response(
        self, extraction_output, *, replay: bool
    ) -> BetaExtractionResponse:
        source = self._first_parent(extraction_output, "beta_extraction_output")
        well = self._first_parent(extraction_output, "contains")
        plate = self._first_parent(well, "contains") if well is not None else None
        fulfillment_item_context = self._resolve_fulfillment_item_context(
            extraction_output
        )
        return BetaExtractionResponse(
            source_specimen_euid=source.euid if source is not None else "",
            plate_euid=plate.euid if plate is not None else "",
            well_euid=well.euid if well is not None else "",
            well_name=self._well_name(well),
            extraction_output_euid=extraction_output.euid,
            atlas_test_fulfillment_item_euid=fulfillment_item_context[
                "atlas_test_fulfillment_item_euid"
            ],
            current_queue=self._current_queue_for_instance(extraction_output) or "",
            idempotent_replay=replay,
        )
