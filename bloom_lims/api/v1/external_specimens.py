"""External specimen API endpoints for Atlas integrations."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.domain.external_specimens import ExternalSpecimenService
from bloom_lims.integrations.atlas.events import emit_bloom_event
from bloom_lims.schemas.external_specimens import (
    AtlasReferences,
    ExternalSpecimenCreateRequest,
    ExternalSpecimenLookupResponse,
    ExternalSpecimenResponse,
    ExternalSpecimenUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external/specimens", tags=["External Specimens"])


def _specimen_event_payload(response: ExternalSpecimenResponse | dict, extra: dict | None = None) -> dict:
    if isinstance(response, dict):
        specimen_euid = response.get("specimen_euid") or response.get("euid")
        specimen_uuid = response.get("specimen_uuid") or response.get("uuid")
        container_euid = response.get("container_euid")
        status = response.get("status")
        atlas_refs = response.get("atlas_refs") if isinstance(response.get("atlas_refs"), dict) else {}
        properties = response.get("properties") if isinstance(response.get("properties"), dict) else {}
    else:
        specimen_euid = response.specimen_euid
        specimen_uuid = response.specimen_uuid
        container_euid = response.container_euid
        status = response.status
        atlas_refs = response.atlas_refs
        properties = response.properties

    payload = {
        "euid": specimen_euid,
        "specimen_euid": specimen_euid,
        "container_euid": container_euid,
        "uuid": specimen_uuid,
        "specimen_uuid": specimen_uuid,
        "status": status,
        "atlas_refs": atlas_refs,
        "properties": properties,
    }
    if extra:
        payload.update(extra)
    return payload


@router.post("", response_model=ExternalSpecimenResponse)
async def create_external_specimen(
    payload: ExternalSpecimenCreateRequest,
    user: APIUser = Depends(require_external_token_auth),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    service = ExternalSpecimenService(app_username=user.email)
    try:
        result = service.create_specimen(payload=payload, idempotency_key=idempotency_key)
        created_flag = result.get("created", True) if isinstance(result, dict) else bool(result.created)
        if created_flag:
            emit_bloom_event("specimen.created", _specimen_event_payload(result))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed creating external specimen")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        service.close()


@router.get("/by-reference", response_model=ExternalSpecimenLookupResponse)
async def find_external_specimens_by_reference(
    order_number: str | None = Query(None),
    patient_id: str | None = Query(None),
    shipment_number: str | None = Query(None),
    package_number: str | None = Query(None),
    kit_barcode: str | None = Query(None),
    user: APIUser = Depends(require_external_token_auth),
):
    refs = AtlasReferences(
        order_number=order_number,
        patient_id=patient_id,
        shipment_number=shipment_number,
        package_number=package_number,
        kit_barcode=kit_barcode,
    )
    service = ExternalSpecimenService(app_username=user.email)
    try:
        items = service.find_by_references(refs)
        return ExternalSpecimenLookupResponse(items=items, total=len(items))
    except Exception as exc:
        logger.exception("Failed querying external specimens by reference")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        service.close()


@router.get("/{specimen_euid}", response_model=ExternalSpecimenResponse)
async def get_external_specimen(
    specimen_euid: str,
    user: APIUser = Depends(require_external_token_auth),
):
    service = ExternalSpecimenService(app_username=user.email)
    try:
        return service.get_specimen(specimen_euid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed fetching external specimen")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        service.close()


@router.patch("/{specimen_euid}", response_model=ExternalSpecimenResponse)
async def update_external_specimen(
    specimen_euid: str,
    payload: ExternalSpecimenUpdateRequest,
    user: APIUser = Depends(require_external_token_auth),
):
    service = ExternalSpecimenService(app_username=user.email)
    previous_status: str | None = None
    try:
        if hasattr(service, "get_specimen"):
            try:
                previous = service.get_specimen(specimen_euid)
                previous_status = (
                    previous.get("status")
                    if isinstance(previous, dict)
                    else previous.status
                )
            except ValueError:
                previous_status = None

        result = service.update_specimen(specimen_euid=specimen_euid, payload=payload)
        emit_bloom_event("specimen.updated", _specimen_event_payload(result))
        result_status = result.get("status") if isinstance(result, dict) else result.status
        if previous_status is not None and previous_status != result_status:
            emit_bloom_event(
                "specimen.status_changed",
                _specimen_event_payload(
                    result,
                    {
                        "previous_status": previous_status,
                        "current_status": result_status,
                    },
                ),
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed updating external specimen")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        service.close()
