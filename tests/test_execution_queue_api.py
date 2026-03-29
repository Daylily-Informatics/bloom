"""Direct API coverage for the execution queue router."""

from __future__ import annotations

import os
import secrets
import sys

import pytest
from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, require_api_auth

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _opaque(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _internal_rw_user() -> APIUser:
    return APIUser(
        email="execution-api@example.com",
        user_id=_opaque("user"),
        roles=["READ_WRITE"],
        auth_source="token",
        token_scope="internal_rw",
        token_id=_opaque("token"),
    )


def _internal_ro_user() -> APIUser:
    return APIUser(
        email="execution-api-ro@example.com",
        user_id=_opaque("user"),
        roles=["READ_ONLY"],
        auth_source="token",
        token_scope="internal_ro",
        token_id=_opaque("token"),
    )


def test_execution_queue_router_lists_queues_and_registers_worker():
    app.dependency_overrides[require_api_auth] = _internal_rw_user
    worker_key = f"worker://pytest/{_opaque('worker')}"

    with TestClient(app) as client:
        queues = client.get("/api/v1/execution/queues")
        assert queues.status_code == 200, queues.text
        queue_keys = {item["queue_key"] for item in queues.json()}
        assert "extraction_prod" in queue_keys

        registered = client.post(
            "/api/v1/execution/actions/register-worker",
            json={
                "worker_key": worker_key,
                "display_name": "Pytest Execution Worker",
                "worker_type": "SERVICE",
                "status": "ONLINE",
                "capabilities": ["wetlab.extraction"],
                "max_concurrent_leases": 2,
                "heartbeat_ttl_seconds": 120,
            },
        )
        assert registered.status_code == 200, registered.text
        worker = registered.json()
        assert worker["worker_key"] == worker_key
        assert worker["capabilities"] == ["wetlab.extraction"]
        assert worker["max_concurrent_leases"] == 2

        workers = client.get("/api/v1/execution/workers")
        assert workers.status_code == 200, workers.text
        worker_keys = {item["worker_key"] for item in workers.json()}
        assert worker_key in worker_keys


def test_execution_queue_router_register_worker_requires_write_permission():
    app.dependency_overrides[require_api_auth] = _internal_ro_user

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/execution/actions/register-worker",
            json={
                "worker_key": f"worker://pytest/{_opaque('worker')}",
                "display_name": "Read Only Worker",
                "worker_type": "SERVICE",
                "status": "ONLINE",
            },
        )

    assert response.status_code == 403
    assert "Write permission required" in response.text


def test_execution_queue_router_maps_missing_queue_to_404():
    app.dependency_overrides[require_api_auth] = _internal_rw_user

    with TestClient(app) as client:
        response = client.get(f"/api/v1/execution/queues/{_opaque('missing-queue')}")

    assert response.status_code == 404
    assert "Queue not found" in response.text
