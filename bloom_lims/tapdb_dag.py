"""Canonical TapDB DAG API integration for Bloom."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from daylily_tapdb.web import (
    DAG_V2_CONTRACT,
    DAG_V2_EXTENSION,
    DagV2Limits,
    DagV2MountResult,
    mount_tapdb_dag_surfaces,
)
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bloom_lims.api.v1.dependencies import get_api_user
from bloom_lims.config import apply_runtime_environment, get_settings

_BLOOM_DAG_LIMITS = DagV2Limits(
    max_depth=12,
    max_nodes=2_000,
    max_search_page_size=100,
)


async def _tapdb_dag_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
) -> dict[str, Any]:
    """Expose Bloom's authenticated identity in TapDB's mapping contract."""

    token = str(credentials.credentials or "") if credentials else ""
    if token.startswith("bloom_dag_"):
        path = request.url.path
        allowed = path in {
            "/api/dag/manifest", "/api/dag/v2/data", "/api/dag/v2/search",
        } or re.fullmatch(r"/api/dag/v2/object/[^/]+", path) is not None
        if request.method != "GET" or not allowed:
            raise HTTPException(status_code=403, detail="DAG read credential has no route scope")
        settings = get_settings().api
        expected = settings.dag_read_token_sha256
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        if not expected or not secrets.compare_digest(fingerprint, expected):
            raise HTTPException(status_code=401, detail="Invalid DAG read credential")
        return {"username": settings.dag_read_actor}

    user = await get_api_user(request, credentials)
    return user.dict()


def mount_tapdb_dag_api(app: FastAPI) -> DagV2MountResult:
    """Mount the canonical TapDB DAG v2 surfaces or fail Bloom startup."""

    runtime_ctx = apply_runtime_environment()
    result = mount_tapdb_dag_surfaces(
        app,
        config_path=runtime_ctx.config_path,
        service_id="bloom",
        display_name="Bloom",
        auth_dependency=_tapdb_dag_auth,
        limits=_BLOOM_DAG_LIMITS,
    )
    if not result.mounted or result.advertisement is None:
        reason = result.reason.value if result.reason is not None else "unknown"
        raise RuntimeError(
            f"Bloom TapDB DAG v2 mount failed ({reason}): {result.diagnostic or ''}"
        )
    return result


def bloom_tapdb_dag_obs_services_fragment(
    advertisement: dict[str, Any],
) -> dict[str, Any]:
    """Return Bloom-facing obs_services metadata for the TapDB DAG contract."""

    manifest = advertisement.get("dag_v2")
    if not isinstance(manifest, dict):
        raise RuntimeError("Mounted TapDB DAG v2 advertisement is missing its manifest")
    if (
        manifest.get("contract") != DAG_V2_CONTRACT
        or manifest.get("extension") != DAG_V2_EXTENSION
        or manifest.get("service_id") != "bloom"
        or manifest.get("eligible") is not True
    ):
        raise RuntimeError("Mounted TapDB DAG v2 manifest does not identify Bloom")

    features = manifest.get("features")
    if not isinstance(features, dict):
        raise RuntimeError("Mounted TapDB DAG v2 manifest is missing features")
    endpoints = [
        {
            "path": str(item["path"]),
            "kind": str(item["kind"]),
            "auth": "operator_or_service_token",
        }
        for item in manifest.get("endpoints", [])
        if isinstance(item, dict) and item.get("path") and item.get("kind")
    ]
    return {
        "endpoints": endpoints,
        "extensions": list(advertisement.get("extensions") or []),
        "capabilities": sorted(
            str(name) for name, enabled in features.items() if enabled is True
        ),
        "external_ref_models": [
            "tapdb_object",
            "typed_external_identifier",
        ],
        "contract_version": str(manifest["contract"]),
    }
