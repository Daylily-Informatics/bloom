from __future__ import annotations

import os
import socket
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import ceil
from threading import RLock
from typing import Any

from fastapi import Request

from bloom_lims import __version__
from bloom_lims.api.v1.dependencies import APIUser
from bloom_lims.config import get_settings


CONTRACT_VERSION = "v3"
SERVICE_NAME = "bloom"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _instance_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _build_sha() -> str:
    return (
        os.environ.get("BLOOM_BUILD_SHA")
        or os.environ.get("BUILD_SHA")
        or os.environ.get("GIT_SHA")
        or ""
    )


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * quantile) - 1))
    return round(float(ordered[index]), 3)


@dataclass
class ProjectionMetadata:
    state: str = "ready"
    stale: bool = False
    observed_at: str | None = None
    last_synced_at: str | None = None
    detail: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "stale": self.stale,
            "observed_at": self.observed_at,
            "last_synced_at": self.last_synced_at,
            "detail": self.detail,
        }


@dataclass
class EndpointRollup:
    method: str
    route_template: str
    request_count: int = 0
    error_count: int = 0
    status_class_counts: Counter[str] = field(default_factory=Counter)
    durations_ms: deque[float] = field(default_factory=lambda: deque(maxlen=512))
    fingerprints: set[str] = field(default_factory=set)
    observed_at: str = field(default_factory=_utcnow)

    def record(self, *, status_code: int, duration_ms: float, fingerprint: str) -> None:
        self.request_count += 1
        if status_code >= 500:
            self.error_count += 1
        self.status_class_counts[f"{status_code // 100}xx"] += 1
        self.durations_ms.append(float(duration_ms))
        if fingerprint:
            self.fingerprints.add(fingerprint)
        self.observed_at = _utcnow()

    def to_dict(self) -> dict[str, Any]:
        durations = list(self.durations_ms)
        return {
            "method": self.method,
            "route_template": self.route_template,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "status_class_counts": dict(self.status_class_counts),
            "p50_ms": _percentile(durations, 0.50),
            "p95_ms": _percentile(durations, 0.95),
            "p99_ms": _percentile(durations, 0.99),
            "fingerprint_count": len(self.fingerprints),
            "observed_at": self.observed_at,
        }


@dataclass
class FamilyRollup:
    family: str
    request_count: int = 0
    error_count: int = 0
    durations_ms: deque[float] = field(default_factory=lambda: deque(maxlen=512))
    observed_at: str = field(default_factory=_utcnow)

    def record(self, *, status_code: int, duration_ms: float) -> None:
        self.request_count += 1
        if status_code >= 500:
            self.error_count += 1
        self.durations_ms.append(float(duration_ms))
        self.observed_at = _utcnow()

    def to_dict(self) -> dict[str, Any]:
        durations = list(self.durations_ms)
        return {
            "family": self.family,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "p50_ms": _percentile(durations, 0.50),
            "p95_ms": _percentile(durations, 0.95),
            "p99_ms": _percentile(durations, 0.99),
            "observed_at": self.observed_at,
        }


class BloomObservabilityStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._started_at = _utcnow()
        self._endpoint_rollups: dict[tuple[str, str], EndpointRollup] = {}
        self._family_rollups: dict[str, FamilyRollup] = {}
        self._db_probes: deque[dict[str, Any]] = deque(maxlen=25)
        self._auth_recent: deque[dict[str, Any]] = deque(maxlen=25)
        self._auth_status_counts: Counter[str] = Counter()
        self._obs_services_snapshot = self._build_obs_services_snapshot()

    def _build_obs_services_snapshot(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "endpoints": [
                {"path": "/healthz", "auth": "none", "kind": "liveness"},
                {"path": "/readyz", "auth": "none", "kind": "readiness"},
                {"path": "/health", "auth": "operator_or_service_token", "kind": "summary"},
                {"path": "/obs_services", "auth": "operator_or_service_token", "kind": "discovery"},
                {"path": "/api_health", "auth": "operator_or_service_token", "kind": "api_rollup"},
                {"path": "/endpoint_health", "auth": "operator_or_service_token", "kind": "endpoint_rollup"},
                {"path": "/db_health", "auth": "operator_or_service_token", "kind": "database"},
                {"path": "/api/anomalies", "auth": "operator_or_service_token", "kind": "anomaly_list"},
                {
                    "path": "/api/anomalies/{anomaly_id}",
                    "auth": "operator_or_service_token",
                    "kind": "anomaly_detail",
                },
                {"path": "/my_health", "auth": "authenticated_self", "kind": "self"},
                {"path": "/auth_health", "auth": "operator_or_service_token", "kind": "auth"},
            ],
            "extensions": [
                "bloom.admin_metrics_ui",
                "bloom.admin_observability_ui",
                "bloom.anomalies_v1",
            ],
            "observed_at": self._started_at,
        }

    def projection(self, *, observed_at: str | None = None, detail: str | None = None) -> ProjectionMetadata:
        seen_at = observed_at or self._started_at
        return ProjectionMetadata(
            state="ready",
            stale=False,
            observed_at=seen_at,
            last_synced_at=seen_at,
            detail=detail,
        )

    def record_http_request(
        self,
        *,
        method: str,
        route_template: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        family = self._classify_family(route_template)
        key = (method.upper(), route_template)
        fingerprint = f"{method.upper()}:{route_template}:{status_code // 100}xx"
        with self._lock:
            endpoint_rollup = self._endpoint_rollups.setdefault(
                key,
                EndpointRollup(method=method.upper(), route_template=route_template),
            )
            endpoint_rollup.record(
                status_code=status_code,
                duration_ms=duration_ms,
                fingerprint=fingerprint,
            )
            family_rollup = self._family_rollups.setdefault(family, FamilyRollup(family=family))
            family_rollup.record(status_code=status_code, duration_ms=duration_ms)

    def record_db_probe(self, *, status: str, latency_ms: float, detail: str) -> None:
        with self._lock:
            self._db_probes.appendleft(
                {
                    "status": status,
                    "latency_ms": round(float(latency_ms), 3),
                    "detail": str(detail or ""),
                    "observed_at": _utcnow(),
                }
            )

    def record_auth_event(
        self,
        *,
        status: str,
        mode: str,
        detail: str,
        service_principal: bool,
    ) -> None:
        event = {
            "status": status,
            "mode": mode,
            "detail": str(detail or ""),
            "service_principal": service_principal,
            "observed_at": _utcnow(),
        }
        with self._lock:
            self._auth_recent.appendleft(event)
            self._auth_status_counts[status] += 1

    def obs_services_snapshot(self) -> tuple[ProjectionMetadata, dict[str, Any]]:
        snapshot = dict(self._obs_services_snapshot)
        observed_at = str(snapshot.get("observed_at") or self._started_at)
        return self.projection(observed_at=observed_at), snapshot

    def api_health(self) -> tuple[ProjectionMetadata, list[dict[str, Any]]]:
        with self._lock:
            families = [rollup.to_dict() for rollup in self._family_rollups.values()]
        families.sort(key=lambda item: (-int(item["request_count"]), item["family"]))
        observed_at = families[0]["observed_at"] if families else self._started_at
        return self.projection(observed_at=observed_at), families

    def endpoint_health(self, *, offset: int, limit: int) -> tuple[ProjectionMetadata, dict[str, Any]]:
        with self._lock:
            items = [rollup.to_dict() for rollup in self._endpoint_rollups.values()]
        items.sort(key=lambda item: (-int(item["request_count"]), item["route_template"], item["method"]))
        total = len(items)
        sliced = items[offset : offset + limit]
        observed_at = sliced[0]["observed_at"] if sliced else (items[0]["observed_at"] if items else self._started_at)
        return self.projection(observed_at=observed_at), {
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": sliced,
        }

    def latest_db_probe(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._db_probes[0]) if self._db_probes else None

    def db_health(self) -> tuple[ProjectionMetadata, dict[str, Any]]:
        from bloom_lims.tapdb_metrics import build_metrics_page_context

        env_name = os.environ.get("TAPDB_ENV", get_settings().tapdb.env)
        metrics_ctx = build_metrics_page_context(env_name, limit=1000)
        summary = dict(metrics_ctx.get("summary") or {})
        latest = self.latest_db_probe()
        observed_at = (
            (latest or {}).get("observed_at")
            or str(summary.get("last_seen") or "")
            or self._started_at
        )
        payload = {
            "status": str((latest or {}).get("status") or "unknown"),
            "latest": latest,
            "recent": list(summary.get("slowest") or [])[:25],
            "slowest": list(summary.get("slowest") or [])[:10],
            "hottest": list(summary.get("by_path") or [])[:10],
            "by_path": list(summary.get("by_path") or [])[:25],
            "by_table": list(summary.get("by_table") or [])[:25],
            "metrics_enabled": bool(metrics_ctx.get("metrics_enabled", False)),
            "metrics_message": str(metrics_ctx.get("metrics_message") or ""),
            "observed_at": observed_at,
        }
        return self.projection(observed_at=observed_at), payload

    def auth_health(self) -> tuple[ProjectionMetadata, dict[str, Any]]:
        settings = get_settings()
        with self._lock:
            recent = list(self._auth_recent)
            status_counts = dict(self._auth_status_counts)
        latest = recent[0] if recent else None
        observed_at = str((latest or {}).get("observed_at") or self._started_at)
        return self.projection(observed_at=observed_at), {
            "status": str((latest or {}).get("status") or "unknown"),
            "mode": str((latest or {}).get("mode") or "unknown"),
            "cognito_configured": bool(
                settings.auth.cognito_domain
                and settings.auth.cognito_user_pool_id
                and settings.auth.cognito_client_id
            ),
            "cognito_domain": str(settings.auth.cognito_domain or ""),
            "user_pool_id": str(settings.auth.cognito_user_pool_id or ""),
            "app_client_id_present": bool(settings.auth.cognito_client_id),
            "recent": recent,
            "status_counts": status_counts,
            "observed_at": observed_at,
        }

    def _classify_family(self, route_template: str) -> str:
        path = route_template or "/"
        if path.startswith("/api/v1/"):
            parts = [part for part in path.split("/") if part]
            return parts[2] if len(parts) > 2 else "api"
        if path.startswith("/auth"):
            return "auth"
        if path.startswith("/admin"):
            return "admin"
        if path in {"/health", "/healthz", "/readyz", "/obs_services", "/api_health", "/endpoint_health", "/db_health", "/my_health", "/auth_health"}:
            return "observability"
        return "web"


def base_frame(request: Request, *, status: str) -> dict[str, Any]:
    settings = get_settings()
    return {
        "contract_version": CONTRACT_VERSION,
        "service": SERVICE_NAME,
        "environment": settings.environment,
        "instance_id": _instance_id(),
        "observed_at": _utcnow(),
        "status": status,
        "request_id": getattr(request.state, "request_id", ""),
        "correlation_id": getattr(request.state, "correlation_id", ""),
        "build": {
            "version": settings.api.version or __version__,
            "sha": _build_sha(),
        },
    }


def _status_for_projection(projection: ProjectionMetadata, ready_status: str) -> str:
    return ready_status if projection.state == "ready" else "unknown"


def _with_projection(payload: dict[str, Any], projection: ProjectionMetadata) -> dict[str, Any]:
    payload["projection"] = projection.model_dump()
    return payload


def build_health_payload(request: Request, *, projection: ProjectionMetadata, health_snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = base_frame(
        request,
        status=_status_for_projection(projection, str(health_snapshot.get("status") or "unknown")),
    )
    payload["checks"] = dict(health_snapshot.get("checks") or {})
    return _with_projection(payload, projection)


def build_obs_services_payload(request: Request, *, projection: ProjectionMetadata, snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = base_frame(
        request,
        status=_status_for_projection(projection, str(snapshot.get("status") or "ok")),
    )
    payload["endpoints"] = list(snapshot.get("endpoints") or [])
    payload["extensions"] = list(snapshot.get("extensions") or [])
    return _with_projection(payload, projection)


def build_api_health_payload(request: Request, *, projection: ProjectionMetadata, families: list[dict[str, Any]]) -> dict[str, Any]:
    payload = base_frame(request, status=_status_for_projection(projection, "ok"))
    payload["families"] = families
    return _with_projection(payload, projection)


def build_endpoint_health_payload(
    request: Request,
    *,
    projection: ProjectionMetadata,
    total: int,
    offset: int,
    limit: int,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = base_frame(request, status=_status_for_projection(projection, "ok"))
    payload["page"] = {"total": total, "offset": offset, "limit": limit}
    payload["items"] = items
    return _with_projection(payload, projection)


def build_db_health_payload(request: Request, *, projection: ProjectionMetadata, db_health: dict[str, Any]) -> dict[str, Any]:
    payload = base_frame(
        request,
        status=_status_for_projection(projection, str(db_health.get("status") or "unknown")),
    )
    payload["database"] = db_health
    return _with_projection(payload, projection)


def build_auth_health_payload(request: Request, *, projection: ProjectionMetadata, auth_rollup: dict[str, Any]) -> dict[str, Any]:
    payload = base_frame(
        request,
        status=_status_for_projection(projection, str(auth_rollup.get("status") or "unknown")),
    )
    payload["auth"] = {
        "mode": str(auth_rollup.get("mode") or ""),
        "cognito_configured": bool(auth_rollup.get("cognito_configured", False)),
        "cognito_domain": str(auth_rollup.get("cognito_domain") or ""),
        "user_pool_id": str(auth_rollup.get("user_pool_id") or ""),
        "app_client_id_present": bool(auth_rollup.get("app_client_id_present", False)),
        "recent": list(auth_rollup.get("recent") or []),
        "status_counts": dict(auth_rollup.get("status_counts") or {}),
    }
    return _with_projection(payload, projection)


def _is_service_principal(user: APIUser) -> bool:
    return user.auth_source in {"legacy_api_key"}


def build_my_health_payload(request: Request, user: APIUser) -> dict[str, Any]:
    payload = base_frame(request, status="ok")
    payload["principal"] = {
        "subject": str(user.user_id),
        "email": user.email,
        "name": None,
        "roles": user.roles,
        "auth_mode": user.auth_source,
        "expires_at": None,
        "service_principal": _is_service_principal(user),
    }
    return payload
