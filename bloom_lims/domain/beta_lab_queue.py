"""Internal queue and execution helpers for beta lab domain services."""

from __future__ import annotations

from typing import Any

from bloom_lims.db import get_child_lineages, get_parent_lineages
from bloom_lims.schemas.beta_lab import (
    BetaClaimResponse,
    BetaConsumeMaterialResponse,
    BetaQueueTransitionResponse,
    BetaReservationResponse,
)
from bloom_lims.schemas.execution_queue import (
    ClaimQueueItemRequest,
    CompleteQueueExecutionRequest,
    ExecutionState,
    ReleaseQueueLeaseRequest,
    RequeueSubjectRequest,
    WorkerType,
)
from bloom_lims.template_identity import instance_semantic_category


class _BetaLabQueueMixin:
    def move_material_to_queue(
        self,
        *,
        material_euid: str,
        queue_name: str,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaQueueTransitionResponse:
        material = self._require_instance(material_euid)
        previous_queue = self._current_queue_for_instance(material)
        queue_action = self.NEXT_ACTION_BY_QUEUE.get(str(queue_name or "").strip())
        action_response = self.execution.requeue_subject(
            RequeueSubjectRequest(
                subject_euid=material.euid,
                queue_key=queue_name,
                next_action_key=queue_action,
                idempotency_key=idempotency_key
                or f"queue:{material.euid}:{queue_name}",
            ),
            executed_by=self.bdb.app_username,
        )
        response = BetaQueueTransitionResponse(
            material_euid=material.euid,
            queue_euid=self.execution.get_queue(queue_name).queue_euid,
            queue_name=queue_name,
            previous_queue=previous_queue,
            current_queue=queue_name,
            idempotent_replay=action_response.replayed,
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
        material = self._require_instance(material_euid)
        self._assert_not_reserved(material)
        self._assert_not_consumed(material, stage_label="claim")
        queue_subject = self._execution_subject_for_material(
            material,
            expected_queues={normalized_queue},
        )
        worker = self._resolve_queue_worker(
            queue_name=normalized_queue,
            worker_type=WorkerType.SERVICE,
        )
        claim_result = self.execution.claim_queue_item(
            ClaimQueueItemRequest(
                worker_euid=worker.worker_euid,
                queue_key=normalized_queue,
                subject_euid=queue_subject.euid,
                idempotency_key=idempotency_key
                or f"claim:{queue_subject.euid}:{normalized_queue}",
                expected_state=ExecutionState.READY,
                payload=metadata or {},
            ),
            executed_by=self.bdb.app_username,
        )
        lease = self.execution._require_lease(str(claim_result.lease_euid))
        self._record_action(
            target_instance=queue_subject,
            action_key="claim_material_in_queue",
            captured_data={
                "material_euid": material_euid,
                "queue_name": normalized_queue,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={
                "status": "success",
                "claim_euid": lease.euid,
                "queue_name": normalized_queue,
                "material_euid": queue_subject.euid,
            },
        )
        self.bdb.session.commit()
        return self._claim_response(lease, replay=claim_result.replayed)

    def release_claim(
        self,
        *,
        claim_euid: str,
        reason: str | None,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> BetaClaimResponse:
        lease = self.execution._require_lease(claim_euid)
        worker_euid = str(self.execution._props(lease).get("worker_lookup_euid") or "")
        action_response = self.execution.release_queue_lease(
            ReleaseQueueLeaseRequest(
                lease_euid=claim_euid,
                worker_euid=worker_euid,
                idempotency_key=idempotency_key or f"release:{claim_euid}",
                reason=reason,
            ),
            executed_by=self.bdb.app_username,
        )
        self._record_action(
            target_instance=lease,
            action_key="release_claim",
            captured_data={
                "claim_euid": claim_euid,
                "reason": reason,
                "metadata": metadata or {},
                "idempotency_key": idempotency_key or "",
            },
            result={"status": "success", "claim_euid": lease.euid},
        )
        self.bdb.session.commit()
        return self._claim_response(lease, replay=action_response.replayed)

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

    def normalize_execution_metadata(
        self, metadata: dict[str, Any] | None
    ) -> dict[str, Any]:
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
            if instance_semantic_category(instrument) != "equipment":
                raise ValueError(
                    "metadata.instrument_euid must reference an equipment object"
                )
            normalized["instrument_euid"] = instrument.euid

        reagent_euid = normalized.get("reagent_euid")
        if reagent_euid is not None:
            reagent = self._require_instance(str(reagent_euid))
            if instance_semantic_category(reagent) != "content" or (
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
        if (
            instance_semantic_category(instance) != "data"
            or instance.type != "generic"
            or instance.subtype != "generic"
        ):
            return False
        return (
            str(self._props(instance).get("beta_kind") or "").strip()
            == str(beta_kind).strip()
        )

    def _work_items_for_material(self, material) -> list[Any]:
        items: list[Any] = []
        for lineage in get_parent_lineages(material):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.REL_WORK_ITEM_SUBJECT
            ):
                continue
            child = lineage.child_instance
            if (
                child is None
                or child.is_deleted
                or not self._is_data_kind(child, self.BETA_KIND_WORK_ITEM)
            ):
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
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.REL_WORK_ITEM_CLAIM
            ):
                continue
            claim = lineage.child_instance
            if (
                claim is None
                or claim.is_deleted
                or not self._is_data_kind(claim, self.BETA_KIND_CLAIM)
            ):
                continue
            status = str(self._props(claim).get("status") or "").strip().lower()
            if status == "active":
                return claim
        return None

    def _active_reservation_for_material(self, material):
        for lineage in get_parent_lineages(material):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.REL_MATERIAL_RESERVATION
            ):
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
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.REL_MATERIAL_CONSUMPTION
            ):
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
        claim_props["release_metadata"] = self.normalize_execution_metadata(
            metadata or {}
        )
        self._write_props(claim, claim_props)

    def _resolve_queue_worker(
        self,
        *,
        queue_name: str,
        worker_type: WorkerType,
    ):
        worker_key = self.execution.synthetic_worker_key_for_user(
            user_id=self.bdb.app_username,
            service=worker_type == WorkerType.SERVICE,
            scope_key=queue_name,
        )
        display_name = f"{self.bdb.app_username} {queue_name}"
        return self.execution.resolve_synthetic_worker(
            worker_key=worker_key,
            display_name=display_name,
            worker_type=worker_type,
            capabilities=list(self.QUEUE_CAPABILITIES.get(queue_name, [])),
            max_concurrent_leases=64,
            executed_by=self.bdb.app_username,
        )

    def _find_execution_container(self, material):
        for lineage in get_child_lineages(material):
            if lineage.is_deleted or lineage.relationship_type != "contains":
                continue
            parent = lineage.parent_instance
            if (
                parent is None
                or parent.is_deleted
                or instance_semantic_category(parent) != "container"
            ):
                continue
            return parent
        return None

    def _execution_subject_for_material(
        self,
        material,
        *,
        expected_queues: set[str],
    ):
        material_queue = self.execution._authoritative_queue_key_for_instance(material)
        if material_queue in expected_queues:
            return material
        container = self._find_execution_container(material)
        if (
            container is not None
            and self.execution._authoritative_queue_key_for_instance(container)
            in expected_queues
        ):
            return container
        expected = ", ".join(sorted(expected_queues))
        raise ValueError(
            f"Source material must be queued in one of [{expected}] "
            f"(current_queue={material_queue!r})"
        )

    def _complete_stage_execution(
        self,
        *,
        subject,
        lease,
        action_key: str,
        idempotency_key: str,
        result_payload: dict[str, Any],
        next_queue_key: str | None = None,
        next_action_key: str | None = None,
        terminal: bool = True,
    ) -> None:
        worker_euid = str(self.execution._props(lease).get("worker_lookup_euid") or "")
        self.execution.complete_queue_execution(
            CompleteQueueExecutionRequest(
                subject_euid=subject.euid,
                worker_euid=worker_euid,
                lease_euid=lease.euid,
                action_key=action_key,
                expected_state=ExecutionState.READY,
                idempotency_key=idempotency_key,
                next_queue_key=next_queue_key,
                next_action_key=next_action_key,
                result_payload=result_payload,
                terminal=terminal,
            ),
            executed_by=self.bdb.app_username,
        )

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
        queue_subject = self._execution_subject_for_material(
            material,
            expected_queues=expected_queues,
        )
        current_queue = self.execution._authoritative_queue_key_for_instance(
            queue_subject
        )
        if claim_euid:
            lease = self.execution._require_lease(claim_euid)
            lease_subject = self.execution._subject_for_lease(lease)
            if lease_subject is None or lease_subject.euid != queue_subject.euid:
                raise ValueError(
                    "claim_euid does not match source execution subject "
                    f"(claim_euid={claim_euid} material_euid={material.euid})"
                )
            return lease

        worker = self._resolve_queue_worker(
            queue_name=current_queue or "",
            worker_type=WorkerType.SERVICE,
        )
        claim_result = self.execution.claim_queue_item(
            ClaimQueueItemRequest(
                worker_euid=worker.worker_euid,
                queue_key=current_queue or "",
                subject_euid=queue_subject.euid,
                idempotency_key=f"implicit:{stage_label}:{queue_subject.euid}",
                expected_state=ExecutionState.READY,
                payload={"stage": stage_label, "implicit_claim": True},
            ),
            executed_by=self.bdb.app_username,
        )
        return self.execution._require_lease(str(claim_result.lease_euid))

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
        if self.execution._is_execution_instance(claim, subtype="queue_lease"):
            claim_props = self.execution._props(claim)
            lease_status = str(claim_props.get("status") or "").strip().upper()
            release_reason = (
                str(claim_props.get("release_reason") or "").strip().lower()
            )
            display_status = lease_status.lower()
            if lease_status == "RELEASED" and release_reason in {
                "released",
                "completed",
                "abandoned",
            }:
                display_status = release_reason
            return BetaClaimResponse(
                claim_euid=claim.euid,
                material_euid=str(claim_props.get("subject_lookup_euid") or ""),
                queue_name=str(claim_props.get("queue_lookup_key") or ""),
                work_item_euid=claim.euid,
                status=display_status,
                metadata={},
                idempotent_replay=replay,
            )
        claim_props = self._props(claim)
        work_item = self._first_parent(claim, self.REL_WORK_ITEM_CLAIM)
        material = (
            self._first_parent(work_item, self.REL_WORK_ITEM_SUBJECT)
            if work_item is not None
            else None
        )
        return BetaClaimResponse(
            claim_euid=claim.euid,
            material_euid=(
                material.euid
                if material is not None
                else str(claim_props.get("material_euid") or "")
            ),
            queue_name=str(claim_props.get("queue_name") or ""),
            work_item_euid=(
                work_item.euid
                if work_item is not None
                else str(claim_props.get("work_item_euid") or "")
            ),
            status=str(claim_props.get("status") or ""),
            metadata=(
                claim_props.get("metadata")
                if isinstance(claim_props.get("metadata"), dict)
                else {}
            ),
            idempotent_replay=replay,
        )

    def _reservation_response(
        self, reservation, *, replay: bool
    ) -> BetaReservationResponse:
        reservation_props = self._props(reservation)
        material = self._first_parent(reservation, self.REL_MATERIAL_RESERVATION)
        return BetaReservationResponse(
            reservation_euid=reservation.euid,
            material_euid=(
                material.euid
                if material is not None
                else str(reservation_props.get("material_euid") or "")
            ),
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
            material_euid=(
                material.euid
                if material is not None
                else str(props.get("material_euid") or "")
            ),
            consumed=True,
            metadata=props.get("metadata")
            if isinstance(props.get("metadata"), dict)
            else {},
            idempotent_replay=replay,
        )

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
        return self.execution.current_queue_for_instance(instance)
