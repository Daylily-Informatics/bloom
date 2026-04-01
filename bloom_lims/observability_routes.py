from __future__ import annotations

import logging
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from bloom_lims.anomalies import TapdbAnomalyRepository
from bloom_lims.api.v1.dependencies import APIUser, get_api_user, require_api_auth
from bloom_lims.health import check_database_health
from bloom_lims.observability import (
    build_api_health_payload,
    build_auth_health_payload,
    build_db_health_payload,
    build_endpoint_health_payload,
    build_my_health_payload,
    build_obs_services_payload,
)
from bloom_lims.tapdb_adapter import BLOOMdb3


router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)


def _record_auth(request: Request, user: APIUser) -> None:
    request.app.state.observability.record_auth_event(
        status="ok",
        mode=user.auth_source,
        detail=request.url.path,
        service_principal=user.auth_source == "legacy_api_key",
        principal_email=getattr(user, "email", "") or "",
    )


def _anomaly_repository(app_username: str) -> tuple[BLOOMdb3, TapdbAnomalyRepository]:
    bdb = BLOOMdb3(app_username=app_username)
    return bdb, TapdbAnomalyRepository(bdb.session)


@router.get("/obs_services")
async def obs_services(
    request: Request,
    user: Annotated[APIUser, Depends(require_api_auth)],
) -> dict:
    _record_auth(request, user)
    projection, snapshot = request.app.state.observability.obs_services_snapshot()
    return build_obs_services_payload(request, projection=projection, snapshot=snapshot)


@router.get("/api_health")
async def api_health(
    request: Request,
    user: Annotated[APIUser, Depends(require_api_auth)],
) -> dict:
    _record_auth(request, user)
    projection, families = request.app.state.observability.api_health()
    return build_api_health_payload(request, projection=projection, families=families)


@router.get("/endpoint_health")
async def endpoint_health(
    request: Request,
    user: Annotated[APIUser, Depends(require_api_auth)],
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
) -> dict:
    _record_auth(request, user)
    projection, payload = request.app.state.observability.endpoint_health(offset=offset, limit=limit)
    return build_endpoint_health_payload(
        request,
        projection=projection,
        total=int(payload["total"]),
        offset=int(payload["offset"]),
        limit=int(payload["limit"]),
        items=list(payload["items"]),
    )


@router.get("/db_health")
async def db_health(
    request: Request,
    user: Annotated[APIUser, Depends(require_api_auth)],
) -> dict:
    _record_auth(request, user)
    started = monotonic()
    db_component = await check_database_health()
    details = db_component.details if isinstance(db_component.details, dict) else {}
    request.app.state.observability.record_db_probe(
        status="ok" if db_component.status == "healthy" else "error",
        latency_ms=float(db_component.latency_ms or ((monotonic() - started) * 1000)),
        detail=str(db_component.message or ""),
    )
    if db_component.status != "healthy":
        try:
            bdb, repository = _anomaly_repository(getattr(user, "email", "") or "observability")
            try:
                repository.record_db_probe_failure(
                    detail=str(db_component.message or ""),
                    latency_ms=float(db_component.latency_ms or ((monotonic() - started) * 1000)),
                )
            finally:
                bdb.close()
        except Exception as exc:
            logger.warning("Failed to record db probe anomaly: %s", exc)
    projection, payload = request.app.state.observability.db_health()
    if not payload.get("observed_at"):
        payload["observed_at"] = details.get("observed_at")
    return build_db_health_payload(request, projection=projection, db_health=payload)


@router.get("/api/anomalies")
async def list_anomalies(
    request: Request,
    user: Annotated[APIUser, Depends(require_api_auth)],
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    _record_auth(request, user)
    bdb, repository = _anomaly_repository(getattr(user, "email", "") or "api-anomalies")
    try:
        items = [record.__dict__ for record in repository.list(skip=offset, limit=limit)]
        projection = repository.projection()
    finally:
        bdb.close()
    return {
        "service": "bloom",
        "contract_version": "v3",
        "observed_at": projection.observed_at,
        "projection": projection.model_dump(),
        "items": items,
        "count": len(items),
    }


@router.get("/api/anomalies/{anomaly_id}")
async def get_anomaly(
    anomaly_id: str,
    request: Request,
    user: Annotated[APIUser, Depends(require_api_auth)],
) -> dict:
    _record_auth(request, user)
    bdb, repository = _anomaly_repository(getattr(user, "email", "") or "api-anomalies")
    try:
        record = repository.get(anomaly_id)
        projection = repository.projection()
    finally:
        bdb.close()
    if record is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return {
        "service": "bloom",
        "contract_version": "v3",
        "observed_at": projection.observed_at,
        "projection": projection.model_dump(),
        "item": record.__dict__,
    }


@router.get("/my_health")
async def my_health(
    request: Request,
    user: Annotated[APIUser, Depends(get_api_user)],
) -> dict:
    if user.auth_source == "legacy_api_key":
        raise HTTPException(status_code=401, detail="Not authenticated")
    _record_auth(request, user)
    return build_my_health_payload(request, user)


@router.get("/auth_health")
async def auth_health(
    request: Request,
    user: Annotated[APIUser, Depends(require_api_auth)],
) -> dict:
    _record_auth(request, user)
    projection, payload = request.app.state.observability.auth_health()
    return build_auth_health_payload(request, projection=projection, auth_rollup=payload)
