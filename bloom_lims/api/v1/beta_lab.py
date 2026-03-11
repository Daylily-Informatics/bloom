"""Bloom beta lab APIs for Atlas and Ursa integration paths."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from bloom_lims.api.v1.dependencies import (
    APIUser,
    require_external_atlas_api_enabled,
    require_external_ursa_api_enabled,
)
from bloom_lims.auth.rbac import Permission
from bloom_lims.domain.beta_lab import BetaLabService
from bloom_lims.domain.execution_queue import (
    ExecutionQueueConflictError,
    ExecutionQueueError,
    ExecutionQueueNotFoundError,
    ExecutionQueuePermissionError,
)
from bloom_lims.schemas.beta_lab import (
    BetaAcceptedMaterialCreateRequest,
    BetaClaimCreateRequest,
    BetaClaimReleaseRequest,
    BetaClaimResponse,
    BetaConsumeMaterialRequest,
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
    BetaQueueTransitionRequest,
    BetaQueueTransitionResponse,
    BetaReservationCreateRequest,
    BetaReservationReleaseRequest,
    BetaReservationResponse,
    BetaRunCreateRequest,
    BetaRunResolutionResponse,
    BetaRunResponse,
    BetaSpecimenUpdateRequest,
    BetaTubeCreateRequest,
    BetaTubeResponse,
    BetaTubeUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external/atlas/beta", tags=["External Atlas Beta"])


def require_external_write(
    user: APIUser = Depends(require_external_atlas_api_enabled),
) -> APIUser:
    if not user.has_permission(Permission.BLOOM_WRITE):
        raise HTTPException(status_code=403, detail="Write permission required")
    return user


def require_external_ursa_read(
    user: APIUser = Depends(require_external_ursa_api_enabled),
) -> APIUser:
    if not user.has_permission(Permission.BLOOM_READ):
        raise HTTPException(status_code=403, detail="Read permission required")
    return user


def _status_for_value_error(exc: ValueError) -> int:
    detail = str(exc).lower()
    if "not found" in detail:
        return 404
    return 400


def _raise_beta_http_error(exc: Exception, *, logger_message: str) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=_status_for_value_error(exc),
            detail=str(exc),
        ) from exc
    if isinstance(exc, ExecutionQueueNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (ExecutionQueueConflictError, ExecutionQueuePermissionError, ExecutionQueueError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.exception(logger_message)
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/materials", response_model=BetaMaterialResponse)
async def register_accepted_material(
    payload: BetaAcceptedMaterialCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.register_accepted_material(
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed registering accepted material",
        )
    finally:
        service.close()


@router.post("/tubes", response_model=BetaTubeResponse)
async def create_empty_tube(
    payload: BetaTubeCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.create_empty_tube(
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed creating empty Bloom tube",
        )
    finally:
        service.close()


@router.patch("/tubes/{container_euid}", response_model=BetaTubeResponse)
async def update_tube(
    container_euid: str,
    payload: BetaTubeUpdateRequest,
    user: APIUser = Depends(require_external_write),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.update_tube(
            container_euid=container_euid,
            payload=payload,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed updating Bloom tube",
        )
    finally:
        service.close()


@router.patch("/specimens/{specimen_euid}", response_model=BetaMaterialResponse)
async def update_specimen(
    specimen_euid: str,
    payload: BetaSpecimenUpdateRequest,
    user: APIUser = Depends(require_external_write),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.update_specimen(
            specimen_euid=specimen_euid,
            payload=payload,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed updating Bloom specimen",
        )
    finally:
        service.close()


@router.post(
    "/queues/{queue_name}/items/{material_euid}",
    response_model=BetaQueueTransitionResponse,
)
async def move_material_to_queue(
    queue_name: str,
    material_euid: str,
    payload: BetaQueueTransitionRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.move_material_to_queue(
            material_euid=material_euid,
            queue_name=queue_name,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed moving Bloom material to beta queue",
        )
    finally:
        service.close()


@router.post(
    "/queues/{queue_name}/items/{material_euid}/claim",
    response_model=BetaClaimResponse,
)
async def claim_material_in_queue(
    queue_name: str,
    material_euid: str,
    payload: BetaClaimCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.claim_material_in_queue(
            material_euid=material_euid,
            queue_name=queue_name,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed claiming Bloom beta queue material",
        )
    finally:
        service.close()


@router.post("/claims/{claim_euid}/release", response_model=BetaClaimResponse)
async def release_claim(
    claim_euid: str,
    payload: BetaClaimReleaseRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.release_claim(
            claim_euid=claim_euid,
            reason=payload.reason,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed releasing Bloom beta queue claim",
        )
    finally:
        service.close()


@router.post(
    "/materials/{material_euid}/reservations",
    response_model=BetaReservationResponse,
)
async def reserve_material(
    material_euid: str,
    payload: BetaReservationCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.reserve_material(
            material_euid=material_euid,
            reason=payload.reason,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed reserving Bloom beta material",
        )
    finally:
        service.close()


@router.post(
    "/reservations/{reservation_euid}/release",
    response_model=BetaReservationResponse,
)
async def release_reservation(
    reservation_euid: str,
    payload: BetaReservationReleaseRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.release_reservation(
            reservation_euid=reservation_euid,
            reason=payload.reason,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed releasing Bloom beta material reservation",
        )
    finally:
        service.close()


@router.post(
    "/materials/{material_euid}/consume",
    response_model=BetaConsumeMaterialResponse,
)
async def consume_material(
    material_euid: str,
    payload: BetaConsumeMaterialRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.consume_material(
            material_euid=material_euid,
            reason=payload.reason,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed consuming Bloom beta material",
        )
    finally:
        service.close()


@router.post("/extractions", response_model=BetaExtractionResponse)
async def create_extraction(
    payload: BetaExtractionCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.create_extraction(
            payload=payload, idempotency_key=idempotency_key
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed creating Bloom beta extraction output",
        )
    finally:
        service.close()


@router.post("/post-extract-qc", response_model=BetaPostExtractQCResponse)
async def record_post_extract_qc(
    payload: BetaPostExtractQCRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.record_post_extract_qc(
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed recording Bloom beta post-extract QC",
        )
    finally:
        service.close()


@router.post("/library-prep", response_model=BetaLibraryPrepResponse)
async def create_library_prep(
    payload: BetaLibraryPrepCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.create_library_prep(
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed creating Bloom beta library prep output",
        )
    finally:
        service.close()


@router.post("/pools", response_model=BetaPoolResponse)
async def create_pool(
    payload: BetaPoolCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.create_pool(payload=payload, idempotency_key=idempotency_key)
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed creating Bloom beta sequencing pool",
        )
    finally:
        service.close()


@router.post("/runs", response_model=BetaRunResponse)
async def create_run(
    payload: BetaRunCreateRequest,
    user: APIUser = Depends(require_external_write),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.create_run(payload=payload, idempotency_key=idempotency_key)
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed creating Bloom beta sequencing run",
        )
    finally:
        service.close()


@router.get("/runs/{run_euid}/resolve", response_model=BetaRunResolutionResponse)
async def resolve_run_assignment(
    run_euid: str,
    flowcell_id: str = Query(...),
    lane: str = Query(...),
    library_barcode: str = Query(...),
    user: APIUser = Depends(require_external_ursa_read),
):
    service = BetaLabService(app_username=user.email)
    try:
        return service.resolve_run_assignment(
            run_euid=run_euid,
            flowcell_id=flowcell_id,
            lane=lane,
            library_barcode=library_barcode,
        )
    except Exception as exc:
        _raise_beta_http_error(
            exc,
            logger_message="Failed resolving Bloom beta run index",
        )
    finally:
        service.close()
