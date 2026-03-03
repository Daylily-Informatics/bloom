from pathlib import Path
from types import SimpleNamespace

import pytest

from auth.cognito.client import CognitoAuth
from auth.cognito.client import CognitoConfigurationError


def _write_daycog_env(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _auth_settings(pool_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        cognito_user_pool_id=pool_id,
        cognito_client_id="",
        cognito_client_secret="",
        cognito_region="",
        cognito_domain="",
        cognito_redirect_uri="",
        cognito_logout_redirect_uri="",
        cognito_scopes=["openid", "email", "profile"],
    )


def test_from_settings_prefers_daycog_entry_matching_expected_callback(monkeypatch, tmp_path):
    home = tmp_path
    daycog_dir = home / ".config" / "daycog"
    daycog_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    pool_id = "us-east-1_POOL123"
    _write_daycog_env(
        daycog_dir / "default.env",
        {
            "COGNITO_USER_POOL_ID": pool_id,
            "COGNITO_REGION": "us-east-1",
            "COGNITO_APP_CLIENT_ID": "atlas-client",
            "COGNITO_CLIENT_NAME": "atlas",
            "COGNITO_CALLBACK_URL": "https://localhost:8915/auth/callback",
            "COGNITO_LOGOUT_URL": "https://localhost:8915/",
            "COGNITO_DOMAIN": "atlas.auth.us-east-1.amazoncognito.com",
        },
    )
    _write_daycog_env(
        daycog_dir / "bloom.us-east-1.client.env",
        {
            "COGNITO_USER_POOL_ID": pool_id,
            "COGNITO_REGION": "us-east-1",
            "COGNITO_APP_CLIENT_ID": "bloom-client",
            "COGNITO_CLIENT_NAME": "bloom",
            "COGNITO_CALLBACK_URL": "https://localhost:8912/auth/callback",
            "COGNITO_LOGOUT_URL": "https://localhost:8912/",
            "COGNITO_DOMAIN": "bloom.auth.us-east-1.amazoncognito.com",
        },
    )

    auth = CognitoAuth.from_settings(
        _auth_settings(pool_id),
        expected_callback_url="https://localhost:8912/auth/callback",
        expected_logout_url="https://localhost:8912/",
    )

    assert auth.config.client_id == "bloom-client"
    assert auth.config.redirect_uri == "https://localhost:8912/auth/callback"
    assert auth.config.logout_redirect_uri == "https://localhost:8912/"


def test_from_settings_uses_request_callback_even_without_exact_daycog_match(monkeypatch, tmp_path):
    home = tmp_path
    daycog_dir = home / ".config" / "daycog"
    daycog_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    pool_id = "us-east-1_POOL456"
    _write_daycog_env(
        daycog_dir / "atlas.us-east-1.client.env",
        {
            "COGNITO_USER_POOL_ID": pool_id,
            "COGNITO_REGION": "us-east-1",
            "COGNITO_APP_CLIENT_ID": "atlas-client",
            "COGNITO_CLIENT_NAME": "atlas",
            "COGNITO_CALLBACK_URL": "https://localhost:8915/auth/callback",
            "COGNITO_LOGOUT_URL": "https://localhost:8915/",
            "COGNITO_DOMAIN": "atlas.auth.us-east-1.amazoncognito.com",
        },
    )

    with pytest.raises(CognitoConfigurationError) as exc:
        CognitoAuth.from_settings(
            _auth_settings(pool_id),
            expected_callback_url="https://localhost:8912/auth/callback",
            expected_logout_url="https://localhost:8912/",
        )

    assert "client name mismatch" in str(exc.value)
    assert "atlas" in str(exc.value)
    assert "bloom" in str(exc.value)
