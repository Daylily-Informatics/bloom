from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
os.environ["BLOOM_OAUTH"] = "no"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app
from bloom_lims.observability import EndpointRollup, ProjectionMetadata, _percentile


DAYHOFF_SCHEMA_ROOT = Path("/Users/jmajor/.codex/worktrees/cbc5/dayhoff/contracts/observability")


def _load_schema(name: str) -> dict:
    return json.loads((DAYHOFF_SCHEMA_ROOT / name).read_text())


def _assert_required_shape(payload: dict, schema: dict) -> None:
    for key in schema.get("required", []):
        assert key in payload, f"missing required key {key}"
    projection_schema = schema.get("properties", {}).get("projection")
    if projection_schema and "projection" in payload:
        for key in projection_schema.get("required", []):
            assert key in payload["projection"], f"missing projection key {key}"


def test_observability_contract_endpoints_match_shared_frame() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/healthz")
        client.get("/readyz")
        client.get("/obs_services")

        schema_map = {
            "/health": "health.schema.json",
            "/obs_services": "obs_services.schema.json",
            "/api_health": "api_health.schema.json",
            "/endpoint_health": "endpoint_health.schema.json",
            "/db_health": "db_health.schema.json",
            "/auth_health": "auth_health.schema.json",
            "/my_health": "my_health.schema.json",
        }

        for path, schema_name in schema_map.items():
            response = client.get(path)
            assert response.status_code == 200, f"{path} returned {response.status_code}"
            payload = response.json()
            _assert_required_shape(payload, _load_schema(schema_name))
            assert payload["service"] == "bloom"
            assert payload["contract_version"] == "v3"


def test_obs_services_uses_canonical_capability_vocabulary() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/obs_services")

    assert response.status_code == 200
    advertised = {
        item["path"]: {"auth": item["auth"], "kind": item["kind"]}
        for item in response.json()["endpoints"]
    }
    assert advertised == {
        "/healthz": {"auth": "none", "kind": "liveness"},
        "/readyz": {"auth": "none", "kind": "readiness"},
        "/health": {"auth": "operator_or_service_token", "kind": "summary"},
        "/obs_services": {"auth": "operator_or_service_token", "kind": "discovery"},
        "/api_health": {"auth": "operator_or_service_token", "kind": "api_rollup"},
        "/endpoint_health": {"auth": "operator_or_service_token", "kind": "endpoint_rollup"},
        "/db_health": {"auth": "operator_or_service_token", "kind": "database"},
        "/api/anomalies": {"auth": "operator_or_service_token", "kind": "anomaly_list"},
        "/api/anomalies/{anomaly_id}": {"auth": "operator_or_service_token", "kind": "anomaly_detail"},
        "/my_health": {"auth": "authenticated_self", "kind": "self"},
        "/auth_health": {"auth": "operator_or_service_token", "kind": "auth"},
    }
    assert "bloom.anomalies_v1" in response.json()["extensions"]


def test_endpoint_health_uses_route_templates_not_raw_instances() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/api/v1/objects/NONEXISTENT_EUID")
        response = client.get("/endpoint_health")

    assert response.status_code == 200
    route_templates = {item["route_template"] for item in response.json()["items"]}
    assert "/api/v1/objects/{euid}" in route_templates
    assert all("NONEXISTENT_EUID" not in item for item in route_templates)


def test_admin_observability_page_renders() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/admin/observability")

    assert response.status_code == 200
    assert "Observability" in response.text
    assert "/endpoint_health" in response.text


def test_observability_helpers_cover_empty_rollups_and_db_fallback(monkeypatch) -> None:
    assert _percentile([], 0.95) == 0.0

    rollup = EndpointRollup(method="GET", route_template="/api/v1/health")
    rollup.record(status_code=200, duration_ms=12.5, fingerprint="")
    payload = rollup.to_dict()
    assert payload["fingerprint_count"] == 0
    assert payload["request_count"] == 1

    with TestClient(app, raise_server_exceptions=False) as client:
        async def _fake_check_database_health():
            return SimpleNamespace(
                status="healthy",
                latency_ms=4.2,
                message="ok",
                details={},
            )

        monkeypatch.setattr(
            "bloom_lims.observability_routes.check_database_health",
            _fake_check_database_health,
        )
        monkeypatch.setattr(
            app.state.observability,
            "db_health",
            lambda: (
                ProjectionMetadata(),
                {"status": "ok", "latest": None, "observed_at": None},
            ),
        )

        response = client.get("/db_health")

    assert response.status_code == 200
    assert response.json()["database"]["observed_at"] is None
