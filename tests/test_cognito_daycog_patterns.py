import os

import pytest
from fastapi.testclient import TestClient

from auth.cognito.client import (
    CognitoConfigurationError,
    _DaycogEntry,
    _build_config,
    _select_daycog_entry,
)


# Ensure OAuth is bypassed before importing the FastAPI app for route tests.
os.environ.setdefault("BLOOM_OAUTH", "no")
os.environ.setdefault("BLOOM_DEV_AUTH_BYPASS", "true")

from main import app


def test_build_config_missing_domain_has_daycog_hint():
    values = {
        "COGNITO_USER_POOL_ID": "us-east-1_example",
        "COGNITO_REGION": "us-east-1",
        "COGNITO_APP_CLIENT_ID": "abc123",
        "COGNITO_CALLBACK_URL": "http://localhost:8912/auth/callback",
    }

    with pytest.raises(CognitoConfigurationError) as exc:
        _build_config(values, source_path="/Users/test/.config/daycog/example.us-east-1.env")

    message = str(exc.value)
    assert "COGNITO_DOMAIN" in message
    assert "--attach-domain" in message
    assert "daycog config update" in message


def test_select_daycog_entry_prefers_pool_scoped_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOOM_COGNITO_APP_NAME", raising=False)

    pool_entry = _DaycogEntry(
        path=tmp_path / "example.us-east-1.env",
        values={"COGNITO_CLIENT_NAME": "active-app"},
        app_name="",
    )
    app_entry = _DaycogEntry(
        path=tmp_path / "example.us-east-1.some-app.env",
        values={"COGNITO_CLIENT_NAME": "some-app"},
        app_name="some-app",
    )

    selected = _select_daycog_entry([app_entry, pool_entry])
    assert selected.path == pool_entry.path


def test_select_daycog_entry_respects_bloom_app_name(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOOM_COGNITO_APP_NAME", "bloom-gui")

    pool_entry = _DaycogEntry(
        path=tmp_path / "example.us-east-1.env",
        values={"COGNITO_CLIENT_NAME": "active-app"},
        app_name="",
    )
    app_entry = _DaycogEntry(
        path=tmp_path / "example.us-east-1.bloom-gui.env",
        values={"COGNITO_CLIENT_NAME": "bloom-gui"},
        app_name="bloom-gui",
    )

    selected = _select_daycog_entry([pool_entry, app_entry])
    assert selected.path == app_entry.path


def test_auth_callback_get_alias_matches_oauth_callback():
    client = TestClient(app)

    legacy = client.get("/oauth_callback", follow_redirects=False)
    alias = client.get("/auth/callback", follow_redirects=False)

    assert legacy.status_code == alias.status_code == 303
    assert legacy.headers.get("location") == alias.headers.get("location")
    assert alias.headers.get("location") == "/login?error=no_authorization_code"


def test_auth_callback_post_alias_matches_oauth_callback():
    client = TestClient(app)

    legacy = client.post("/oauth_callback", json={})
    alias = client.post("/auth/callback", json={})

    assert legacy.status_code == alias.status_code == 400
    assert legacy.json() == alias.json()
    assert alias.json()["message"] == "No Cognito tokens provided."
