"""TAPDB admin auth disable-flag behavior tests."""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient


os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


def test_tapdb_login_requires_auth_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TAPDB_ADMIN_DISABLE_AUTH", raising=False)
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)

    response = client.get("/tapdb/login", follow_redirects=False)

    assert response.status_code == 200


def test_tapdb_login_redirects_when_auth_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TAPDB_ADMIN_DISABLE_AUTH", "true")
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)

    response = client.get("/tapdb/login", follow_redirects=False)

    assert response.status_code in {301, 302, 303, 307, 308}
    assert response.headers.get("location") == "/tapdb/"
