"""
BLOOM LIMS Health Check Endpoints

This module provides health check endpoints for monitoring and orchestration.

Endpoints:
    GET /health - Overall system health status
    GET /health/live - Kubernetes liveness probe
    GET /health/ready - Kubernetes readiness probe

Usage:
    from bloom_lims.health import health_router
    app.include_router(health_router)
"""

import logging
import platform
import psutil
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from bloom_lims.api.v1.dependencies import APIUser, require_api_auth
from bloom_lims.config import get_settings
from bloom_lims.observability import (
    build_health_payload,
    build_healthz_payload,
    build_readyz_payload,
)


logger = logging.getLogger(__name__)


# Pydantic models for health responses
class ComponentHealth(BaseModel):
    """Health status of a single component."""
    name: str
    status: str  # healthy, degraded, unhealthy
    latency_ms: Optional[float] = None
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    """Full health check response."""
    status: str  # healthy, degraded, unhealthy
    timestamp: datetime
    version: str
    environment: str
    uptime_seconds: float
    components: List[ComponentHealth] = []
    system: Optional[Dict[str, Any]] = None


class LivenessResponse(BaseModel):
    """Liveness probe response."""
    status: str
    timestamp: datetime


class ReadinessResponse(BaseModel):
    """Readiness probe response."""
    status: str
    ready: bool
    timestamp: datetime
    checks: Dict[str, bool] = {}


# Track startup time for uptime calculation
_startup_time = datetime.now(UTC)


# Create routers
health_router = APIRouter(prefix="/health", tags=["Health"])
probe_router = APIRouter(tags=["Health"])


async def check_database_health() -> ComponentHealth:
    """Check database connectivity and health."""
    import time
    start = time.time()
    
    try:
        from bloom_lims.db import BLOOMdb3
        bdb = BLOOMdb3(echo_sql=False)
        
        # Execute a simple query
        result = bdb.session.execute(text("SELECT 1")).fetchone()
        latency = (time.time() - start) * 1000
        
        if result:
            return ComponentHealth(
                name="database",
                status="healthy",
                latency_ms=round(latency, 2),
                message="PostgreSQL connection successful",
                details={"query": "SELECT 1", "observed_at": datetime.now(UTC).isoformat()},
            )
        else:
            return ComponentHealth(
                name="database",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="Query returned no result",
                details={"query": "SELECT 1", "observed_at": datetime.now(UTC).isoformat()},
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.error(f"Database health check failed: {e}")
        return ComponentHealth(
            name="database",
            status="unhealthy",
            latency_ms=round(latency, 2),
            message=str(e),
            details={"observed_at": datetime.now(UTC).isoformat()},
        )


async def check_cognito_health() -> ComponentHealth:
    """Check Cognito connectivity by resolving JWKS metadata."""
    import time
    start = time.time()
    
    settings = get_settings()
    if not (
        settings.auth.cognito_user_pool_id
        and settings.auth.cognito_region
        and settings.auth.cognito_domain
    ):
        return ComponentHealth(
            name="cognito",
            status="degraded",
            message="Cognito not configured",
        )
    
    try:
        import httpx
        jwks_url = (
            f"https://cognito-idp.{settings.auth.cognito_region}.amazonaws.com/"
            f"{settings.auth.cognito_user_pool_id}/.well-known/jwks.json"
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(jwks_url)
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                return ComponentHealth(
                    name="cognito",
                    status="healthy",
                    latency_ms=round(latency, 2),
                    message="Cognito JWKS reachable",
                    details={"observed_at": datetime.now(UTC).isoformat()},
                )
            else:
                return ComponentHealth(
                    name="cognito",
                    status="degraded",
                    latency_ms=round(latency, 2),
                    message=f"Cognito JWKS returned status {response.status_code}",
                    details={"observed_at": datetime.now(UTC).isoformat()},
                )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning(f"Cognito health check failed: {e}")
        return ComponentHealth(
            name="cognito",
            status="degraded",
            latency_ms=round(latency, 2),
            message=str(e),
            details={"observed_at": datetime.now(UTC).isoformat()},
        )


def get_system_info() -> Dict[str, Any]:
    """Get system resource information."""
    try:
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_available_mb": round(psutil.virtual_memory().available / (1024 * 1024), 2),
            "disk_percent": psutil.disk_usage("/").percent,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "hostname": platform.node(),
        }
    except Exception as e:
        logger.warning(f"Could not get system info: {e}")
        return {}


@health_router.get("")
@health_router.get("/")
async def health_check(
    request: Request,
    user: APIUser = Depends(require_api_auth),
) -> dict:
    """
    Full health check endpoint.

    Returns comprehensive health status including:
    - Database connectivity
    - External service status
    - System resource metrics
    - Version information
    """
    settings = get_settings()
    uptime = (datetime.now(UTC) - _startup_time).total_seconds()

    # Check components
    components = []

    db_health = await check_database_health()
    components.append(db_health)

    cognito_health = await check_cognito_health()
    components.append(cognito_health)

    # Determine overall status
    statuses = [c.status for c in components]
    if all(s == "healthy" for s in statuses):
        overall_status = "healthy"
    elif "unhealthy" in statuses:
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    db_payload = {
        "status": "ok" if db_health.status == "healthy" else "error",
        "latency_ms": db_health.latency_ms,
        "detail": db_health.message,
        "details": db_health.details,
        "observed_at": (db_health.details or {}).get("observed_at"),
    }
    request.app.state.observability.record_db_probe(
        status=str(db_payload["status"]),
        latency_ms=float(db_payload["latency_ms"] or 0.0),
        detail=str(db_payload["detail"] or ""),
    )
    auth_payload = {
        "status": "ok" if cognito_health.status == "healthy" else "degraded",
        "mode": "cognito",
        "cognito_configured": bool(
            settings.auth.cognito_domain
            and settings.auth.cognito_user_pool_id
            and settings.auth.cognito_client_id
        ),
        "observed_at": (cognito_health.details or {}).get("observed_at"),
        "detail": cognito_health.message,
    }
    snapshot = {
        "status": "ok" if db_payload["status"] == "ok" else "degraded",
        "checks": {
            "process": {
                "status": "ok",
                "uptime_seconds": round(uptime, 2),
                "system": get_system_info(),
            },
            "database": db_payload,
            "auth": auth_payload,
        },
    }
    request.app.state.observability.record_auth_event(
        status="ok",
        mode=user.auth_source,
        detail=request.url.path,
        service_principal=user.auth_source == "legacy_api_key",
    )
    projection = request.app.state.observability.projection(observed_at=db_payload.get("observed_at"))
    return build_health_payload(request, projection=projection, health_snapshot=snapshot)


@health_router.get("/live", response_model=LivenessResponse)
async def liveness_probe() -> LivenessResponse:
    """
    Kubernetes liveness probe.

    Returns 200 if the application is running.
    This endpoint should be fast and not check external dependencies.
    """
    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(UTC),
    )


