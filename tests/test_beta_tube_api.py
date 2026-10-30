"""Bounded API admission contracts; no running application or database required."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bloom_lims.api.v1 import beta_lab
from bloom_lims.api.v1.dependencies import require_external_atlas_api_enabled
from bloom_lims.auth.rbac import Permission


TENANT = "10000000-0000-0000-0000-000000000001"
ROOT = "/external/atlas/beta"


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(beta_lab.router)
    app.dependency_overrides[require_external_atlas_api_enabled] = lambda: SimpleNamespace(
        email="caller@example.invalid", has_permission=lambda permission: True,
    )
    def unexpected_service(**kwargs):
        raise AssertionError("Invalid requests must fail before opening a database adapter")
    monkeypatch.setattr(beta_lab, "BetaLabService", unexpected_service)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("operation", ["tubes", "tubes/register-existing"])
def test_tube_write_requires_idempotency_header(client, operation):
    body = {"container_template_code": "container/tube/tube-generic-10ml/1.0",
            "atlas_context": {"atlas_tenant_id": TENANT}}
    if operation.endswith("register-existing"):
        body["identifier"] = {"tenant_id": TENANT, "namespace": "lab", "kind": "opaque", "value": "external-1"}
    response = client.post(f"{ROOT}/{operation}", json=body)
    assert response.status_code == 422
    assert any(error["loc"] == ["header", "Idempotency-Key"] for error in response.json()["detail"])


def test_create_requires_explicit_exact_template(client):
    response = client.post(f"{ROOT}/tubes", headers={"Idempotency-Key": "request-key"},
                           json={"atlas_context": {"atlas_tenant_id": TENANT}})
    assert response.status_code == 422


@pytest.mark.parametrize("path", ["tube-requests/request-key", "tubes/placeholder/identity"])
def test_identity_and_receipt_reads_require_explicit_registration_tenant(client, path):
    assert client.get(f"{ROOT}/{path}").status_code == 422


def test_identity_read_requires_bloom_read_permission(client):
    client.app.dependency_overrides[require_external_atlas_api_enabled] = lambda: SimpleNamespace(
        email="caller@example.invalid", has_permission=lambda permission: permission == Permission.BLOOM_WRITE,
    )
    response = client.get(f"{ROOT}/tube-requests/request-key", params={"atlas_tenant_id": TENANT})
    assert response.status_code == 403
