"""Canonical TapDB DAG API integration for Bloom."""

from __future__ import annotations

from typing import Any

from daylily_tapdb.web import (
    build_dag_capability_advertisement,
    create_tapdb_dag_router,
)
from fastapi import Depends, FastAPI

from bloom_lims.api.v1.dependencies import require_api_auth
from bloom_lims.config import apply_runtime_environment


def mount_tapdb_dag_api(app: FastAPI) -> None:
    """Mount the canonical `/api/dag/*` TapDB router with Bloom API auth."""

    runtime_ctx = apply_runtime_environment()
    app.include_router(
        create_tapdb_dag_router(
            config_path=runtime_ctx.config_path,
            service_name="bloom",
        ),
        dependencies=[Depends(require_api_auth)],
    )


def bloom_tapdb_dag_obs_services_fragment() -> dict[str, Any]:
    """Return Bloom-facing obs_services metadata for the TapDB DAG contract."""

    return build_dag_capability_advertisement(
        base_path="/api/dag",
        auth="operator_or_service_token",
    )
