"""Bloom lab action APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from bloom_lims.domain.lab_actions import LabActionsService
from bloom_lims.schemas.lab_actions import (
    ExtractionPlateRequest,
    PrintEuidRequest,
    SeqLibraryPlateRequest,
    SeqLibraryPoolRequest,
    SeqRunSetRequest,
)
from bloom_lims.tapdb_adapter import BLOOMdb3

from .dependencies import APIUser, require_read, require_write

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lab-actions", tags=["Lab Actions"])


def _service_for_user(user: APIUser) -> LabActionsService:
    return LabActionsService(
        BLOOMdb3(app_username=user.email),
        user_id=user.user_id,
        email=user.email,
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.exception("Bloom lab action failed")
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/extraction-plates")
async def create_extraction_plate(
    payload: ExtractionPlateRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.create_extraction_plate(payload)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.post("/seq-library-plates")
async def create_seq_library_plate(
    payload: SeqLibraryPlateRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.create_seq_library_plate(payload)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.post("/seq-library-pools")
async def create_seq_library_pool(
    payload: SeqLibraryPoolRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.create_seq_library_pool(payload)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.post("/seq-runs")
async def create_seq_run_set(
    payload: SeqRunSetRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.create_seq_run_set(payload)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.get("/seq-runs/{set_euid}/samplesheet")
async def download_seq_run_sample_sheet(
    set_euid: str,
    user: APIUser = Depends(require_read),
):
    service = _service_for_user(user)
    try:
        content = service.illumina_sample_sheet(set_euid)
        return PlainTextResponse(
            content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{set_euid}_SampleSheet.csv"'
            },
        )
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.get("/plates/{plate_euid}/mapping.csv")
async def download_plate_mapping_csv(
    plate_euid: str,
    user: APIUser = Depends(require_read),
):
    service = _service_for_user(user)
    try:
        content = service.plate_mapping_csv(plate_euid)
        return PlainTextResponse(
            content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{plate_euid}_mapping.csv"'
            },
        )
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.post("/print-euids")
async def print_euids(
    payload: PrintEuidRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.print_euids(payload)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()
