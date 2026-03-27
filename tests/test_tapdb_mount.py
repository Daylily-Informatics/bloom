"""Tests for Bloom-mounted TapDB admin surface."""

from __future__ import annotations

import os

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
        lambda _scope: {"email": "user@example.com", "role": "user"},
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
        lambda _scope: {"email": "admin@example.com", "role": "admin"},
    )
    with _client() as client:
        response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert response.status_code in {302, 303}
        assert response.headers.get("location") == "/admin/tapdb/"


def test_tapdb_local_auth_not_required_in_mounted_mode(monkeypatch):
    monkeypatch.setattr(
        tapdb_mount,
        "_resolve_bloom_user_data",
        lambda _scope: {"email": "admin@example.com", "role": "admin"},
    )
    with _client() as client:
        response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert response.status_code in {302, 303}
        assert response.headers.get("location") == "/admin/tapdb/"


def test_bloom_single_app_serves_api_and_tapdb_mount(monkeypatch):
    monkeypatch.setattr(
        tapdb_mount,
        "_resolve_bloom_user_data",
        lambda _scope: {"email": "admin@example.com", "role": "admin"},
    )
    with _client() as client:
        api_response = client.get("/api/v1/")
        tapdb_response = client.get("/admin/tapdb/login", follow_redirects=False)
        assert api_response.status_code == 200
        assert tapdb_response.status_code != 404

