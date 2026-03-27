"""Execution queue API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from bloom_lims.api.v1.dependencies import APIUser, require_api_auth
from bloom_lims.auth.rbac import Permission
from bloom_lims.domain.execution_queue import (
    ExecutionQueueConflictError,
    ExecutionQueueError,
    ExecutionQueueNotFoundError,
    ExecutionQueuePermissionError,
    ExecutionQueueService,
)
from bloom_lims.schemas.execution_queue import (
    CancelSubjectExecutionRequest,
    ClaimQueueItemRequest,
    CompleteQueueExecutionRequest,
    DeadLetterSummary,
    ExecutionActionResponse,
    ExecutionQueueDetail,
    ExecutionQueueItem,
    ExecutionQueueSummary,
    ExpireQueueLeaseRequest,
    FailQueueExecutionRequest,
    HeartbeatWorkerRequest,
    LeaseSummary,
    PlaceExecutionHoldRequest,
    RegisterWorkerRequest,
    ReleaseExecutionHoldRequest,
    ReleaseQueueLeaseRequest,
    RenewQueueLeaseRequest,
    RequeueSubjectRequest,
    SubjectExecutionDetail,
    SubjectExecutionHistory,
    WorkerDetail,
    WorkerSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/execution", tags=["Execution Queue"])


def _require_read(user: APIUser = Depends(require_api_auth)) -> APIUser:
    if not user.has_permission(Permission.BLOOM_READ):
        raise HTTPException(status_code=403, detail="Read permission required")
    return user


def _require_write(user: APIUser = Depends(require_api_auth)) -> APIUser:
    if not user.has_permission(Permission.BLOOM_WRITE):
        raise HTTPException(status_code=403, detail="Write permission required")
    return user


def _require_admin(user: APIUser = Depends(require_api_auth)) -> APIUser:
    if not user.has_permission(Permission.BLOOM_ADMIN):
        raise HTTPException(status_code=403, detail="Admin permission required")
    return user


def _raise_execution_http_error(exc: Exception) -> None:
    if isinstance(exc, ExecutionQueueNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ExecutionQueuePermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ExecutionQueueConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ExecutionQueueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.exception("Unhandled execution queue error")
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/queues", response_model=list[ExecutionQueueSummary])
async def list_queues(user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.list_queues()
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/queues/{queue_key}", response_model=ExecutionQueueDetail)
async def get_queue(queue_key: str, user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.get_queue(queue_key)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/queues/{queue_key}/items", response_model=list[ExecutionQueueItem])
async def list_queue_items(queue_key: str, user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.list_queue_items(queue_key)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/subjects/{euid}", response_model=SubjectExecutionDetail)
async def get_subject_execution(euid: str, user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.get_subject_detail(euid)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/subjects/{euid}/history", response_model=SubjectExecutionHistory)
async def get_subject_execution_history(euid: str, user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.get_subject_history(euid)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/workers", response_model=list[WorkerSummary])
async def list_workers(user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.list_workers()
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/workers/{worker_euid}", response_model=WorkerDetail)
async def get_worker(worker_euid: str, user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.get_worker(worker_euid)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/leases", response_model=list[LeaseSummary])
async def list_leases(
    status: str | None = Query(None),
    user: APIUser = Depends(_require_read),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.list_leases(status=status)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.get("/dead-letter", response_model=list[DeadLetterSummary])
async def list_dead_letter(user: APIUser = Depends(_require_read)):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.list_dead_letters()
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/register-worker", response_model=WorkerDetail)
async def register_worker(
    payload: RegisterWorkerRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.register_worker(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/heartbeat-worker", response_model=WorkerDetail)
async def heartbeat_worker(
    payload: HeartbeatWorkerRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.heartbeat_worker(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/claim", response_model=ExecutionActionResponse)
async def claim_queue_item(
    payload: ClaimQueueItemRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.claim_queue_item(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/renew-lease", response_model=ExecutionActionResponse)
async def renew_queue_lease(
    payload: RenewQueueLeaseRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.renew_queue_lease(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/release-lease", response_model=ExecutionActionResponse)
async def release_queue_lease(
    payload: ReleaseQueueLeaseRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.release_queue_lease(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/complete", response_model=ExecutionActionResponse)
async def complete_queue_execution(
    payload: CompleteQueueExecutionRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.complete_queue_execution(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/fail", response_model=ExecutionActionResponse)
async def fail_queue_execution(
    payload: FailQueueExecutionRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.fail_queue_execution(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/hold", response_model=ExecutionActionResponse)
async def place_execution_hold(
    payload: PlaceExecutionHoldRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.place_execution_hold(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/release-hold", response_model=ExecutionActionResponse)
async def release_execution_hold(
    payload: ReleaseExecutionHoldRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.release_execution_hold(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/requeue", response_model=ExecutionActionResponse)
async def requeue_subject(
    payload: RequeueSubjectRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.requeue_subject(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/cancel", response_model=ExecutionActionResponse)
async def cancel_subject_execution(
    payload: CancelSubjectExecutionRequest,
    user: APIUser = Depends(_require_write),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.cancel_subject_execution(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()


@router.post("/actions/expire-lease", response_model=ExecutionActionResponse)
async def expire_queue_lease(
    payload: ExpireQueueLeaseRequest,
    user: APIUser = Depends(_require_admin),
):
    service = ExecutionQueueService(app_username=user.email)
    try:
        return service.expire_queue_lease(payload, executed_by=user.email)
    except Exception as exc:
        _raise_execution_http_error(exc)
    finally:
        service.close()
