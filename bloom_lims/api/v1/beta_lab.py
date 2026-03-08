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
    BetaQueueTransitionRequest,
    BetaQueueTransitionResponse,
    BetaRunCreateRequest,
    BetaRunResolutionResponse,
    BetaRunResponse,
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed registering accepted material")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed moving Bloom material to beta queue")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed creating Bloom beta extraction output")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed recording Bloom beta post-extract QC")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed creating Bloom beta library prep output")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed creating Bloom beta sequencing pool")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed creating Bloom beta sequencing run")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_for_value_error(exc), detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed resolving Bloom beta run index")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        service.close()
