"""Tests for Bloom-mounted TapDB admin surface."""

from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import bloom_lims.integrations.tapdb_mount as tapdb_mount
from bloom_lims.app import create_app


def _client() -> TestClient:
    os.environ["BLOOM_TAPDB_MOUNT_ENABLED"] = "1"
    os.environ["BLOOM_TAPDB_MOUNT_PATH"] = "/admin/tapdb"
    return TestClient(create_app(), raise_server_exceptions=False)


def test_mounted_route_exists_under_bloom_app():
    with _client() as client:
        response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert response.status_code != 404


def test_unauthenticated_request_redirects_to_bloom_login():
    with _client() as client:
        response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("location") == "/login"

        json_response = client.get(
            "/admin/tapdb/login",
            headers={"accept": "application/json"},
            follow_redirects=False,
        )
        assert json_response.status_code == 401
        assert json_response.json()["detail"] == "Authentication required"


def test_non_admin_authenticated_user_is_denied(monkeypatch):
    monkeypatch.setattr(
        tapdb_mount,
        "_resolve_bloom_user_data",
        lambda _scope: {"email": "user@example.com", "role": "READ_WRITE"},
    )
    with _client() as client:
        response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("location") == "/user_home?admin_required=1"

        json_response = client.get(
            "/admin/tapdb/login",
            headers={"accept": "application/json"},
            follow_redirects=False,
        )
        assert json_response.status_code == 403
        assert json_response.json()["detail"] == "Admin privileges required"


def test_admin_user_can_access_mounted_surface(monkeypatch):
    monkeypatch.setattr(
        tapdb_mount,
        "_resolve_bloom_user_data",
        lambda _scope: {"email": "admin@example.com", "role": "ADMIN"},
    )
    with _client() as client:
        response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert response.status_code in {302, 303}
        assert response.headers.get("location") == "/admin/tapdb/"


def test_tapdb_local_auth_not_required_in_mounted_mode(monkeypatch):
    monkeypatch.setattr(
        tapdb_mount,
        "_resolve_bloom_user_data",
        lambda _scope: {"email": "admin@example.com", "role": "ADMIN"},
    )
    with _client() as client:
        response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert response.status_code in {302, 303}
        assert response.headers.get("location") == "/admin/tapdb/"


def test_bloom_single_app_serves_api_and_tapdb_mount(monkeypatch):
    monkeypatch.setattr(
        tapdb_mount,
        "_resolve_bloom_user_data",
        lambda _scope: {"email": "admin@example.com", "role": "ADMIN"},
    )
    with _client() as client:
        api_response = client.get("/api/v1/")
        tapdb_response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert api_response.status_code == 200
        assert tapdb_response.status_code != 404


def test_app_shutdown_cleanup_runs(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("BLOOM_TAPDB_MOUNT_ENABLED", "0")
    monkeypatch.setattr("bloom_lims.app.stop_all_writers", lambda: calls.append("stop"))

    with TestClient(create_app(), raise_server_exceptions=False):
        pass

    assert calls == ["stop"]


def test_mount_uses_explicit_tapdb_context(monkeypatch):
    captured: dict[str, str] = {}

    tapdb_app = FastAPI()

    @tapdb_app.get("/")
    async def _index():
        return {"tapdb": "ok"}

    monkeypatch.setattr(
        tapdb_mount,
        "apply_runtime_environment",
        lambda: SimpleNamespace(
            env="dev",
            config_path="/tmp/bloom-tapdb-config.yaml",
            client_id="bloom",
            database_name="bloom",
        ),
    )
    monkeypatch.setattr(
        tapdb_mount,
        "_load_tapdb_admin_app",
        lambda **kwargs: (
            captured.update({key: str(value) for key, value in kwargs.items()})
            or tapdb_app
        ),
    )

    config = tapdb_mount.mount_tapdb_admin_subapp(FastAPI())

    assert config is not None
    assert captured == {
        "tapdb_env": "dev",
        "config_path": "/tmp/bloom-tapdb-config.yaml",
        "client_id": "bloom",
        "database_name": "bloom",
    }
