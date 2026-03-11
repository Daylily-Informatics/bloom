"""TapDB-native execution queue runtime for Bloom."""

from __future__ import annotations

import hashlib
import json
import secrets
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3, get_child_lineages, get_parent_lineages
from bloom_lims.domain.execution_actions import ExecutionQueueActionRecorder
from bloom_lims.schemas.execution_queue import (
    CancelSubjectExecutionRequest,
    ClaimQueueItemRequest,
    CompleteQueueExecutionRequest,
    DeadLetterResolutionState,
    DeadLetterSummary,
    ExecutionActionResponse,
    ExecutionEnvelope,
    ExecutionQueueDetail,
    ExecutionQueueItem,
    ExecutionQueueSummary,
    ExecutionRecordSummary,
    ExecutionState,
    ExpireQueueLeaseRequest,
    FailQueueExecutionRequest,
    HeartbeatWorkerRequest,
    HoldStatus,
    HoldSummary,
    LeaseStatus,
    LeaseSummary,
    PlaceExecutionHoldRequest,
    QueueRetryPolicy,
    QueueSelectionPolicy,
    RecordStatus,
    RegisterWorkerRequest,
    ReleaseExecutionHoldRequest,
    ReleaseQueueLeaseRequest,
    RenewQueueLeaseRequest,
    RequeueSubjectRequest,
    SubjectExecutionDetail,
    SubjectExecutionDiagnostics,
    SubjectExecutionHistory,
    WorkerDetail,
    WorkerStatus,
    WorkerSummary,
    WorkerType,
)


class ExecutionQueueError(Exception):
    """Base execution queue exception."""


class ExecutionQueueConflictError(ExecutionQueueError):
    """Raised for deterministic state/idempotency conflicts."""


class ExecutionQueueNotFoundError(ExecutionQueueError):
    """Raised when queue runtime objects are missing."""


class ExecutionQueuePermissionError(ExecutionQueueError):
    """Raised when ownership or permission checks fail."""


