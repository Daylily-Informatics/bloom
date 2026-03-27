"""Schemas for the TapDB-native execution queue subsystem."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    HELD = "HELD"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"


class LeaseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    ABANDONED = "ABANDONED"
    CANCELED = "CANCELED"


class WorkerType(StrEnum):
    SERVICE = "SERVICE"
    HUMAN_SESSION = "HUMAN_SESSION"
    INSTRUMENT_ADAPTER = "INSTRUMENT_ADAPTER"


class WorkerStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DRAINING = "DRAINING"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class RecordStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class HoldStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class DeadLetterResolutionState(StrEnum):
    OPEN = "OPEN"
    REQUEUED = "REQUEUED"
    CANCELED = "CANCELED"
    IGNORED = "IGNORED"


class QueueRetryPolicy(BaseModel):
    mode: str = "EXPONENTIAL_BACKOFF"
    initial_delay_seconds: int = 60
    backoff_factor: float = 2.0
    max_delay_seconds: int = 3600


class QueueSelectionPolicy(BaseModel):
    order: list[str] = Field(
        default_factory=lambda: [
            "priority_desc",
            "due_at_asc",
            "ready_at_asc",
            "created_dt_asc",
            "euid_asc",
        ]
    )


class QueueCache(BaseModel):
    current_queue_key: str | None = None
    computed_at: str | None = None


class ExecutionEnvelope(BaseModel):
    state: ExecutionState = ExecutionState.PENDING
    revision: int = 1
    next_queue_key: str | None = None
    next_action_key: str | None = None
    priority: int = 0
    ready_at: str | None = None
    due_at: str | None = None
    attempt_count: int = 0
    max_attempts_override: int | None = None
    retry_at: str | None = None
    hold_state: str = "NONE"
    hold_reason: str | None = None
    cancel_requested: bool = False
    terminal: bool = False
    last_execution_record_euid: str | None = None
    queue_cache: QueueCache = Field(default_factory=QueueCache)


class ExecutionQueueSummary(BaseModel):
    queue_euid: str
    queue_key: str
    display_name: str
    enabled: bool
    manual_only: bool
    operator_visible: bool
    dispatch_priority: int
    queue_depth: int
    oldest_job_age_seconds: float | None = None
    newest_job_age_seconds: float | None = None
    active_leases: int
    held_count: int
    dead_letter_count: int
    failure_rate: float = 0.0


class ExecutionQueueDetail(ExecutionQueueSummary):
    subject_template_codes: list[str] = Field(default_factory=list)
    eligible_states: list[ExecutionState] = Field(default_factory=list)
    required_worker_capabilities: list[str] = Field(default_factory=list)
    site_scope: list[str] = Field(default_factory=list)
    platform_scope: list[str] = Field(default_factory=list)
    assay_scope: list[str] = Field(default_factory=list)
    lease_ttl_seconds: int
    max_attempts_default: int
    retry_policy: QueueRetryPolicy
    selection_policy: QueueSelectionPolicy
    diagnostics_enabled: bool
    revision: int
    disabled_reason: str | None = None


class ExecutionQueueItem(BaseModel):
    subject_euid: str
    subject_name: str | None = None
    subject_category: str
    template_code: str
    state: ExecutionState
    next_queue_key: str | None = None
    next_action_key: str | None = None
    priority: int = 0
    ready_at: str | None = None
    due_at: str | None = None
    retry_at: str | None = None
    attempt_count: int = 0
    created_at: datetime | None = None
    queue_ready_timestamp: str | None = None


class WorkerSummary(BaseModel):
    worker_euid: str
    worker_key: str
    display_name: str
    worker_type: WorkerType
    status: WorkerStatus
    capabilities: list[str] = Field(default_factory=list)
    active_lease_count: int = 0
    max_concurrent_leases: int = 1
    heartbeat_at: str | None = None
    heartbeat_lag_seconds: float | None = None
    drain_requested: bool = False


class WorkerDetail(WorkerSummary):
    site_scope: list[str] = Field(default_factory=list)
    platform_scope: list[str] = Field(default_factory=list)
    assay_scope: list[str] = Field(default_factory=list)
    heartbeat_ttl_seconds: int = 60
    build_version: str | None = None
    host: str | None = None
    process_identity: str | None = None
    disabled_reason: str | None = None
    last_error_at: str | None = None
    last_error_class: str | None = None
    revision: int = 1


class LeaseSummary(BaseModel):
    lease_euid: str
    lease_token: str
    queue_lookup_key: str
    subject_lookup_euid: str
    worker_lookup_euid: str
    status: LeaseStatus
    claimed_at: str | None = None
    heartbeat_at: str | None = None
    expires_at: str | None = None
    released_at: str | None = None
    release_reason: str | None = None
    attempt_number: int = 0
    next_action_key: str | None = None
    idempotency_key: str | None = None


class ExecutionRecordSummary(BaseModel):
    record_euid: str
    subject_lookup_euid: str
    queue_lookup_key: str
    worker_lookup_euid: str
    lease_lookup_euid: str
    attempt_number: int
    status: RecordStatus
    action_key: str
    idempotency_key: str | None = None
    expected_state: str | None = None
    start_state: str | None = None
    end_state: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    retryable: bool = False
    error_class: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    result_snapshot: dict[str, Any] = Field(default_factory=dict)


class HoldSummary(BaseModel):
    hold_euid: str
    subject_lookup_euid: str
    queue_lookup_key: str | None = None
    placed_by_lookup_euid: str
    status: HoldStatus
    hold_code: str
    reason: str
    placed_at: str | None = None
    released_at: str | None = None
    released_by_lookup_euid: str | None = None


class DeadLetterSummary(BaseModel):
    dead_letter_euid: str
    subject_lookup_euid: str
    queue_lookup_key: str
    last_execution_record_lookup_euid: str | None = None
    last_lease_lookup_euid: str | None = None
    dead_lettered_at: str | None = None
    failure_count: int = 0
    error_class: str | None = None
    error_message: str | None = None
    resolution_state: DeadLetterResolutionState = DeadLetterResolutionState.OPEN
    resolved_by_lookup_euid: str | None = None
    resolved_at: str | None = None


class SubjectExecutionDiagnostics(BaseModel):
    visible_in_queue: bool = False
    current_queue_key: str | None = None
    reasons: list[str] = Field(default_factory=list)


class SubjectExecutionDetail(BaseModel):
    subject_euid: str
    subject_name: str | None = None
    subject_category: str
    template_code: str
    execution: ExecutionEnvelope
    diagnostics: SubjectExecutionDiagnostics
    active_lease: LeaseSummary | None = None
    active_holds: list[HoldSummary] = Field(default_factory=list)
    dead_letter: DeadLetterSummary | None = None


class SubjectExecutionHistory(BaseModel):
    subject_euid: str
    records: list[ExecutionRecordSummary] = Field(default_factory=list)
    leases: list[LeaseSummary] = Field(default_factory=list)
    holds: list[HoldSummary] = Field(default_factory=list)
    dead_letters: list[DeadLetterSummary] = Field(default_factory=list)


class RegisterWorkerRequest(BaseModel):
    worker_key: str
    display_name: str
    worker_type: WorkerType = WorkerType.SERVICE
    capabilities: list[str] = Field(default_factory=list)
    site_scope: list[str] = Field(default_factory=list)
    platform_scope: list[str] = Field(default_factory=list)
    assay_scope: list[str] = Field(default_factory=list)
    max_concurrent_leases: int = 1
    heartbeat_ttl_seconds: int = 60
    build_version: str | None = None
    host: str | None = None
    process_identity: str | None = None
    status: WorkerStatus = WorkerStatus.ONLINE
    drain_requested: bool = False


class HeartbeatWorkerRequest(BaseModel):
    worker_euid: str
    status: WorkerStatus | None = None
    last_error_at: str | None = None
    last_error_class: str | None = None
    host: str | None = None
    process_identity: str | None = None


class ClaimQueueItemRequest(BaseModel):
    worker_euid: str
    queue_key: str
    subject_euid: str | None = None
    idempotency_key: str
    expected_state: ExecutionState = ExecutionState.READY
    payload: dict[str, Any] = Field(default_factory=dict)


class RenewQueueLeaseRequest(BaseModel):
    lease_euid: str
    worker_euid: str
    idempotency_key: str


class ReleaseQueueLeaseRequest(BaseModel):
    lease_euid: str
    worker_euid: str
    idempotency_key: str
    reason: str | None = None


class CompleteQueueExecutionRequest(BaseModel):
    subject_euid: str
    worker_euid: str
    lease_euid: str
    action_key: str
    expected_state: ExecutionState
    expected_revision: int | None = None
    idempotency_key: str
    next_queue_key: str | None = None
    next_action_key: str | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)
    terminal: bool = False


class FailQueueExecutionRequest(BaseModel):
    subject_euid: str
    worker_euid: str
    lease_euid: str
    action_key: str
    expected_state: ExecutionState
    expected_revision: int | None = None
    idempotency_key: str
    retryable: bool = True
    error_class: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)


class PlaceExecutionHoldRequest(BaseModel):
    subject_euid: str
    placed_by_worker_euid: str
    queue_key: str | None = None
    hold_code: str
    reason: str
    idempotency_key: str


class ReleaseExecutionHoldRequest(BaseModel):
    hold_euid: str
    released_by_worker_euid: str
    idempotency_key: str


class RequeueSubjectRequest(BaseModel):
    subject_euid: str
    queue_key: str
    next_action_key: str | None = None
    priority: int | None = None
    ready_at: str | None = None
    due_at: str | None = None
    expected_state: ExecutionState | None = None
    expected_revision: int | None = None
    idempotency_key: str


class CancelSubjectExecutionRequest(BaseModel):
    subject_euid: str
    expected_state: ExecutionState | None = None
    expected_revision: int | None = None
    idempotency_key: str
    reason: str | None = None


class ExpireQueueLeaseRequest(BaseModel):
    lease_euid: str
    idempotency_key: str
    reason: str | None = None


class ExecutionActionResponse(BaseModel):
    status: str
    action_key: str
    subject_euid: str | None = None
    worker_euid: str | None = None
    lease_euid: str | None = None
    hold_euid: str | None = None
    dead_letter_euid: str | None = None
    replayed: bool = False
    result: dict[str, Any] = Field(default_factory=dict)
