"""Bloom lab action APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from bloom_lims.domain.lab_actions import LabActionsService
from bloom_lims.schemas.lab_actions import (
    ExtractionPlateRequest,
    ExtractionQcPlateRequest,
    LabSetMembersRequest,
    LabSetRequest,
    PlateWellDataRequest,
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


@router.post("/extraction-qc-plates")
async def fill_extraction_qc_plate(
    payload: ExtractionQcPlateRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.fill_extraction_qc_plate(payload)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.post("/plate-well-data")
async def attach_plate_well_data(
    payload: PlateWellDataRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.attach_plate_well_data(payload)
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


@router.post("/sets")
async def create_lab_set(
    payload: LabSetRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.create_lab_set(payload)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.get("/sets/{set_euid}")
async def get_lab_set(
    set_euid: str,
    user: APIUser = Depends(require_read),
):
    service = _service_for_user(user)
    try:
        return service.get_lab_set(set_euid)
    except Exception as exc:
        _raise_http(exc)
    finally:
        service.close()


@router.post("/sets/{set_euid}/members")
async def add_lab_set_members(
    set_euid: str,
    payload: LabSetMembersRequest,
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        return service.add_lab_set_members(set_euid, payload)
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
        content, filename, media_type = service.sequencing_sample_sheet_download(
            set_euid
        )
        return PlainTextResponse(
            content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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


@router.post("/spreadsheet-import")
async def import_lab_action_spreadsheet(
    file: UploadFile = File(...),
    dry_run: bool = Query(True),
    user: APIUser = Depends(require_write),
):
    service = _service_for_user(user)
    try:
        data = await file.read()
        return service.import_spreadsheet(
            filename=file.filename or "upload.xlsx",
            data=data,
            dry_run=dry_run,
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