@health_router.get("/ready", response_model=ReadinessResponse)
async def readiness_probe() -> ReadinessResponse:
    """
    Kubernetes readiness probe.

    Returns 200 if the application is ready to receive traffic.
    Checks critical dependencies like database connectivity.
    """
    checks = {}

    # Check database
    db_health = await check_database_health()
    checks["database"] = db_health.status == "healthy"

    # Check if in maintenance mode
    settings = get_settings()
    checks["not_maintenance"] = not settings.features.maintenance_mode

    # Overall readiness
    ready = all(checks.values())

    response = ReadinessResponse(
        status="ready" if ready else "not_ready",
        ready=ready,
        timestamp=datetime.now(UTC),
        checks=checks,
    )

    if not ready:
        raise HTTPException(status_code=503, detail=response.model_dump(mode="json"))

    return response


@probe_router.get("/healthz")
async def healthz_probe(request: Request) -> dict[str, Any]:
    """Top-level liveness alias for orchestration probes."""
    return build_healthz_payload(
        request,
        started_at=request.app.state.observability.started_at,
    )


@probe_router.get("/readyz")
async def readyz_probe(request: Request) -> JSONResponse:
    """Top-level readiness alias for orchestration probes."""
    db_health = await check_database_health()
    db_payload = {
        "status": "ok" if db_health.status == "healthy" else "error",
        "latency_ms": db_health.latency_ms,
        "detail": db_health.message,
        "details": db_health.details or {},
        "observed_at": (db_health.details or {}).get("observed_at"),
    }
    request.app.state.observability.record_db_probe(
        status=str(db_payload["status"]),
        latency_ms=float(db_payload["latency_ms"] or 0.0),
        detail=str(db_payload["detail"] or ""),
    )
    settings = get_settings()
    ready = db_payload["status"] == "ok" and not settings.features.maintenance_mode
    payload = build_readyz_payload(
        request,
        started_at=request.app.state.observability.started_at,
        database_check=db_payload,
        ready=ready,
        process_details={"maintenance_mode": bool(settings.features.maintenance_mode)},
    )
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@health_router.get("/metrics")
async def metrics() -> Dict[str, Any]:
    """
    Basic metrics endpoint.

    Returns system and application metrics in a simple format.
    For production, consider using Prometheus metrics.
    """
    settings = get_settings()
    uptime = (datetime.now(UTC) - _startup_time).total_seconds()

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime_seconds": round(uptime, 2),
        "environment": settings.environment,
        "system": get_system_info(),
    }
