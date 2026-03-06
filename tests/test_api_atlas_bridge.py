"""Tests for manual Atlas bridge API endpoints."""

from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

import bloom_lims.api.v1.atlas_bridge as atlas_bridge_mod
from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.integrations.atlas.service import AtlasDependencyError


os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _external_rw_user() -> APIUser:
    return APIUser(
        email="atlas-bridge@example.com",
        user_id=str(uuid.uuid4()),
        roles=["INTERNAL_READ_WRITE"],
        auth_source="token",
        is_service_account=True,
        token_scope="internal_rw",
        token_id=str(uuid.uuid4()),
    )


def _external_ro_user() -> APIUser:
    return APIUser(
        email="atlas-bridge-ro@example.com",
        user_id=str(uuid.uuid4()),
        roles=["INTERNAL_READ_ONLY"],
        auth_source="token",
        is_service_account=True,
        token_scope="internal_ro",
        token_id=str(uuid.uuid4()),
    )


def _payload() -> dict:
    return {
        "event_id": "bloom-status-evt-0001",
        "status": "IN_PROGRESS",
        "occurred_at": "2026-03-03T01:00:00Z",
        "reason": "Lab processing started",
        "container_euid": "CX-RT",
        "specimen_euid": "MX-B4",
        "metadata": {"source": "bloom", "workflow": "wgs"},
    }


def test_push_test_order_status_event_happy_path(monkeypatch):
    class _FakeAtlasService:
        def push_test_order_status_event(self, *, test_order_id, payload, idempotency_key=None, tenant_id=None):
            assert test_order_id == "8f4ad36e-5f41-4a00-83dd-a2f3afb8f431"
            assert payload["event_id"] == "bloom-status-evt-0001"
            assert idempotency_key == "idem-123"
            assert tenant_id is None
            return type(
                "Result",
                (),
                {
                    "payload": {
                        "applied": True,
                        "idempotent_replay": False,
                        "test_order_id": test_order_id,
                        "test_order_status": "IN_PROGRESS",
                        "order_id": "57bf7f35-2558-4429-b17a-f9ec72dbe45a",
                        "order_number": "ORD-1001",
                        "order_status": "IN_PROGRESS",
                        "status_event_id": "5188fca0-bc37-498e-af31-26a3d11f6648",
                        "order_status_event_id": "5d2f9720-0cb8-4445-9ca9-458f115bc58c",
                    }
                },
            )()

    app.dependency_overrides[require_external_token_auth] = _external_rw_user
    monkeypatch.setattr(atlas_bridge_mod, "AtlasService", _FakeAtlasService)

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/external/atlas/test-orders/8f4ad36e-5f41-4a00-83dd-a2f3afb8f431/status-events",
            headers={"Idempotency-Key": "idem-123"},
            json=_payload(),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] is True
    assert body["test_order_status"] == "IN_PROGRESS"


def test_push_test_order_status_event_requires_token_auth(monkeypatch):
    class _FakeAtlasService:
        def push_test_order_status_event(self, *, test_order_id, payload, idempotency_key=None, tenant_id=None):
            return type("Result", (), {"payload": {}})()

    monkeypatch.setattr(atlas_bridge_mod, "AtlasService", _FakeAtlasService)

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/external/atlas/test-orders/8f4ad36e-5f41-4a00-83dd-a2f3afb8f431/status-events",
            json=_payload(),
        )

    assert response.status_code == 401


def test_push_test_order_status_event_requires_write_permission(monkeypatch):
    class _FakeAtlasService:
        def push_test_order_status_event(self, *, test_order_id, payload, idempotency_key=None, tenant_id=None):
            return type("Result", (), {"payload": {}})()

    app.dependency_overrides[require_external_token_auth] = _external_ro_user
    monkeypatch.setattr(atlas_bridge_mod, "AtlasService", _FakeAtlasService)

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/external/atlas/test-orders/8f4ad36e-5f41-4a00-83dd-a2f3afb8f431/status-events",
            json=_payload(),
        )

    assert response.status_code == 403


def test_push_test_order_status_event_missing_tenant_config_maps_to_424(monkeypatch):
    class _FakeAtlasService:
        def push_test_order_status_event(self, *, test_order_id, payload, idempotency_key=None, tenant_id=None):
            raise AtlasDependencyError("Atlas tenant UUID not configured (atlas.organization_id)")

    app.dependency_overrides[require_external_token_auth] = _external_rw_user
    monkeypatch.setattr(atlas_bridge_mod, "AtlasService", _FakeAtlasService)

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/external/atlas/test-orders/8f4ad36e-5f41-4a00-83dd-a2f3afb8f431/status-events",
            json=_payload(),
        )

    assert response.status_code == 424
    assert "tenant" in response.json()["detail"].lower()