class ExecutionQueueService:
    """Execution queue runtime built on TapDB templates and lineage."""

    EXECUTION_QUEUE_TEMPLATE_CODE = "data/execution/queue/1.0"
    EXECUTION_LEASE_TEMPLATE_CODE = "data/execution/queue_lease/1.0"
    EXECUTION_RECORD_TEMPLATE_CODE = "data/execution/execution_record/1.0"
    EXECUTION_HOLD_TEMPLATE_CODE = "data/execution/hold/1.0"
    EXECUTION_DEAD_LETTER_TEMPLATE_CODE = "data/execution/dead_letter/1.0"
    WORKER_TEMPLATE_CODE = "actor/system/worker/1.0"

    REL_SUBJECT_LEASE = "execution_subject_lease"
    REL_WORKER_LEASE = "execution_worker_lease"
    REL_QUEUE_LEASE = "execution_queue_lease"
    REL_SUBJECT_RECORD = "execution_subject_record"
    REL_WORKER_RECORD = "execution_worker_record"
    REL_QUEUE_RECORD = "execution_queue_record"
    REL_LEASE_RECORD = "execution_lease_record"
    REL_SUBJECT_HOLD = "execution_subject_hold"
    REL_QUEUE_HOLD = "execution_queue_hold"
    REL_ACTOR_HOLD = "execution_actor_hold"
    REL_SUBJECT_DEAD_LETTER = "execution_subject_dead_letter"
    REL_QUEUE_DEAD_LETTER = "execution_queue_dead_letter"
    REL_RECORD_DEAD_LETTER = "execution_record_dead_letter"

    LEGACY_REL_QUEUE_MEMBERSHIP = "beta_queue_membership"

    DEFAULT_RETRY_POLICY = QueueRetryPolicy().model_dump()
    DEFAULT_SELECTION_POLICY = QueueSelectionPolicy().model_dump()

    WETLAB_QUEUE_DEFAULTS: dict[str, dict[str, Any]] = {
        "extraction_prod": {
            "display_name": "Extraction / Production",
            "dispatch_priority": 100,
            "subject_template_codes": [
                "container/tube/tube-generic-10ml/1.0",
                "content/specimen/blood-whole/1.0",
            ],
            "required_worker_capabilities": ["wetlab.extraction"],
        },
        "extraction_rnd": {
            "display_name": "Extraction / R&D",
            "dispatch_priority": 90,
            "subject_template_codes": [
                "container/tube/tube-generic-10ml/1.0",
                "content/specimen/blood-whole/1.0",
            ],
            "required_worker_capabilities": ["wetlab.extraction"],
        },
        "post_extract_qc": {
            "display_name": "Post-Extract QC",
            "dispatch_priority": 100,
            "subject_template_codes": [
                "content/sample/cfdna/1.0",
                "content/sample/gdna/1.0",
            ],
            "required_worker_capabilities": ["wetlab.post_extract_qc"],
        },
        "ilmn_lib_prep": {
            "display_name": "Illumina Library Prep",
            "dispatch_priority": 100,
            "subject_template_codes": [
                "content/sample/cfdna/1.0",
                "content/sample/gdna/1.0",
            ],
            "required_worker_capabilities": ["wetlab.library_prep", "platform.ILMN"],
        },
        "ont_lib_prep": {
            "display_name": "ONT Library Prep",
            "dispatch_priority": 100,
            "subject_template_codes": [
                "content/sample/cfdna/1.0",
                "content/sample/gdna/1.0",
            ],
            "required_worker_capabilities": ["wetlab.library_prep", "platform.ONT"],
        },
        "ilmn_seq_pool": {
            "display_name": "Illumina Sequencing Pool",
            "dispatch_priority": 100,
            "subject_template_codes": ["data/wetlab/library_prep_output/1.0"],
            "required_worker_capabilities": ["wetlab.pooling", "platform.ILMN"],
        },
        "ont_seq_pool": {
            "display_name": "ONT Sequencing Pool",
            "dispatch_priority": 100,
            "subject_template_codes": ["data/wetlab/library_prep_output/1.0"],
            "required_worker_capabilities": ["wetlab.pooling", "platform.ONT"],
        },
        "ilmn_start_seq_run": {
            "display_name": "Illumina Start Run",
            "dispatch_priority": 100,
            "subject_template_codes": ["content/pool/generic/1.0"],
            "required_worker_capabilities": ["wetlab.run_start", "platform.ILMN"],
        },
        "ont_start_seq_run": {
            "display_name": "ONT Start Run",
            "dispatch_priority": 100,
            "subject_template_codes": ["content/pool/generic/1.0"],
            "required_worker_capabilities": ["wetlab.run_start", "platform.ONT"],
        },
    }

    def __init__(
        self,
        *,
        app_username: str,
        bdb: BLOOMdb3 | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.bdb = bdb if bdb is not None else BLOOMdb3(app_username=app_username)
        self._owns_bdb = bdb is None
        self.bobj = BloomObj(self.bdb)
        self.action_recorder = ExecutionQueueActionRecorder(self.bdb.session)
        self.clock = clock or (lambda: datetime.now(UTC))

    def close(self) -> None:
        if self._owns_bdb:
            self.bdb.close()

    def ensure_default_queue_definitions(self) -> None:
        for queue_key, defaults in self.WETLAB_QUEUE_DEFAULTS.items():
            queue = self._find_queue_by_key(queue_key)
            if queue is not None:
                continue
            queue = self.bobj.create_instance_by_code(
                self.EXECUTION_QUEUE_TEMPLATE_CODE,
                {"json_addl": {"properties": self._queue_definition_defaults(queue_key, defaults)}},
            )
            queue.name = defaults["display_name"]
            props = self._props(queue)
            props["name"] = queue.name
            self._write_props(queue, props)
        self.bdb.session.flush()

    def register_worker(
        self,
        payload: RegisterWorkerRequest,
        *,
        executed_by: str | None,
    ) -> WorkerDetail:
        worker = self._find_worker_by_key(payload.worker_key)
        if worker is None:
            worker = self.bobj.create_instance_by_code(
                self.WORKER_TEMPLATE_CODE,
                {"json_addl": {"properties": {}}},
            )
        props = self._props(worker)
        props.update(
            {
                "worker_key": payload.worker_key,
                "display_name": payload.display_name,
                "worker_type": payload.worker_type.value,
                "status": payload.status.value,
                "capabilities": list(payload.capabilities),
                "site_scope": list(payload.site_scope),
                "platform_scope": list(payload.platform_scope),
                "assay_scope": list(payload.assay_scope),
                "max_concurrent_leases": payload.max_concurrent_leases,
                "heartbeat_at": self._timestamp(),
                "heartbeat_ttl_seconds": payload.heartbeat_ttl_seconds,
                "build_version": payload.build_version,
                "host": payload.host,
                "process_identity": payload.process_identity,
                "drain_requested": payload.drain_requested,
                "disabled_reason": None,
                "revision": int(props.get("revision") or 0) + 1,
            }
        )
        worker.name = payload.display_name
        props["name"] = payload.display_name
        self._write_props(worker, props)
        self.action_recorder.record(
            target_instance=worker,
            action_key="register_worker",
            captured_data=payload.model_dump(),
            result={"status": "success", "worker_euid": worker.euid},
            executed_by=executed_by,
            subject_euid=None,
            worker_euid=worker.euid,
            lease_euid=None,
            idempotency_key="",
            payload_hash=self._payload_hash(payload.model_dump()),
        )
        self.bdb.session.commit()
        return self._worker_detail(worker)

    def heartbeat_worker(
        self,
        payload: HeartbeatWorkerRequest,
        *,
        executed_by: str | None,
    ) -> WorkerDetail:
        worker = self._require_worker(payload.worker_euid)
        props = self._props(worker)
        props["heartbeat_at"] = self._timestamp()
        if payload.status is not None and str(props.get("status") or "") != WorkerStatus.DISABLED.value:
            props["status"] = payload.status.value
        if payload.last_error_at is not None:
            props["last_error_at"] = payload.last_error_at
        if payload.last_error_class is not None:
            props["last_error_class"] = payload.last_error_class
        if payload.host is not None:
            props["host"] = payload.host
        if payload.process_identity is not None:
            props["process_identity"] = payload.process_identity
        props["revision"] = int(props.get("revision") or 0) + 1
        self._write_props(worker, props)
        self.action_recorder.record(
            target_instance=worker,
            action_key="heartbeat_worker",
            captured_data=payload.model_dump(),
            result={"status": "success", "worker_euid": worker.euid},
            executed_by=executed_by,
            subject_euid=None,
            worker_euid=worker.euid,
            lease_euid=None,
            idempotency_key="",
            payload_hash=self._payload_hash(payload.model_dump()),
        )
        self.bdb.session.commit()
        return self._worker_detail(worker)

    def list_queues(self) -> list[ExecutionQueueSummary]:
        self.ensure_default_queue_definitions()
        now = self.clock()
        return [self._queue_summary(queue, now=now) for queue in self._all_execution_queues()]

    def get_queue(self, queue_key: str) -> ExecutionQueueDetail:
        self.ensure_default_queue_definitions()
        queue = self._require_queue(queue_key)
        summary = self._queue_summary(queue, now=self.clock())
        props = self._props(queue)
        return ExecutionQueueDetail(
            **summary.model_dump(),
            subject_template_codes=list(props.get("subject_template_codes") or []),
            eligible_states=[
                ExecutionState(str(value))
                for value in list(props.get("eligible_states") or [])
            ],
            required_worker_capabilities=list(props.get("required_worker_capabilities") or []),
            site_scope=list(props.get("site_scope") or []),
            platform_scope=list(props.get("platform_scope") or []),
            assay_scope=list(props.get("assay_scope") or []),
            lease_ttl_seconds=int(props.get("lease_ttl_seconds") or 900),
            max_attempts_default=int(props.get("max_attempts_default") or 5),
            retry_policy=QueueRetryPolicy(**dict(props.get("retry_policy") or {})),
            selection_policy=QueueSelectionPolicy(**dict(props.get("selection_policy") or {})),
            diagnostics_enabled=bool(props.get("diagnostics_enabled", True)),
            revision=int(props.get("revision") or 1),
            disabled_reason=str(props.get("disabled_reason") or "") or None,
        )

    def list_queue_items(self, queue_key: str) -> list[ExecutionQueueItem]:
        self.ensure_default_queue_definitions()
        queue = self._require_queue(queue_key)
        return [self._queue_item(instance) for instance in self._visible_queue_items(queue, self.clock())]

    def list_workers(self) -> list[WorkerSummary]:
        now = self.clock()
        return [self._worker_summary(worker, now=now) for worker in self._all_workers()]

    def get_worker(self, worker_euid: str) -> WorkerDetail:
        return self._worker_detail(self._require_worker(worker_euid))

    def list_leases(self, *, status: str | None = None) -> list[LeaseSummary]:
        leases = self._all_execution_instances(subtype="queue_lease")
        if status:
            clean = str(status).strip().upper()
            leases = [
                lease
                for lease in leases
                if str(self._props(lease).get("status") or "").strip().upper() == clean
            ]
        return [self._lease_summary(lease) for lease in leases]

    def list_dead_letters(self) -> list[DeadLetterSummary]:
        return [
            self._dead_letter_summary(record)
            for record in self._all_execution_instances(subtype="dead_letter")
        ]

    def get_subject_detail(self, subject_euid: str) -> SubjectExecutionDetail:
        subject = self._require_instance(subject_euid)
        execution = ExecutionEnvelope(**self._ensure_execution_envelope(subject, write=False))
        diagnostics = self._subject_diagnostics(subject, queue_key=execution.next_queue_key)
        active_holds = [
            self._hold_summary(hold)
            for hold in self._active_holds_for_subject(subject)
        ]
        dead_letter = self._latest_dead_letter_for_subject(subject)
        return SubjectExecutionDetail(
            subject_euid=subject.euid,
            subject_name=subject.name,
            subject_category=str(subject.category or ""),
            template_code=self._template_code(subject),
            execution=execution,
            diagnostics=diagnostics,
            active_lease=self._lease_summary(self._active_lease_for_subject(subject, self.clock()))
            if self._active_lease_for_subject(subject, self.clock()) is not None
            else None,
            active_holds=active_holds,
            dead_letter=self._dead_letter_summary(dead_letter) if dead_letter is not None else None,
        )

    def get_subject_history(self, subject_euid: str) -> SubjectExecutionHistory:
        subject = self._require_instance(subject_euid)
        records = [
            self._record_summary(record)
            for record in self._records_for_subject(subject)
        ]
        leases = [
            self._lease_summary(lease)
            for lease in self._leases_for_subject(subject)
        ]
        holds = [self._hold_summary(hold) for hold in self._holds_for_subject(subject)]
        dead_letters = [
            self._dead_letter_summary(record)
            for record in self._dead_letters_for_subject(subject)
        ]
        return SubjectExecutionHistory(
            subject_euid=subject.euid,
            records=records,
            leases=leases,
            holds=holds,
            dead_letters=dead_letters,
        )

    def claim_queue_item(
        self,
        payload: ClaimQueueItemRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        self.ensure_default_queue_definitions()
        payload_hash = self._payload_hash(payload.model_dump())
        replay = self._maybe_replay_action(
            action_key="claim_queue_item",
            subject_euid=payload.subject_euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return replay

        worker = self._lock_worker(payload.worker_euid)
        queue = self._require_queue(payload.queue_key)
        self._assert_worker_can_claim(worker, queue)
        subject = self._lock_subject(
            payload.subject_euid
            or self._next_visible_subject_euid(queue, now=self.clock())
        )
        if subject is None:
            raise ExecutionQueueNotFoundError("No visible queue item found to claim")
        self._assert_subject_visible_in_queue(subject, queue, now=self.clock())
        if self._active_lease_for_subject(subject, self.clock()) is not None:
            raise ExecutionQueueConflictError(
                f"Subject already has an active lease: {subject.euid}"
            )

        execution = self._ensure_execution_envelope(subject, write=True)
        attempt_number = int(execution.get("attempt_count") or 0) + 1
        queue_props = self._props(queue)
        lease_ttl_seconds = int(queue_props.get("lease_ttl_seconds") or 900)
        now = self.clock()
        lease = self._create_execution_instance(
            self.EXECUTION_LEASE_TEMPLATE_CODE,
            name=f"lease:{payload.queue_key}:{subject.euid}",
            properties={
                "lease_token": self._random_token(),
                "queue_lookup_key": payload.queue_key,
                "subject_lookup_euid": subject.euid,
                "worker_lookup_euid": worker.euid,
                "status": LeaseStatus.ACTIVE.value,
                "claimed_at": self._timestamp(now),
                "heartbeat_at": self._timestamp(now),
                "expires_at": self._timestamp(now + timedelta(seconds=lease_ttl_seconds)),
                "released_at": None,
                "release_reason": None,
                "attempt_number": attempt_number,
                "ttl_seconds": lease_ttl_seconds,
                "next_action_key": execution.get("next_action_key"),
                "idempotency_key": payload.idempotency_key,
                "subject_revision_at_claim": int(execution.get("revision") or 1),
                "payload_hash": payload_hash,
            },
        )
        self._link(subject, lease, self.REL_SUBJECT_LEASE)
        self._link(worker, lease, self.REL_WORKER_LEASE)
        self._link(queue, lease, self.REL_QUEUE_LEASE)

        record = self._create_execution_instance(
            self.EXECUTION_RECORD_TEMPLATE_CODE,
            name=f"record:{payload.queue_key}:{subject.euid}:{attempt_number}",
            properties={
                "subject_lookup_euid": subject.euid,
                "queue_lookup_key": payload.queue_key,
                "worker_lookup_euid": worker.euid,
                "lease_lookup_euid": lease.euid,
                "attempt_number": attempt_number,
                "status": RecordStatus.STARTED.value,
                "action_key": str(execution.get("next_action_key") or ""),
                "idempotency_key": payload.idempotency_key,
                "payload_hash": payload_hash,
                "expected_state": payload.expected_state.value,
                "start_state": execution.get("state"),
                "end_state": None,
                "start_revision": int(execution.get("revision") or 1),
                "end_revision": None,
                "started_at": self._timestamp(now),
                "finished_at": None,
                "duration_ms": None,
                "retryable": False,
                "error_class": None,
                "error_code": None,
                "error_message": None,
                "correlation": {},
                "input_snapshot": payload.payload,
                "result_snapshot": {},
                "policy_refs": [],
            },
        )
        self._link(subject, record, self.REL_SUBJECT_RECORD)
        self._link(worker, record, self.REL_WORKER_RECORD)
        self._link(queue, record, self.REL_QUEUE_RECORD)
        self._link(lease, record, self.REL_LEASE_RECORD)

        execution["queue_cache"]["current_queue_key"] = payload.queue_key
        execution["queue_cache"]["computed_at"] = self._timestamp(now)
        execution["last_execution_record_euid"] = record.euid
        self._set_execution_envelope(subject, execution)

        self.action_recorder.record(
            target_instance=subject,
            action_key="claim_queue_item",
            captured_data=payload.model_dump(),
            result={
                "status": "success",
                "lease_euid": lease.euid,
                "subject_euid": subject.euid,
                "queue_key": payload.queue_key,
                "worker_euid": worker.euid,
                "execution_record_euid": record.euid,
            },
            executed_by=executed_by,
            subject_euid=subject.euid,
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="claim_queue_item",
            subject_euid=subject.euid,
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            replayed=False,
            result={
                "queue_key": payload.queue_key,
                "lease": self._lease_summary(lease).model_dump(),
                "record_euid": record.euid,
            },
        )

    def renew_queue_lease(
        self,
        payload: RenewQueueLeaseRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        lease = self._require_lease(payload.lease_euid)
        worker = self._require_worker(payload.worker_euid)
        self._assert_worker_owns_lease(worker, lease)
        now = self.clock()
        props = self._props(lease)
        if str(props.get("status") or "") != LeaseStatus.ACTIVE.value:
            raise ExecutionQueueConflictError(f"Lease is not active: {lease.euid}")
        if self._lease_expired(lease, now):
            raise ExecutionQueueConflictError(f"Lease already expired: {lease.euid}")
        ttl_seconds = int(props.get("ttl_seconds") or 900)
        props["heartbeat_at"] = self._timestamp(now)
        props["expires_at"] = self._timestamp(now + timedelta(seconds=ttl_seconds))
        self._write_props(lease, props)
        payload_hash = self._payload_hash(payload.model_dump())
        self.action_recorder.record(
            target_instance=lease,
            action_key="renew_queue_lease",
            captured_data=payload.model_dump(),
            result={"status": "success", "lease_euid": lease.euid},
            executed_by=executed_by,
            subject_euid=str(props.get("subject_lookup_euid") or ""),
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="renew_queue_lease",
            subject_euid=str(props.get("subject_lookup_euid") or ""),
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            result={"lease": self._lease_summary(lease).model_dump()},
        )

    def release_queue_lease(
        self,
        payload: ReleaseQueueLeaseRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        lease = self._require_lease(payload.lease_euid)
        worker = self._require_worker(payload.worker_euid)
        self._assert_worker_owns_lease(worker, lease)
        self._transition_lease_to_terminal(
            lease,
            status=LeaseStatus.RELEASED,
            reason=payload.reason or "released",
        )
        payload_hash = self._payload_hash(payload.model_dump())
        self.action_recorder.record(
            target_instance=lease,
            action_key="release_queue_lease",
            captured_data=payload.model_dump(),
            result={"status": "success", "lease_euid": lease.euid},
            executed_by=executed_by,
            subject_euid=str(self._props(lease).get("subject_lookup_euid") or ""),
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="release_queue_lease",
            subject_euid=str(self._props(lease).get("subject_lookup_euid") or ""),
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            result={"lease": self._lease_summary(lease).model_dump()},
        )

    def complete_queue_execution(
        self,
        payload: CompleteQueueExecutionRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        payload_hash = self._payload_hash(payload.model_dump())
        replay = self._maybe_replay_action(
            action_key="complete_queue_execution",
            subject_euid=payload.subject_euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return replay

        subject = self._lock_subject(payload.subject_euid)
        worker = self._require_worker(payload.worker_euid)
        lease = self._require_lease(payload.lease_euid)
        self._assert_worker_owns_lease(worker, lease)
        self._assert_lease_active_for_subject(subject, lease, now=self.clock())

        execution = self._ensure_execution_envelope(subject, write=True)
        self._assert_expected_state(subject, execution, payload.expected_state, payload.expected_revision)

        next_state = ExecutionState.COMPLETED if payload.terminal or not payload.next_queue_key else ExecutionState.READY
        if str(execution.get("state") or "") == ExecutionState.WAITING_EXTERNAL.value:
            next_state = ExecutionState.READY if payload.next_queue_key else ExecutionState.COMPLETED
        execution["state"] = next_state.value
        execution["revision"] = int(execution.get("revision") or 1) + 1
        execution["next_queue_key"] = payload.next_queue_key
        execution["next_action_key"] = payload.next_action_key
        execution["ready_at"] = self._timestamp()
        execution["retry_at"] = None
        execution["terminal"] = bool(payload.terminal or not payload.next_queue_key)
        execution["cancel_requested"] = False

        record = self._active_record_for_lease(lease)
        if record is None:
            raise ExecutionQueueConflictError(f"Active execution record not found for lease {lease.euid}")
        self._finalize_record(
            record,
            status=RecordStatus.SUCCEEDED,
            end_state=next_state.value,
            end_revision=int(execution["revision"]),
            result_snapshot=payload.result_payload,
            retryable=False,
        )
        execution["last_execution_record_euid"] = record.euid
        execution["queue_cache"]["current_queue_key"] = payload.next_queue_key
        execution["queue_cache"]["computed_at"] = self._timestamp()
        self._set_execution_envelope(subject, execution)
        self._transition_lease_to_terminal(lease, status=LeaseStatus.COMPLETED, reason="completed")

        self.action_recorder.record(
            target_instance=subject,
            action_key="complete_queue_execution",
            captured_data=payload.model_dump(),
            result={
                "status": "success",
                "subject_euid": subject.euid,
                "lease_euid": lease.euid,
                "record_euid": record.euid,
                "next_queue_key": payload.next_queue_key,
            },
            executed_by=executed_by,
            subject_euid=subject.euid,
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="complete_queue_execution",
            subject_euid=subject.euid,
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            result={"execution": execution, "record_euid": record.euid},
        )

    def fail_queue_execution(
        self,
        payload: FailQueueExecutionRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        payload_hash = self._payload_hash(payload.model_dump())
        replay = self._maybe_replay_action(
            action_key="fail_queue_execution",
            subject_euid=payload.subject_euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return replay

        subject = self._lock_subject(payload.subject_euid)
        worker = self._require_worker(payload.worker_euid)
        lease = self._require_lease(payload.lease_euid)
        self._assert_worker_owns_lease(worker, lease)
        self._assert_lease_active_for_subject(subject, lease, now=self.clock())

        execution = self._ensure_execution_envelope(subject, write=True)
        self._assert_expected_state(subject, execution, payload.expected_state, payload.expected_revision)

        queue_key = str(self._props(lease).get("queue_lookup_key") or execution.get("next_queue_key") or "")
        queue = self._require_queue(queue_key)
        queue_props = self._props(queue)
        execution["attempt_count"] = int(execution.get("attempt_count") or 0) + 1
        max_attempts = int(
            execution.get("max_attempts_override")
            or queue_props.get("max_attempts_default")
            or 5
        )

        record = self._active_record_for_lease(lease)
        if record is None:
            raise ExecutionQueueConflictError(f"Active execution record not found for lease {lease.euid}")

        dead_letter_euid: str | None = None
        if payload.retryable and int(execution["attempt_count"]) < max_attempts:
            retry_at = self._compute_retry_at(
                queue_props=dict(queue_props),
                attempt_count=int(execution["attempt_count"]),
            )
            execution["state"] = ExecutionState.FAILED_RETRYABLE.value
            execution["retry_at"] = self._timestamp(retry_at)
            execution["terminal"] = False
            execution["next_queue_key"] = queue_key
            self._finalize_record(
                record,
                status=RecordStatus.FAILED_RETRYABLE,
                end_state=ExecutionState.FAILED_RETRYABLE.value,
                end_revision=int(execution.get("revision") or 1) + 1,
                result_snapshot=payload.result_payload,
                retryable=True,
                error_class=payload.error_class,
                error_code=payload.error_code,
                error_message=payload.error_message,
            )
            self._transition_lease_to_terminal(lease, status=LeaseStatus.RELEASED, reason="retryable_failure")
        else:
            execution["state"] = ExecutionState.FAILED_TERMINAL.value
            execution["retry_at"] = None
            execution["terminal"] = True
            self._finalize_record(
                record,
                status=RecordStatus.FAILED_TERMINAL,
                end_state=ExecutionState.FAILED_TERMINAL.value,
                end_revision=int(execution.get("revision") or 1) + 1,
                result_snapshot=payload.result_payload,
                retryable=False,
                error_class=payload.error_class,
                error_code=payload.error_code,
                error_message=payload.error_message,
            )
            self._transition_lease_to_terminal(lease, status=LeaseStatus.RELEASED, reason="terminal_failure")
            dead_letter = self._create_dead_letter(subject, queue, record, lease, payload)
            dead_letter_euid = dead_letter.euid
        execution["revision"] = int(execution.get("revision") or 1) + 1
        execution["last_execution_record_euid"] = record.euid
        execution["queue_cache"]["current_queue_key"] = execution.get("next_queue_key")
        execution["queue_cache"]["computed_at"] = self._timestamp()
        self._set_execution_envelope(subject, execution)

        self.action_recorder.record(
            target_instance=subject,
            action_key="fail_queue_execution",
            captured_data=payload.model_dump(),
            result={
                "status": "success",
                "subject_euid": subject.euid,
                "lease_euid": lease.euid,
                "record_euid": record.euid,
                "dead_letter_euid": dead_letter_euid,
            },
            executed_by=executed_by,
            subject_euid=subject.euid,
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="fail_queue_execution",
            subject_euid=subject.euid,
            worker_euid=worker.euid,
            lease_euid=lease.euid,
            dead_letter_euid=dead_letter_euid,
            result={"execution": execution, "record_euid": record.euid},
        )

    def place_execution_hold(
        self,
        payload: PlaceExecutionHoldRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        payload_hash = self._payload_hash(payload.model_dump())
        replay = self._maybe_replay_action(
            action_key="place_execution_hold",
            subject_euid=payload.subject_euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return replay

        subject = self._lock_subject(payload.subject_euid)
        placed_by = self._require_worker(payload.placed_by_worker_euid)
        queue = self._find_queue_by_key(payload.queue_key) if payload.queue_key else None
        execution = self._ensure_execution_envelope(subject, write=True)
        execution["state"] = ExecutionState.HELD.value
        execution["hold_state"] = "ACTIVE"
        execution["hold_reason"] = payload.reason
        execution["revision"] = int(execution.get("revision") or 1) + 1
        self._set_execution_envelope(subject, execution)

        hold = self._create_execution_instance(
            self.EXECUTION_HOLD_TEMPLATE_CODE,
            name=f"hold:{payload.hold_code}:{subject.euid}",
            properties={
                "subject_lookup_euid": subject.euid,
                "queue_lookup_key": payload.queue_key,
                "placed_by_lookup_euid": placed_by.euid,
                "status": HoldStatus.ACTIVE.value,
                "hold_code": payload.hold_code,
                "reason": payload.reason,
                "placed_at": self._timestamp(),
                "released_at": None,
                "released_by_lookup_euid": None,
            },
        )
        self._link(subject, hold, self.REL_SUBJECT_HOLD)
        self._link(placed_by, hold, self.REL_ACTOR_HOLD)
        if queue is not None:
            self._link(queue, hold, self.REL_QUEUE_HOLD)

        self.action_recorder.record(
            target_instance=subject,
            action_key="place_execution_hold",
            captured_data=payload.model_dump(),
            result={"status": "success", "hold_euid": hold.euid},
            executed_by=executed_by,
            subject_euid=subject.euid,
            worker_euid=placed_by.euid,
            lease_euid=None,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="place_execution_hold",
            subject_euid=subject.euid,
            worker_euid=placed_by.euid,
            hold_euid=hold.euid,
            result={"hold": self._hold_summary(hold).model_dump()},
        )

    def release_execution_hold(
        self,
        payload: ReleaseExecutionHoldRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        hold = self._require_hold(payload.hold_euid)
        released_by = self._require_worker(payload.released_by_worker_euid)
        subject = self._subject_for_hold(hold)
        if subject is None:
            raise ExecutionQueueConflictError(f"Hold subject not found: {hold.euid}")
        props = self._props(hold)
        props["status"] = HoldStatus.RELEASED.value
        props["released_at"] = self._timestamp()
        props["released_by_lookup_euid"] = released_by.euid
        self._write_props(hold, props)
        execution = self._ensure_execution_envelope(subject, write=True)
        execution["hold_state"] = "NONE"
        execution["hold_reason"] = None
        if execution.get("state") == ExecutionState.HELD.value:
            execution["state"] = (
                ExecutionState.FAILED_RETRYABLE.value
                if execution.get("retry_at")
                else ExecutionState.READY.value
            )
        execution["revision"] = int(execution.get("revision") or 1) + 1
        self._set_execution_envelope(subject, execution)
        payload_hash = self._payload_hash(payload.model_dump())
        self.action_recorder.record(
            target_instance=subject,
            action_key="release_execution_hold",
            captured_data=payload.model_dump(),
            result={"status": "success", "hold_euid": hold.euid},
            executed_by=executed_by,
            subject_euid=subject.euid,
            worker_euid=released_by.euid,
            lease_euid=None,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="release_execution_hold",
            subject_euid=subject.euid,
            worker_euid=released_by.euid,
            hold_euid=hold.euid,
            result={"hold": self._hold_summary(hold).model_dump()},
        )

    def requeue_subject(
        self,
        payload: RequeueSubjectRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        self.ensure_default_queue_definitions()
        payload_hash = self._payload_hash(payload.model_dump())
        replay = self._maybe_replay_action(
            action_key="requeue_subject",
            subject_euid=payload.subject_euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return replay

        subject = self._lock_subject(payload.subject_euid)
        self._require_queue(payload.queue_key)
        execution = self._ensure_execution_envelope(subject, write=True)
        if payload.expected_state is not None:
            self._assert_expected_state(subject, execution, payload.expected_state, payload.expected_revision)
        execution["state"] = ExecutionState.READY.value
        execution["next_queue_key"] = payload.queue_key
        execution["next_action_key"] = payload.next_action_key
        if payload.priority is not None:
            execution["priority"] = payload.priority
        if payload.ready_at is not None:
            execution["ready_at"] = payload.ready_at
        if payload.due_at is not None:
            execution["due_at"] = payload.due_at
        execution["retry_at"] = None
        execution["hold_state"] = "NONE"
        execution["hold_reason"] = None
        execution["cancel_requested"] = False
        execution["terminal"] = False
        execution["revision"] = int(execution.get("revision") or 1) + 1
        execution["queue_cache"]["current_queue_key"] = payload.queue_key
        execution["queue_cache"]["computed_at"] = self._timestamp()
        self._set_execution_envelope(subject, execution)
        self.action_recorder.record(
            target_instance=subject,
            action_key="requeue_subject",
            captured_data=payload.model_dump(),
            result={"status": "success", "subject_euid": subject.euid, "queue_key": payload.queue_key},
            executed_by=executed_by,
            subject_euid=subject.euid,
            worker_euid=None,
            lease_euid=None,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="requeue_subject",
            subject_euid=subject.euid,
            result={"execution": execution},
        )

    def cancel_subject_execution(
        self,
        payload: CancelSubjectExecutionRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        payload_hash = self._payload_hash(payload.model_dump())
        replay = self._maybe_replay_action(
            action_key="cancel_subject_execution",
            subject_euid=payload.subject_euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return replay
        subject = self._lock_subject(payload.subject_euid)
        execution = self._ensure_execution_envelope(subject, write=True)
        if payload.expected_state is not None:
            self._assert_expected_state(subject, execution, payload.expected_state, payload.expected_revision)
        execution["state"] = ExecutionState.CANCELED.value
        execution["cancel_requested"] = True
        execution["terminal"] = True
        execution["next_queue_key"] = None
        execution["next_action_key"] = None
        execution["revision"] = int(execution.get("revision") or 1) + 1
        execution["queue_cache"]["current_queue_key"] = None
        execution["queue_cache"]["computed_at"] = self._timestamp()
        self._set_execution_envelope(subject, execution)
        self.action_recorder.record(
            target_instance=subject,
            action_key="cancel_subject_execution",
            captured_data=payload.model_dump(),
            result={"status": "success", "subject_euid": subject.euid},
            executed_by=executed_by,
            subject_euid=subject.euid,
            worker_euid=None,
            lease_euid=None,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="cancel_subject_execution",
            subject_euid=subject.euid,
            result={"execution": execution},
        )

    def expire_queue_lease(
        self,
        payload: ExpireQueueLeaseRequest,
        *,
        executed_by: str | None,
    ) -> ExecutionActionResponse:
        lease = self._require_lease(payload.lease_euid)
        if str(self._props(lease).get("status") or "") == LeaseStatus.EXPIRED.value:
            return ExecutionActionResponse(
                status="success",
                action_key="expire_queue_lease",
                lease_euid=lease.euid,
                replayed=True,
                result={"lease": self._lease_summary(lease).model_dump()},
            )
        self._transition_lease_to_terminal(
            lease,
            status=LeaseStatus.EXPIRED,
            reason=payload.reason or "HEARTBEAT_TIMEOUT",
        )
        payload_hash = self._payload_hash(payload.model_dump())
        self.action_recorder.record(
            target_instance=lease,
            action_key="expire_queue_lease",
            captured_data=payload.model_dump(),
            result={"status": "success", "lease_euid": lease.euid},
            executed_by=executed_by,
            subject_euid=str(self._props(lease).get("subject_lookup_euid") or ""),
            worker_euid=str(self._props(lease).get("worker_lookup_euid") or ""),
            lease_euid=lease.euid,
            idempotency_key=payload.idempotency_key,
            payload_hash=payload_hash,
        )
        self.bdb.session.commit()
        return ExecutionActionResponse(
            status="success",
            action_key="expire_queue_lease",
            lease_euid=lease.euid,
            result={"lease": self._lease_summary(lease).model_dump()},
        )

    def resolve_synthetic_worker(
        self,
        *,
        worker_key: str,
        display_name: str,
        worker_type: WorkerType,
        capabilities: list[str],
        executed_by: str | None,
        max_concurrent_leases: int = 1,
    ) -> WorkerDetail:
        return self.register_worker(
            RegisterWorkerRequest(
                worker_key=worker_key,
                display_name=display_name,
                worker_type=worker_type,
                capabilities=capabilities,
                max_concurrent_leases=max_concurrent_leases,
                heartbeat_ttl_seconds=60,
                status=WorkerStatus.ONLINE,
            ),
            executed_by=executed_by,
        )

    def queue_subject(
        self,
        *,
        subject_euid: str,
        queue_key: str,
        next_action_key: str | None,
        idempotency_key: str,
        executed_by: str | None,
        priority: int | None = None,
    ) -> ExecutionActionResponse:
        return self.requeue_subject(
            RequeueSubjectRequest(
                subject_euid=subject_euid,
                queue_key=queue_key,
                next_action_key=next_action_key,
                priority=priority,
                idempotency_key=idempotency_key,
            ),
            executed_by=executed_by,
        )

    def current_queue_for_instance(self, instance) -> str | None:
        queue_key = self._authoritative_queue_key_for_instance(instance)
        if queue_key:
            return queue_key
        for lineage in get_child_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != "contains":
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted or parent.category != "container":
                continue
            container_queue = self.current_queue_for_instance(parent)
            if container_queue:
                return container_queue
        return None

    def synthetic_worker_key_for_user(
        self,
        *,
        user_id: str,
        service: bool,
        scope_key: str | None = None,
    ) -> str:
        kind = "service" if service else "human"
        normalized_scope = str(scope_key or "").strip().replace(" ", "-")
        if normalized_scope:
            return f"worker://bloom/{kind}/{user_id}/{normalized_scope}"
        return f"worker://bloom/{kind}/{user_id}"

    def _queue_definition_defaults(self, queue_key: str, defaults: dict[str, Any]) -> dict[str, Any]:
        return {
            "queue_key": queue_key,
            "display_name": defaults["display_name"],
            "enabled": True,
            "manual_only": False,
            "operator_visible": True,
            "dispatch_priority": int(defaults.get("dispatch_priority") or 100),
            "subject_template_codes": list(defaults.get("subject_template_codes") or []),
            "eligible_states": [
                ExecutionState.READY.value,
                ExecutionState.FAILED_RETRYABLE.value,
            ],
            "required_worker_capabilities": list(defaults.get("required_worker_capabilities") or []),
            "site_scope": [],
            "platform_scope": [],
            "assay_scope": [],
            "lease_ttl_seconds": 900,
            "max_attempts_default": 5,
            "retry_policy": deepcopy(self.DEFAULT_RETRY_POLICY),
            "selection_policy": deepcopy(self.DEFAULT_SELECTION_POLICY),
            "diagnostics_enabled": True,
            "revision": 1,
            "disabled_reason": None,
        }

    def _create_dead_letter(self, subject, queue, record, lease, payload: FailQueueExecutionRequest):
        dead_letter = self._create_execution_instance(
            self.EXECUTION_DEAD_LETTER_TEMPLATE_CODE,
            name=f"dead-letter:{queue.euid}:{subject.euid}",
            properties={
                "subject_lookup_euid": subject.euid,
                "queue_lookup_key": str(self._props(queue).get("queue_key") or ""),
                "last_execution_record_lookup_euid": record.euid,
                "last_lease_lookup_euid": lease.euid,
                "dead_lettered_at": self._timestamp(),
                "failure_count": int(self._ensure_execution_envelope(subject, write=False).get("attempt_count") or 0),
                "error_class": payload.error_class,
                "error_message": payload.error_message,
                "resolution_state": DeadLetterResolutionState.OPEN.value,
                "resolved_by_lookup_euid": None,
                "resolved_at": None,
            },
        )
        self._link(subject, dead_letter, self.REL_SUBJECT_DEAD_LETTER)
        self._link(queue, dead_letter, self.REL_QUEUE_DEAD_LETTER)
        self._link(record, dead_letter, self.REL_RECORD_DEAD_LETTER)
        return dead_letter

    def _records_for_subject(self, subject) -> list[Any]:
        records: list[Any] = []
        for lineage in get_parent_lineages(subject):
            if lineage.is_deleted or lineage.relationship_type != self.REL_SUBJECT_RECORD:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="execution_record"):
                records.append(child)
        records.sort(key=lambda row: row.created_dt or datetime.min.replace(tzinfo=UTC), reverse=True)
        return records

    def _leases_for_subject(self, subject) -> list[Any]:
        leases: list[Any] = []
        for lineage in get_parent_lineages(subject):
            if lineage.is_deleted or lineage.relationship_type != self.REL_SUBJECT_LEASE:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="queue_lease"):
                leases.append(child)
        leases.sort(key=lambda row: row.created_dt or datetime.min.replace(tzinfo=UTC), reverse=True)
        return leases

    def _holds_for_subject(self, subject) -> list[Any]:
        holds: list[Any] = []
        for lineage in get_parent_lineages(subject):
            if lineage.is_deleted or lineage.relationship_type != self.REL_SUBJECT_HOLD:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="hold"):
                holds.append(child)
        holds.sort(key=lambda row: row.created_dt or datetime.min.replace(tzinfo=UTC), reverse=True)
        return holds

    def _active_holds_for_subject(self, subject) -> list[Any]:
        return [
            hold
            for hold in self._holds_for_subject(subject)
            if str(self._props(hold).get("status") or "") == HoldStatus.ACTIVE.value
        ]

    def _dead_letters_for_subject(self, subject) -> list[Any]:
        dead_letters: list[Any] = []
        for lineage in get_parent_lineages(subject):
            if lineage.is_deleted or lineage.relationship_type != self.REL_SUBJECT_DEAD_LETTER:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="dead_letter"):
                dead_letters.append(child)
        dead_letters.sort(key=lambda row: row.created_dt or datetime.min.replace(tzinfo=UTC), reverse=True)
        return dead_letters

    def _latest_dead_letter_for_subject(self, subject):
        dead_letters = self._dead_letters_for_subject(subject)
        return dead_letters[0] if dead_letters else None

    def _all_execution_queues(self) -> list[Any]:
        return self._all_execution_instances(subtype="queue")

    def _all_workers(self) -> list[Any]:
        return [
            worker
            for worker in self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "actor",
                self.bdb.Base.classes.generic_instance.type == "system",
                self.bdb.Base.classes.generic_instance.subtype == "worker",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
            )
            .all()
        ]

    def _all_execution_instances(self, *, subtype: str) -> list[Any]:
        return list(
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "data",
                self.bdb.Base.classes.generic_instance.type == "execution",
                self.bdb.Base.classes.generic_instance.subtype == subtype,
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
            )
            .all()
        )

    def _visible_queue_items(self, queue, now: datetime) -> list[Any]:
        props = self._props(queue)
        if not bool(props.get("enabled", True)):
            return []
        subject_template_codes = set(str(code) for code in list(props.get("subject_template_codes") or []))
        eligible_states = set(str(code) for code in list(props.get("eligible_states") or []))
        items = []
        for instance in self._candidate_subjects():
            template_code = self._template_code(instance)
            if template_code not in subject_template_codes:
                continue
            execution = self._ensure_execution_envelope(instance, write=False)
            if str(execution.get("next_queue_key") or "") != str(props.get("queue_key") or ""):
                continue
            if str(execution.get("state") or "") not in eligible_states:
                continue
            if bool(execution.get("terminal")) or bool(execution.get("cancel_requested")):
                continue
            if str(execution.get("hold_state") or "") == "ACTIVE":
                continue
            if self._active_holds_for_subject(instance):
                continue
            if self._active_lease_for_subject(instance, now) is not None:
                continue
            ready_ts = self._queue_ready_at(instance, execution)
            if ready_ts is not None and ready_ts > now:
                continue
            if not self._scopes_match(instance, queue):
                continue
            items.append(instance)
        items.sort(key=lambda instance: self._queue_sort_key(instance))
        return items

    def _candidate_subjects(self) -> list[Any]:
        return [
            instance
            for instance in self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(self.bdb.Base.classes.generic_instance.is_deleted.is_(False))
            .all()
            if str(instance.category or "") not in {"action"}
        ]

    def _next_visible_subject_euid(self, queue, now: datetime) -> str | None:
        items = self._visible_queue_items(queue, now)
        return items[0].euid if items else None

    def _queue_sort_key(self, instance) -> tuple[Any, ...]:
        execution = self._ensure_execution_envelope(instance, write=False)
        priority = -int(execution.get("priority") or 0)
        due_at = self._parse_datetime(execution.get("due_at"))
        due_at_key = (0, due_at) if due_at is not None else (1, datetime.max.replace(tzinfo=UTC))
        ready_ts = self._queue_ready_at(instance, execution) or datetime.max.replace(tzinfo=UTC)
        created_dt = instance.created_dt or datetime.max.replace(tzinfo=UTC)
        return (priority, due_at_key, ready_ts, created_dt, str(instance.euid))

    def _queue_ready_at(self, instance, execution: dict[str, Any]) -> datetime | None:
        return (
            self._parse_datetime(execution.get("retry_at"))
            or self._parse_datetime(execution.get("ready_at"))
            or getattr(instance, "created_dt", None)
        )

    def _queue_summary(self, queue, *, now: datetime) -> ExecutionQueueSummary:
        props = self._props(queue)
        visible_items = self._visible_queue_items(queue, now)
        oldest_age = None
        newest_age = None
        if visible_items:
            ages = [
                (now - (self._queue_ready_at(item, self._ensure_execution_envelope(item, write=False)) or now)).total_seconds()
                for item in visible_items
            ]
            oldest_age = max(ages)
            newest_age = min(ages)
        queue_key = str(props.get("queue_key") or "")
        return ExecutionQueueSummary(
            queue_euid=queue.euid,
            queue_key=queue_key,
            display_name=str(props.get("display_name") or queue.name or queue_key),
            enabled=bool(props.get("enabled", True)),
            manual_only=bool(props.get("manual_only", False)),
            operator_visible=bool(props.get("operator_visible", True)),
            dispatch_priority=int(props.get("dispatch_priority") or 100),
            queue_depth=len(visible_items),
            oldest_job_age_seconds=oldest_age,
            newest_job_age_seconds=newest_age,
            active_leases=len(self._active_leases_for_queue(queue, now)),
            held_count=len(self._holds_for_queue(queue)),
            dead_letter_count=len(self._dead_letters_for_queue(queue)),
            failure_rate=self._queue_failure_rate(queue),
        )

    def _queue_failure_rate(self, queue) -> float:
        queue_key = str(self._props(queue).get("queue_key") or "")
        records = [
            record
            for record in self._all_execution_instances(subtype="execution_record")
            if str(self._props(record).get("queue_lookup_key") or "") == queue_key
        ]
        if not records:
            return 0.0
        failures = 0
        successes = 0
        for record in records:
            status = str(self._props(record).get("status") or "")
            if status == RecordStatus.SUCCEEDED.value:
                successes += 1
            elif status in {RecordStatus.FAILED_RETRYABLE.value, RecordStatus.FAILED_TERMINAL.value}:
                failures += 1
        total = successes + failures
        if total == 0:
            return 0.0
        return failures / total

    def _holds_for_queue(self, queue) -> list[Any]:
        holds: list[Any] = []
        for lineage in get_parent_lineages(queue):
            if lineage.is_deleted or lineage.relationship_type != self.REL_QUEUE_HOLD:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="hold"):
                holds.append(child)
        return holds

    def _dead_letters_for_queue(self, queue) -> list[Any]:
        dead_letters: list[Any] = []
        for lineage in get_parent_lineages(queue):
            if lineage.is_deleted or lineage.relationship_type != self.REL_QUEUE_DEAD_LETTER:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="dead_letter"):
                dead_letters.append(child)
        return dead_letters

    def _active_leases_for_queue(self, queue, now: datetime) -> list[Any]:
        leases: list[Any] = []
        for lineage in get_parent_lineages(queue):
            if lineage.is_deleted or lineage.relationship_type != self.REL_QUEUE_LEASE:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="queue_lease") and self._lease_active(child, now):
                leases.append(child)
        return leases

    def _active_lease_for_subject(self, subject, now: datetime):
        for lease in self._leases_for_subject(subject):
            if self._lease_active(lease, now):
                return lease
        return None

    def _active_record_for_lease(self, lease):
        for lineage in get_parent_lineages(lease):
            if lineage.is_deleted or lineage.relationship_type != self.REL_LEASE_RECORD:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if not self._is_execution_instance(child, subtype="execution_record"):
                continue
            status = str(self._props(child).get("status") or "")
            if status == RecordStatus.STARTED.value:
                return child
        return None

    def _lease_active(self, lease, now: datetime) -> bool:
        props = self._props(lease)
        return str(props.get("status") or "") == LeaseStatus.ACTIVE.value and not self._lease_expired(lease, now)

    def _lease_expired(self, lease, now: datetime) -> bool:
        expires_at = self._parse_datetime(self._props(lease).get("expires_at"))
        return expires_at is not None and expires_at <= now

    def _subject_diagnostics(self, subject, *, queue_key: str | None) -> SubjectExecutionDiagnostics:
        execution = self._ensure_execution_envelope(subject, write=False)
        reasons: list[str] = []
        queue = self._find_queue_by_key(queue_key) if queue_key else None
        now = self.clock()
        if not queue_key:
            reasons.append("next_queue_key_missing")
        if str(execution.get("terminal") or False).lower() == "true" or bool(execution.get("terminal")):
            reasons.append("terminal_state")
        if bool(execution.get("cancel_requested")):
            reasons.append("cancel_requested")
        if str(execution.get("hold_state") or "") == "ACTIVE" or self._active_holds_for_subject(subject):
            reasons.append("active_hold")
        if self._active_lease_for_subject(subject, now) is not None:
            reasons.append("active_lease")
        retry_at = self._parse_datetime(execution.get("retry_at"))
        if retry_at is not None and retry_at > now:
            reasons.append("retry_window_not_reached")
        if queue is not None:
            queue_props = self._props(queue)
            if not bool(queue_props.get("enabled", True)):
                reasons.append("queue_disabled")
            if str(execution.get("state") or "") not in set(queue_props.get("eligible_states") or []):
                reasons.append("state_not_eligible")
            if not self._scopes_match(subject, queue):
                reasons.append("capability_mismatch")
        visible = not reasons and (queue is not None) and bool(self._visible_queue_items(queue, now))
        return SubjectExecutionDiagnostics(
            visible_in_queue=self._is_visible_in_queue(subject, queue, now) if queue is not None else False,
            current_queue_key=self.current_queue_for_instance(subject),
            reasons=reasons,
        )

    def _is_visible_in_queue(self, subject, queue, now: datetime) -> bool:
        return any(item.uid == subject.uid for item in self._visible_queue_items(queue, now))

    def _scopes_match(self, instance, queue) -> bool:
        props = self._props(instance)
        queue_props = self._props(queue)
        checks = [
            ("site_scope", [props.get("site"), props.get("site_euid")]),
            ("platform_scope", [props.get("platform")]),
            ("assay_scope", [props.get("assay"), props.get("assay_key")]),
        ]
        for queue_field, candidates in checks:
            queue_scope = [str(item).strip() for item in list(queue_props.get(queue_field) or []) if str(item).strip()]
            if not queue_scope:
                continue
            subject_values = {str(item).strip() for item in candidates if str(item or "").strip()}
            if not subject_values.intersection(queue_scope):
                return False
        return True

    def _assert_worker_can_claim(self, worker, queue) -> None:
        worker_props = self._props(worker)
        queue_props = self._props(queue)
        worker_status = str(worker_props.get("status") or WorkerStatus.OFFLINE.value)
        if worker_status in {WorkerStatus.DISABLED.value, WorkerStatus.RETIRED.value}:
            raise ExecutionQueuePermissionError(f"Worker cannot claim in status {worker_status}")
        if bool(worker_props.get("drain_requested")) or worker_status == WorkerStatus.DRAINING.value:
            raise ExecutionQueuePermissionError(f"Worker is draining: {worker.euid}")
        if not bool(queue_props.get("enabled", True)):
            raise ExecutionQueuePermissionError(f"Queue is disabled: {queue.euid}")
        if bool(queue_props.get("manual_only")) and str(worker_props.get("worker_type") or "") != WorkerType.HUMAN_SESSION.value:
            raise ExecutionQueuePermissionError(f"Queue is manual-only: {queue.euid}")
        required = {str(item) for item in list(queue_props.get("required_worker_capabilities") or []) if str(item).strip()}
        capabilities = {str(item) for item in list(worker_props.get("capabilities") or []) if str(item).strip()}
        if not required.issubset(capabilities):
            raise ExecutionQueuePermissionError(f"Worker capability mismatch for queue {queue.euid}")
        active_lease_count = len(self._active_leases_for_worker(worker, self.clock()))
        max_concurrent = int(worker_props.get("max_concurrent_leases") or 1)
        if active_lease_count >= max_concurrent:
            raise ExecutionQueuePermissionError(f"Worker already at max active leases: {worker.euid}")

    def _active_leases_for_worker(self, worker, now: datetime) -> list[Any]:
        leases: list[Any] = []
        for lineage in get_parent_lineages(worker):
            if lineage.is_deleted or lineage.relationship_type != self.REL_WORKER_LEASE:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if self._is_execution_instance(child, subtype="queue_lease") and self._lease_active(child, now):
                leases.append(child)
        return leases

    def _assert_subject_visible_in_queue(self, subject, queue, *, now: datetime) -> None:
        if not self._is_visible_in_queue(subject, queue, now):
            raise ExecutionQueueConflictError(
                f"Subject is not currently visible in queue {self._props(queue).get('queue_key')}: {subject.euid}"
            )

    def _assert_expected_state(
        self,
        subject,
        execution: dict[str, Any],
        expected_state: ExecutionState,
        expected_revision: int | None,
    ) -> None:
        if str(execution.get("state") or "") != expected_state.value:
            raise ExecutionQueueConflictError(
                f"Expected state {expected_state.value} but found {execution.get('state')} for {subject.euid}"
            )
        if expected_revision is not None and int(execution.get("revision") or 0) != expected_revision:
            raise ExecutionQueueConflictError(
                f"Expected revision {expected_revision} but found {execution.get('revision')} for {subject.euid}"
            )

    def _assert_lease_active_for_subject(self, subject, lease, *, now: datetime) -> None:
        if str(self._props(lease).get("status") or "") != LeaseStatus.ACTIVE.value:
            raise ExecutionQueueConflictError(f"Lease is not active: {lease.euid}")
        if self._lease_expired(lease, now):
            raise ExecutionQueueConflictError(f"LEASE_EXPIRED: {lease.euid}")
        if self._subject_for_lease(lease) is None or self._subject_for_lease(lease).uid != subject.uid:
            raise ExecutionQueueConflictError(
                f"Lease {lease.euid} does not belong to subject {subject.euid}"
            )

    def _assert_worker_owns_lease(self, worker, lease) -> None:
        worker_owner = self._worker_for_lease(lease)
        if worker_owner is None or worker_owner.uid != worker.uid:
            raise ExecutionQueuePermissionError(
                f"Worker {worker.euid} does not own lease {lease.euid}"
            )

    def _transition_lease_to_terminal(self, lease, *, status: LeaseStatus, reason: str) -> None:
        props = self._props(lease)
        if str(props.get("status") or "") in {
            LeaseStatus.RELEASED.value,
            LeaseStatus.COMPLETED.value,
            LeaseStatus.EXPIRED.value,
            LeaseStatus.ABANDONED.value,
            LeaseStatus.CANCELED.value,
        }:
            return
        props["status"] = status.value
        props["released_at"] = self._timestamp()
        props["release_reason"] = reason
        self._write_props(lease, props)

    def _finalize_record(
        self,
        record,
        *,
        status: RecordStatus,
        end_state: str,
        end_revision: int,
        result_snapshot: dict[str, Any],
        retryable: bool,
        error_class: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        props = self._props(record)
        finished_at = self.clock()
        started_at = self._parse_datetime(props.get("started_at")) or finished_at
        props["status"] = status.value
        props["end_state"] = end_state
        props["end_revision"] = end_revision
        props["finished_at"] = self._timestamp(finished_at)
        props["duration_ms"] = int((finished_at - started_at).total_seconds() * 1000)
        props["retryable"] = retryable
        props["error_class"] = error_class
        props["error_code"] = error_code
        props["error_message"] = error_message
        props["result_snapshot"] = result_snapshot or {}
        self._write_props(record, props)

    def _worker_summary(self, worker, *, now: datetime) -> WorkerSummary:
        props = self._props(worker)
        heartbeat_at = self._parse_datetime(props.get("heartbeat_at"))
        lag = (now - heartbeat_at).total_seconds() if heartbeat_at is not None else None
        status_value = str(props.get("status") or WorkerStatus.OFFLINE.value)
        if heartbeat_at is not None and lag is not None and lag > int(props.get("heartbeat_ttl_seconds") or 60):
            status_value = WorkerStatus.OFFLINE.value
        return WorkerSummary(
            worker_euid=worker.euid,
            worker_key=str(props.get("worker_key") or ""),
            display_name=str(props.get("display_name") or worker.name or worker.euid),
            worker_type=WorkerType(str(props.get("worker_type") or WorkerType.SERVICE.value)),
            status=WorkerStatus(status_value),
            capabilities=list(props.get("capabilities") or []),
            active_lease_count=len(self._active_leases_for_worker(worker, now)),
            max_concurrent_leases=int(props.get("max_concurrent_leases") or 1),
            heartbeat_at=self._timestamp(heartbeat_at) if heartbeat_at is not None else None,
            heartbeat_lag_seconds=lag,
            drain_requested=bool(props.get("drain_requested")),
        )

    def _worker_detail(self, worker) -> WorkerDetail:
        summary = self._worker_summary(worker, now=self.clock())
        props = self._props(worker)
        return WorkerDetail(
            **summary.model_dump(),
            site_scope=list(props.get("site_scope") or []),
            platform_scope=list(props.get("platform_scope") or []),
            assay_scope=list(props.get("assay_scope") or []),
            heartbeat_ttl_seconds=int(props.get("heartbeat_ttl_seconds") or 60),
            build_version=str(props.get("build_version") or "") or None,
            host=str(props.get("host") or "") or None,
            process_identity=str(props.get("process_identity") or "") or None,
            disabled_reason=str(props.get("disabled_reason") or "") or None,
            last_error_at=str(props.get("last_error_at") or "") or None,
            last_error_class=str(props.get("last_error_class") or "") or None,
            revision=int(props.get("revision") or 1),
        )

    def _queue_item(self, instance) -> ExecutionQueueItem:
        execution = self._ensure_execution_envelope(instance, write=False)
        return ExecutionQueueItem(
            subject_euid=instance.euid,
            subject_name=instance.name,
            subject_category=str(instance.category or ""),
            template_code=self._template_code(instance),
            state=ExecutionState(str(execution.get("state") or ExecutionState.PENDING.value)),
            next_queue_key=str(execution.get("next_queue_key") or "") or None,
            next_action_key=str(execution.get("next_action_key") or "") or None,
            priority=int(execution.get("priority") or 0),
            ready_at=str(execution.get("ready_at") or "") or None,
            due_at=str(execution.get("due_at") or "") or None,
            retry_at=str(execution.get("retry_at") or "") or None,
            attempt_count=int(execution.get("attempt_count") or 0),
            created_at=getattr(instance, "created_dt", None),
            queue_ready_timestamp=self._timestamp(self._queue_ready_at(instance, execution))
            if self._queue_ready_at(instance, execution) is not None
            else None,
        )

    def _lease_summary(self, lease) -> LeaseSummary:
        props = self._props(lease)
        return LeaseSummary(
            lease_euid=lease.euid,
            lease_token=str(props.get("lease_token") or ""),
            queue_lookup_key=str(props.get("queue_lookup_key") or ""),
            subject_lookup_euid=str(props.get("subject_lookup_euid") or ""),
            worker_lookup_euid=str(props.get("worker_lookup_euid") or ""),
            status=LeaseStatus(str(props.get("status") or LeaseStatus.ACTIVE.value)),
            claimed_at=str(props.get("claimed_at") or "") or None,
            heartbeat_at=str(props.get("heartbeat_at") or "") or None,
            expires_at=str(props.get("expires_at") or "") or None,
            released_at=str(props.get("released_at") or "") or None,
            release_reason=str(props.get("release_reason") or "") or None,
            attempt_number=int(props.get("attempt_number") or 0),
            next_action_key=str(props.get("next_action_key") or "") or None,
            idempotency_key=str(props.get("idempotency_key") or "") or None,
        )

    def _record_summary(self, record) -> ExecutionRecordSummary:
        props = self._props(record)
        return ExecutionRecordSummary(
            record_euid=record.euid,
            subject_lookup_euid=str(props.get("subject_lookup_euid") or ""),
            queue_lookup_key=str(props.get("queue_lookup_key") or ""),
            worker_lookup_euid=str(props.get("worker_lookup_euid") or ""),
            lease_lookup_euid=str(props.get("lease_lookup_euid") or ""),
            attempt_number=int(props.get("attempt_number") or 0),
            status=RecordStatus(str(props.get("status") or RecordStatus.STARTED.value)),
            action_key=str(props.get("action_key") or ""),
            idempotency_key=str(props.get("idempotency_key") or "") or None,
            expected_state=str(props.get("expected_state") or "") or None,
            start_state=str(props.get("start_state") or "") or None,
            end_state=str(props.get("end_state") or "") or None,
            started_at=str(props.get("started_at") or "") or None,
            finished_at=str(props.get("finished_at") or "") or None,
            duration_ms=int(props.get("duration_ms")) if props.get("duration_ms") is not None else None,
            retryable=bool(props.get("retryable")),
            error_class=str(props.get("error_class") or "") or None,
            error_code=str(props.get("error_code") or "") or None,
            error_message=str(props.get("error_message") or "") or None,
            input_snapshot=dict(props.get("input_snapshot") or {}),
            result_snapshot=dict(props.get("result_snapshot") or {}),
        )

    def _hold_summary(self, hold) -> HoldSummary:
        props = self._props(hold)
        return HoldSummary(
            hold_euid=hold.euid,
            subject_lookup_euid=str(props.get("subject_lookup_euid") or ""),
            queue_lookup_key=str(props.get("queue_lookup_key") or "") or None,
            placed_by_lookup_euid=str(props.get("placed_by_lookup_euid") or ""),
            status=HoldStatus(str(props.get("status") or HoldStatus.ACTIVE.value)),
            hold_code=str(props.get("hold_code") or ""),
            reason=str(props.get("reason") or ""),
            placed_at=str(props.get("placed_at") or "") or None,
            released_at=str(props.get("released_at") or "") or None,
            released_by_lookup_euid=str(props.get("released_by_lookup_euid") or "") or None,
        )

    def _dead_letter_summary(self, dead_letter) -> DeadLetterSummary:
        props = self._props(dead_letter)
        return DeadLetterSummary(
            dead_letter_euid=dead_letter.euid,
            subject_lookup_euid=str(props.get("subject_lookup_euid") or ""),
            queue_lookup_key=str(props.get("queue_lookup_key") or ""),
            last_execution_record_lookup_euid=str(props.get("last_execution_record_lookup_euid") or "") or None,
            last_lease_lookup_euid=str(props.get("last_lease_lookup_euid") or "") or None,
            dead_lettered_at=str(props.get("dead_lettered_at") or "") or None,
            failure_count=int(props.get("failure_count") or 0),
            error_class=str(props.get("error_class") or "") or None,
            error_message=str(props.get("error_message") or "") or None,
            resolution_state=DeadLetterResolutionState(
                str(props.get("resolution_state") or DeadLetterResolutionState.OPEN.value)
            ),
            resolved_by_lookup_euid=str(props.get("resolved_by_lookup_euid") or "") or None,
            resolved_at=str(props.get("resolved_at") or "") or None,
        )

    def _require_queue(self, queue_key: str):
        queue = self._find_queue_by_key(queue_key)
        if queue is None:
            raise ExecutionQueueNotFoundError(f"Queue not found: {queue_key}")
        return queue

    def _find_queue_by_key(self, queue_key: str):
        return self._find_instance_by_property(
            category="data",
            type_name="execution",
            subtype="queue",
            property_key="queue_key",
            expected=queue_key,
        )

    def _find_worker_by_key(self, worker_key: str):
        return self._find_instance_by_property(
            category="actor",
            type_name="system",
            subtype="worker",
            property_key="worker_key",
            expected=worker_key,
        )

    def _authoritative_queue_key_for_instance(self, instance) -> str | None:
        execution = self._ensure_execution_envelope(instance, write=False)
        queue_key = str(execution.get("next_queue_key") or "").strip()
        if queue_key and not execution.get("terminal") and not execution.get("cancel_requested"):
            return queue_key

        props = self._props(instance)
        current_queue = str(props.get("current_queue") or "").strip()
        if current_queue:
            return current_queue

        for lineage in get_child_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != self.LEGACY_REL_QUEUE_MEMBERSHIP:
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted:
                continue
            parent_props = self._props(parent)
            queue_name = str(parent_props.get("queue_name") or "").strip()
            if queue_name:
                return queue_name

        return None

    def _find_instance_by_property(
        self,
        *,
        category: str,
        type_name: str,
        subtype: str,
        property_key: str,
        expected: str,
    ):
        GI = self.bdb.Base.classes.generic_instance
        return (
            self.bdb.session.query(GI)
            .filter(
                GI.category == category,
                GI.type == type_name,
                GI.subtype == subtype,
                GI.is_deleted.is_(False),
                func.jsonb_extract_path_text(GI.json_addl["properties"], property_key)
                == str(expected).strip(),
            )
            .first()
        )

    def _create_execution_instance(self, template_code: str, *, name: str, properties: dict[str, Any]):
        instance = self.bobj.create_instance_by_code(
            template_code,
            {"json_addl": {"properties": properties}},
        )
        instance.name = name
        props = self._props(instance)
        props["name"] = name
        self._write_props(instance, props)
        return instance

    def _link(self, parent, child, relationship_type: str) -> None:
        self.bobj.create_generic_instance_lineage_by_euids(
            parent.euid,
            child.euid,
            relationship_type=relationship_type,
        )

    def _subject_for_lease(self, lease):
        for lineage in get_child_lineages(lease):
            if lineage.is_deleted or lineage.relationship_type != self.REL_SUBJECT_LEASE:
                continue
            return lineage.parent_instance
        return None

    def _worker_for_lease(self, lease):
        for lineage in get_child_lineages(lease):
            if lineage.is_deleted or lineage.relationship_type != self.REL_WORKER_LEASE:
                continue
            return lineage.parent_instance
        return None

    def _subject_for_hold(self, hold):
        for lineage in get_child_lineages(hold):
            if lineage.is_deleted or lineage.relationship_type != self.REL_SUBJECT_HOLD:
                continue
            return lineage.parent_instance
        return None

    def _lock_subject(self, subject_euid: str | None):
        if not subject_euid:
            return None
        GI = self.bdb.Base.classes.generic_instance
        subject = (
            self.bdb.session.query(GI)
            .filter(GI.euid == subject_euid, GI.is_deleted.is_(False))
            .with_for_update()
            .one_or_none()
        )
        if subject is None:
            raise ExecutionQueueNotFoundError(f"Subject not found: {subject_euid}")
        return subject

    def _lock_worker(self, worker_euid: str):
        GI = self.bdb.Base.classes.generic_instance
        worker = (
            self.bdb.session.query(GI)
            .filter(
                GI.euid == worker_euid,
                GI.category == "actor",
                GI.type == "system",
                GI.subtype == "worker",
                GI.is_deleted.is_(False),
            )
            .with_for_update()
            .one_or_none()
        )
        if worker is None:
            raise ExecutionQueueNotFoundError(f"Worker not found: {worker_euid}")
        return worker

    def _require_worker(self, worker_euid: str):
        worker = self._lock_worker(worker_euid)
        return worker

    def _require_lease(self, lease_euid: str):
        lease = self._require_instance(lease_euid)
        if not self._is_execution_instance(lease, subtype="queue_lease"):
            raise ExecutionQueueNotFoundError(f"Lease not found: {lease_euid}")
        return lease

    def _require_hold(self, hold_euid: str):
        hold = self._require_instance(hold_euid)
        if not self._is_execution_instance(hold, subtype="hold"):
            raise ExecutionQueueNotFoundError(f"Hold not found: {hold_euid}")
        return hold

    def _require_instance(self, euid: str):
        instance = self.bobj.get_by_euid(euid)
        if instance is None or instance.is_deleted:
            raise ExecutionQueueNotFoundError(f"Object not found: {euid}")
        return instance

    def _is_execution_instance(self, instance, *, subtype: str) -> bool:
        return bool(
            instance is not None
            and not instance.is_deleted
            and str(instance.category or "") == "data"
            and str(instance.type or "") == "execution"
            and str(instance.subtype or "") == subtype
        )

    def _template_code(self, instance) -> str:
        category = str(getattr(instance, "category", "") or "")
        type_name = str(getattr(instance, "type", "") or "")
        subtype = str(getattr(instance, "subtype", "") or "")
        version = str(getattr(instance, "version", "") or "")
        return f"{category}/{type_name}/{subtype}/{version}"

    def _props(self, instance) -> dict[str, Any]:
        payload = instance.json_addl if isinstance(instance.json_addl, dict) else {}
        props = payload.get("properties")
        return dict(props) if isinstance(props, dict) else {}

    def _write_props(self, instance, props: dict[str, Any]) -> None:
        payload = deepcopy(instance.json_addl) if isinstance(instance.json_addl, dict) else {}
        payload["properties"] = props
        instance.json_addl = payload
        flag_modified(instance, "json_addl")
        self.bdb.session.flush()

    def _default_execution_envelope(self) -> dict[str, Any]:
        return ExecutionEnvelope().model_dump()

    def _ensure_execution_envelope(self, instance, *, write: bool) -> dict[str, Any]:
        props = self._props(instance)
        current = props.get("execution") if isinstance(props.get("execution"), dict) else {}
        queue_cache = current.get("queue_cache") if isinstance(current.get("queue_cache"), dict) else {}
        envelope = self._default_execution_envelope()
        envelope.update({k: v for k, v in current.items() if k != "queue_cache"})
        envelope["queue_cache"] = {
            **dict(envelope.get("queue_cache") or {}),
            **dict(queue_cache or {}),
        }
        if write or not current:
            self._set_execution_envelope(instance, envelope)
        return envelope

    def _set_execution_envelope(self, instance, envelope: dict[str, Any]) -> None:
        normalized = deepcopy(self._default_execution_envelope())
        normalized.update({k: v for k, v in envelope.items() if k != "queue_cache"})
        normalized["queue_cache"] = {
            **dict(self._default_execution_envelope()["queue_cache"]),
            **dict(envelope.get("queue_cache") or {}),
        }
        props = self._props(instance)
        props["execution"] = normalized
        queue_key = str(normalized.get("next_queue_key") or "").strip()
        if queue_key and not bool(normalized.get("terminal")) and not bool(normalized.get("cancel_requested")):
            props["current_queue"] = queue_key
        else:
            props.pop("current_queue", None)
        self._write_props(instance, props)

    def _payload_hash(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _maybe_replay_action(
        self,
        *,
        action_key: str,
        subject_euid: str | None,
        idempotency_key: str,
        payload_hash: str,
    ) -> ExecutionActionResponse | None:
        existing = self.action_recorder.find_replay(
            action_key=action_key,
            subject_euid=subject_euid,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            return None
        payload = existing.json_addl if isinstance(existing.json_addl, dict) else {}
        existing_hash = str(payload.get("payload_hash") or "").strip()
        if existing_hash and existing_hash != payload_hash:
            raise ExecutionQueueConflictError(
                f"Idempotency conflict for action {action_key} subject {subject_euid}"
            )
        result = payload.get("result")
        return ExecutionActionResponse(
            status="success",
            action_key=action_key,
            subject_euid=str(payload.get("subject_lookup_euid") or "") or None,
            worker_euid=str(payload.get("worker_lookup_euid") or "") or None,
            lease_euid=str(payload.get("lease_lookup_euid") or "") or None,
            replayed=True,
            result=dict(result or {}) if isinstance(result, dict) else {},
        )

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    def _timestamp(self, value: datetime | None = None) -> str:
        dt = value or self.clock()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()

    def _random_token(self) -> str:
        return secrets.token_hex(16)

    def _compute_retry_at(self, *, queue_props: dict[str, Any], attempt_count: int) -> datetime:
        retry_policy = dict(queue_props.get("retry_policy") or {})
        initial_delay_seconds = int(retry_policy.get("initial_delay_seconds") or 60)
        backoff_factor = float(retry_policy.get("backoff_factor") or 2.0)
        max_delay_seconds = int(retry_policy.get("max_delay_seconds") or 3600)
        delay = initial_delay_seconds * (backoff_factor ** max(attempt_count - 1, 0))
        delay = min(int(delay), max_delay_seconds)
        return self.clock() + timedelta(seconds=delay)
