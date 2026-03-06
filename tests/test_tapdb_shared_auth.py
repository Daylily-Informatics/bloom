"""TAPDB shared-auth bridge behavior tests."""

from __future__ import annotations

import json
import os
import sys
from base64 import b64encode

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner


os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


def _signed_bloom_session(payload: dict, *, secret: str = "your-secret-key") -> str:
    raw = b64encode(json.dumps(payload).encode("utf-8"))
    return TimestampSigner(secret).sign(raw).decode("utf-8")


def test_tapdb_shared_auth_redirects_from_login(monkeypatch) -> None:
    monkeypatch.setenv("TAPDB_ADMIN_SHARED_AUTH", "true")
    monkeypatch.delenv("TAPDB_ADMIN_DISABLE_AUTH", raising=False)
    monkeypatch.setattr(
        "admin.auth.get_user_by_username",
        lambda _email: {
            "uuid": 1001,
            "email": "alice@example.com",
            "username": "alice@example.com",
            "role": "admin",
            "require_password_change": False,
        },
    )

    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    client.cookies.set(
        "session",
        _signed_bloom_session({"user_data": {"email": "alice@example.com", "role": "admin"}}),
    )

    response = client.get("/tapdb/login", follow_redirects=False)

    assert response.status_code in {301, 302, 303, 307, 308}
    assert response.headers.get("location") == "/tapdb/"


def test_tapdb_shared_auth_falls_back_to_login_without_bloom_session(monkeypatch) -> None:
    monkeypatch.setenv("TAPDB_ADMIN_SHARED_AUTH", "true")
    monkeypatch.delenv("TAPDB_ADMIN_DISABLE_AUTH", raising=False)

    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    response = client.get("/tapdb/login", follow_redirects=False)

    assert response.status_code == 200
