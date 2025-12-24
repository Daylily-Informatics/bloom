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
import os
import platform
import psutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from bloom_lims.config import get_settings


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
_startup_time = datetime.utcnow()


# Create router
health_router = APIRouter(prefix="/health", tags=["Health"])


async def check_database_health() -> ComponentHealth:
    """Check database connectivity and health."""
    import time
    start = time.time()
    
    try:
        from bloom_lims.db import BLOOMdb3
        bdb = BLOOMdb3(echo_sql=False)
        
        # Execute a simple query
        result = bdb.session.execute("SELECT 1").fetchone()
        latency = (time.time() - start) * 1000
        
        if result:
            return ComponentHealth(
                name="database",
                status="healthy",
                latency_ms=round(latency, 2),
                message="PostgreSQL connection successful",
            )
        else:
            return ComponentHealth(
                name="database",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="Query returned no result",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.error(f"Database health check failed: {e}")
        return ComponentHealth(
            name="database",
            status="unhealthy",
            latency_ms=round(latency, 2),
            message=str(e),
        )


async def check_supabase_health() -> ComponentHealth:
    """Check Supabase connectivity."""
    import time
    start = time.time()
    
    settings = get_settings()
    if not settings.auth.supabase_url:
        return ComponentHealth(
            name="supabase",
            status="degraded",
            message="Supabase not configured",
        )
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.auth.supabase_url}/health")
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                return ComponentHealth(
                    name="supabase",
                    status="healthy",
                    latency_ms=round(latency, 2),
                    message="Supabase connection successful",
                )
            else:
                return ComponentHealth(
                    name="supabase",
                    status="degraded",
                    latency_ms=round(latency, 2),
                    message=f"Supabase returned status {response.status_code}",
                )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning(f"Supabase health check failed: {e}")
        return ComponentHealth(
            name="supabase",
            status="degraded",
            latency_ms=round(latency, 2),
            message=str(e),
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


@health_router.get("", response_model=HealthResponse)
@health_router.get("/", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Full health check endpoint.

    Returns comprehensive health status including:
    - Database connectivity
    - External service status
    - System resource metrics
    - Version information
    """
    settings = get_settings()
    uptime = (datetime.utcnow() - _startup_time).total_seconds()

    # Check components
    components = []

    db_health = await check_database_health()
    components.append(db_health)

    supabase_health = await check_supabase_health()
    components.append(supabase_health)

    # Determine overall status
    statuses = [c.status for c in components]
    if all(s == "healthy" for s in statuses):
        overall_status = "healthy"
    elif "unhealthy" in statuses:
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.utcnow(),
        version=settings.api.version,
        environment=settings.environment,
        uptime_seconds=round(uptime, 2),
        components=components,
        system=get_system_info(),
    )


@health_router.get("/live", response_model=LivenessResponse)
async def liveness_probe() -> LivenessResponse:
    """
    Kubernetes liveness probe.

    Returns 200 if the application is running.
    This endpoint should be fast and not check external dependencies.
    """
    return LivenessResponse(
        status="alive",
        timestamp=datetime.utcnow(),
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
        timestamp=datetime.utcnow(),
        checks=checks,
    )

    if not ready:
        raise HTTPException(status_code=503, detail=response.model_dump())

    return response


@health_router.get("/metrics")
async def metrics() -> Dict[str, Any]:
    """
    Basic metrics endpoint.

    Returns system and application metrics in a simple format.
    For production, consider using Prometheus metrics.
    """
    settings = get_settings()
    uptime = (datetime.utcnow() - _startup_time).total_seconds()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": round(uptime, 2),
        "environment": settings.environment,
        "system": get_system_info(),
    }

