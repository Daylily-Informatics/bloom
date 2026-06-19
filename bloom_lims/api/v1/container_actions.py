"""Generic Bloom container-action validation facade."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from bloom_lims.tapdb_adapter import BLOOMdb3, generic_instance
from bloom_lims.domain.lab_actions import LabActionsService
from bloom_lims.schemas.lab_actions import (
    ExtractionPlateRequest,
    ExtractionQcPlateRequest,
    LabSetRequest,
    PlateWellDataRequest,
    PrintEuidRequest,
    SeqLibraryPlateRequest,
    SeqLibraryPoolRequest,
    SeqRunSetRequest,
)

from .dependencies import APIUser, require_write

router = APIRouter(prefix="/container-actions", tags=["Container Actions"])


class ContainerActionScanRequest(BaseModel):
    rows: str | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    default_target: str | None = None
    child_name: str | None = None
    child_description: str | None = None
    child_content_type: str | None = None


ContainerActionOperation = Literal[
    "extraction_plate",
    "extraction_qc_plate",
    "plate_well_data",
    "seq_library_plate",
    "seq_library_pool",
    "seq_run_set",
    "lab_set",
    "print_euids",
]


class ContainerActionExecuteRequest(ContainerActionScanRequest):
    operation_type: ContainerActionOperation | None = None
    operation_payload: dict[str, Any] | None = None


def _service_for_user(user: APIUser) -> LabActionsService:
    return LabActionsService(
        BLOOMdb3(app_username=user.email),
        user_id=user.user_id,
        email=user.email,
    )


def _split_source(value: str) -> tuple[str, str | None]:
    source = str(value or "").strip()
    if not source:
        raise ValueError("source EUID is required")
    if "." not in source:
        return source, None
    euid, well = source.rsplit(".", 1)
    euid = euid.strip()
    well = well.strip().upper()
    if not euid or not well:
        raise ValueError(f"Invalid source well reference: {value!r}")
    return euid, well


def _normalize_record(row: dict[str, Any], default_target: str | None) -> dict[str, Any]:
    source = row.get("source") or row.get("source_euid") or row.get("euid") or row.get("0")
    target = (
        row.get("target")
        or row.get("target_container_euid")
        or row.get("target_container")
        or row.get("1")
        or default_target
    )
    target_well = row.get("target_well") or row.get("well") or row.get("2")
    source_euid, source_well = _split_source(str(source or ""))
    target_text = str(target or "").strip()
    if not target_text:
        raise ValueError(f"Target is required for source {source_euid}")
    create_type = None
    target_euid = target_text
    if target_text.upper().startswith("CREATE."):
        create_type = target_text.split(".", 1)[1].strip()
        target_euid = None
        if not create_type:
            raise ValueError(f"CREATE target requires a type for source {source_euid}")
    return {
        "source_euid": source_euid,
        "source_well": source_well,
        "target_euid": target_euid,
        "create_type": create_type,
        "target_well": str(target_well or "").strip().upper() or None,
        "mapping_mode": "directed" if target_well else "auto",
    }


def _parse_rows(payload: ContainerActionScanRequest) -> list[dict[str, Any]]:
    records = list(payload.records)
    if payload.rows:
        sample = payload.rows[:1024]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(StringIO(payload.rows), dialect)
        for row in reader:
            if not row or not any(str(cell).strip() for cell in row):
                continue
            records.append({str(index): value for index, value in enumerate(row)})
    if not records:
        raise ValueError("rows or records is required")
    return [_normalize_record(row, payload.default_target) for row in records]


def _object_kind(euid: str, user: APIUser) -> dict[str, Any]:
    db = BLOOMdb3(app_username=user.email)
    try:
        instance = db.session.execute(
            select(generic_instance).where(
                generic_instance.euid == euid,
                generic_instance.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        if instance is None:
            return {"euid": euid, "exists": False, "kind": None}
        return {
            "euid": euid,
            "exists": True,
            "kind": "/".join(
                [
                    str(getattr(instance, "category", "") or ""),
                    str(getattr(instance, "type", "") or ""),
                    str(getattr(instance, "subtype", "") or ""),
                    str(getattr(instance, "version", "") or ""),
                ]
            ),
        }
    finally:
        db.close()


@router.post("/validate")
async def validate_container_action(
    payload: ContainerActionScanRequest,
    user: APIUser = Depends(require_write),
):
    try:
        planned = _parse_rows(payload)
        source_types = {row["source_euid"]: _object_kind(row["source_euid"], user) for row in planned}
        target_types = {
            row["target_euid"]: _object_kind(row["target_euid"], user)
            for row in planned
            if row["target_euid"]
        }
        return {
            "valid": True,
            "row_count": len(planned),
            "planned": planned,
            "source_types": source_types,
            "target_types": target_types,
            "creates": [row for row in planned if row["create_type"]],
        }
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/execute")
async def execute_container_action(
    payload: ContainerActionExecuteRequest,
    user: APIUser = Depends(require_write),
):
    validation = await validate_container_action(payload, user)
    if not payload.operation_type:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "operation_type is required. Container actions do not infer "
                    "execution behavior from scanned rows."
                ),
                "validation": validation,
            },
        )
    if not payload.operation_payload:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "operation_payload is required for container-action execution.",
                "operation_type": payload.operation_type,
                "validation": validation,
            },
        )

    service = _service_for_user(user)
    try:
        operation_payload = payload.operation_payload
        if payload.operation_type == "extraction_plate":
            result = service.create_extraction_plate(
                ExtractionPlateRequest.model_validate(operation_payload)
            )
        elif payload.operation_type == "extraction_qc_plate":
            result = service.fill_extraction_qc_plate(
                ExtractionQcPlateRequest.model_validate(operation_payload)
            )
        elif payload.operation_type == "plate_well_data":
            result = service.attach_plate_well_data(
                PlateWellDataRequest.model_validate(operation_payload)
            )
        elif payload.operation_type == "seq_library_plate":
            result = service.create_seq_library_plate(
                SeqLibraryPlateRequest.model_validate(operation_payload)
            )
        elif payload.operation_type == "seq_library_pool":
            result = service.create_seq_library_pool(
                SeqLibraryPoolRequest.model_validate(operation_payload)
            )
        elif payload.operation_type == "seq_run_set":
            result = service.create_seq_run_set(
                SeqRunSetRequest.model_validate(operation_payload)
            )
        elif payload.operation_type == "lab_set":
            result = service.create_lab_set(LabSetRequest.model_validate(operation_payload))
        elif payload.operation_type == "print_euids":
            result = service.print_euids(PrintEuidRequest.model_validate(operation_payload))
        else:  # pragma: no cover - Literal validation should prevent this.
            raise HTTPException(status_code=400, detail="Unsupported operation_type")
        return {
            "operation_type": payload.operation_type,
            "validation": validation,
            "result": result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        service.close()
