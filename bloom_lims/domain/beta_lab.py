"""Queue-driven beta lab domain services for Bloom."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3, get_child_lineages, get_parent_lineages
from bloom_lims.domain.external_specimens import ExternalSpecimenService
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

    def close(self) -> None:
        self.bdb.close()

    def register_accepted_material(
        self,
        *,
        payload: BetaAcceptedMaterialCreateRequest,
        idempotency_key: str | None,
    ) -> BetaMaterialResponse:
        ext = ExternalSpecimenService(app_username=self.bdb.app_username)
        try:
            created = ext.create_specimen(
                payload=payload.to_external_specimen_request(),
                idempotency_key=idempotency_key,
            )
        finally:
            ext.close()

        specimen = self._require_instance(created.specimen_euid)
        return BetaMaterialResponse(
            specimen_euid=created.specimen_euid,
            container_euid=created.container_euid,
            status=created.status,
            atlas_refs=created.atlas_refs,
            properties=created.properties,
            idempotency_key=created.idempotency_key,
            current_queue=self._current_queue_for_instance(specimen),
            created=created.created,
        )

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

        return self._transition_material(
            material=material,
            queue_name=queue_name,
            metadata=metadata or {},
            idempotency_key=idempotency_key,
            replay=replay,
        )

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

        atlas_refs = self._resolve_atlas_identity(source)
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
                        "source_specimen_euid": source.euid,
                        "plate_euid": plate.euid,
                        "well_euid": well.euid,
                        "well_name": payload.well_name,
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
        self._replace_external_references(output, atlas_refs=atlas_refs)
        response = self._transition_material(
            material=output,
            queue_name="post_extract_qc",
            metadata={
                "source_specimen_euid": source.euid,
                "plate_euid": plate.euid,
                "well_name": payload.well_name,
            },
            idempotency_key=f"{idempotency_key}:post_extract_qc"
            if idempotency_key
            else None,
        )
        self.bdb.session.commit()
        return BetaExtractionResponse(
            source_specimen_euid=source.euid,
            plate_euid=plate.euid,
            well_euid=well.euid,
            well_name=payload.well_name,
            extraction_output_euid=output.euid,
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
                "extraction_output_euid": output.euid,
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
                return BetaLibraryPrepResponse(
                    source_extraction_output_euid=str(
                        self._props(existing).get("source_extraction_output_euid") or ""
                    ),
                    library_prep_output_euid=existing.euid,
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

        atlas_refs = self._resolve_atlas_identity(source)
        lib_output = self._create_data_record(
            beta_kind="library_prep_output",
            name=payload.output_name
            or f"{payload.platform.lower()}-lib-prep:{source.euid}",
            properties={
                "platform": payload.platform,
                "source_extraction_output_euid": source.euid,
                "idempotency_key": idempotency_key or "",
                "metadata": payload.metadata or {},
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            source.euid,
            lib_output.euid,
            relationship_type="beta_library_prep_output",
        )
        self._replace_external_references(lib_output, atlas_refs=atlas_refs)
        transition = self._transition_material(
            material=lib_output,
            queue_name=self.SEQ_POOL_QUEUE_BY_PLATFORM[payload.platform],
            metadata={"source_extraction_output_euid": source.euid},
            idempotency_key=f"{idempotency_key}:queue" if idempotency_key else None,
        )
        self.bdb.session.commit()
        return BetaLibraryPrepResponse(
            source_extraction_output_euid=source.euid,
            library_prep_output_euid=lib_output.euid,
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
                    pool_euid=str(existing_props.get("pool_euid") or ""),
                    run_folder=str(
                        existing_props.get("run_folder") or f"{existing.euid}/"
                    ),
                    status=str(existing_props.get("status") or ""),
                    artifact_count=self._count_children(existing, "beta_run_artifact"),
                    mapping_count=self._count_children(existing, "beta_run_index_map"),
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
                "pool_euid": pool.euid,
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

        for mapping in payload.index_mappings:
            source = self._require_instance(mapping.source_euid)
            atlas_refs = self._resolve_atlas_identity(source)
            mapping_record = self._create_data_record(
                beta_kind="run_index_mapping",
                name=f"{run.euid}:{mapping.index_string}",
                properties={
                    "run_euid": run.euid,
                    "index_string": mapping.index_string,
                    "source_euid": source.euid,
                    "atlas_tenant_id": atlas_refs["atlas_tenant_id"],
                    "atlas_order_euid": atlas_refs["atlas_order_euid"],
                    "atlas_test_order_euid": atlas_refs["atlas_test_order_euid"],
                },
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                run.euid,
                mapping_record.euid,
                relationship_type="beta_run_index_map",
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                source.euid,
                mapping_record.euid,
                relationship_type="beta_run_source_map",
            )

        for artifact in payload.artifacts:
            artifact_record = self._create_data_record(
                beta_kind="run_artifact",
                name=f"{run.euid}:{artifact.artifact_type}:{artifact.filename}",
                properties={
                    "run_euid": run.euid,
                    "artifact_type": artifact.artifact_type,
                    "bucket": artifact.bucket,
                    "filename": artifact.filename,
                    "index_string": artifact.index_string or "",
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

        self.bdb.session.commit()
        return BetaRunResponse(
            run_euid=run.euid,
            pool_euid=pool.euid,
            run_folder=str(run_props["run_folder"]),
            status=payload.status,
            artifact_count=len(payload.artifacts),
            mapping_count=len(payload.index_mappings),
            idempotent_replay=False,
        )

    def resolve_run_index(
        self, *, run_euid: str, index_string: str
    ) -> BetaRunResolutionResponse:
        run = self._require_instance(run_euid)
        normalized_index = str(index_string or "").strip()
        if not normalized_index:
            raise ValueError("index_string is required")

        for lineage in get_parent_lineages(run):
            if lineage.is_deleted or lineage.relationship_type != "beta_run_index_map":
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            props = self._props(child)
            if str(props.get("index_string") or "").strip() != normalized_index:
                continue
            return BetaRunResolutionResponse(
                run_euid=run.euid,
                index_string=normalized_index,
                atlas_tenant_id=str(props.get("atlas_tenant_id") or ""),
                atlas_order_euid=str(props.get("atlas_order_euid") or ""),
                atlas_test_order_euid=str(props.get("atlas_test_order_euid") or ""),
                source_euid=str(props.get("source_euid") or ""),
            )

        raise ValueError(
            "Run/index mapping not found for "
            f"run_euid={run_euid} index_string={normalized_index}"
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
                "material_euid": material.euid,
                "queue_euid": queue_def.euid,
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
        return BetaQueueTransitionResponse(
            material_euid=str(props.get("material_euid") or ""),
            queue_euid=str(props.get("queue_euid") or ""),
            queue_name=str(props.get("queue_name") or ""),
            previous_queue=str(props.get("previous_queue") or "") or None,
            current_queue=str(props.get("queue_name") or ""),
            idempotent_replay=replay,
        )

    def _extraction_response(
        self, extraction_output, *, replay: bool
    ) -> BetaExtractionResponse:
        props = self._props(extraction_output)
        return BetaExtractionResponse(
            source_specimen_euid=str(props.get("source_specimen_euid") or ""),
            plate_euid=str(props.get("plate_euid") or ""),
            well_euid=str(props.get("well_euid") or ""),
            well_name=str(props.get("well_name") or ""),
            extraction_output_euid=extraction_output.euid,
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
        return None

    def _resolve_atlas_identity(self, instance) -> dict[str, str]:
        visited: set[int] = set()
        to_visit = [instance]
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)

            refs = self._atlas_refs_for_instance(current)
            if {
                "atlas_tenant_id",
                "atlas_order_euid",
                "atlas_test_order_euid",
            }.issubset(refs):
                return {
                    "atlas_tenant_id": refs["atlas_tenant_id"],
                    "atlas_order_euid": refs["atlas_order_euid"],
                    "atlas_test_order_euid": refs["atlas_test_order_euid"],
                }

            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)

        raise ValueError(
            "No Atlas TRF/test identity could be resolved from "
            f"Bloom lineage for {instance.euid}"
        )

    def _atlas_refs_for_instance(self, instance) -> dict[str, str]:
        refs: dict[str, str] = {}
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
            ref_type = str(payload.get("reference_type") or "").strip()
            ref_value = str(payload.get("reference_value") or "").strip()
            if ref_type and ref_value:
                refs[ref_type] = ref_value
        return refs

    def _replace_external_references(
        self, instance, *, atlas_refs: dict[str, str]
    ) -> None:
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
            lineage.is_deleted = True
            child.is_deleted = True

        for reference_type, reference_value in sorted(atlas_refs.items()):
            clean_value = str(reference_value or "").strip()
            if not clean_value:
                continue
            ref_obj = self.bobj.create_instance_by_code(
                self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                {
                    "json_addl": {
                        "properties": {
                            "provider": "atlas",
                            "reference_type": reference_type,
                            "reference_value": clean_value,
                            "foreign_reference": clean_value,
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
