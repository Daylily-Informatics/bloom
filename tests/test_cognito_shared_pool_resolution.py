from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from auth.cognito.client import CognitoAuth, CognitoConfigurationError

def _auth_settings(**overrides):
    payload = {
        "cognito_user_pool_id": "us-east-1_POOL123",
        "cognito_client_id": "bloom-client",
        "cognito_client_secret": "",
        "cognito_region": "us-east-1",
        "cognito_domain": "bloom.auth.us-east-1.amazoncognito.com",
        "cognito_redirect_uri": "https://localhost:8912/auth/callback",
        "cognito_logout_redirect_uri": "https://localhost:8912/",
        "cognito_scopes": ["openid", "email", "profile"],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_from_settings_uses_yaml_only_configuration():
    auth = CognitoAuth.from_settings(
        _auth_settings(),
        expected_callback_url="https://localhost:8912/auth/callback",
        expected_logout_url="https://localhost:8912/",
    )

    assert auth.config.client_id == "bloom-client"
    assert auth.config.redirect_uri == "https://localhost:8912/auth/callback"
    assert auth.config.logout_redirect_uri == "https://localhost:8912/"
    assert auth.config.domain == "bloom.auth.us-east-1.amazoncognito.com"


def test_authorize_url_uses_authorization_code_flow():
    auth = CognitoAuth.from_settings(_auth_settings())

    parsed = urlparse(auth.config.authorize_url)
    query = parse_qs(parsed.query)

    assert parsed.path == "/oauth2/authorize"
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["https://localhost:8912/auth/callback"]
    assert query["scope"] == ["openid email profile"]


def test_from_settings_rejects_missing_yaml_values():
    with pytest.raises(CognitoConfigurationError) as exc:
        CognitoAuth.from_settings(
            _auth_settings(cognito_client_id=""),
            expected_callback_url="https://localhost:8912/auth/callback",
        )

    assert "Missing Cognito configuration in YAML config" in str(exc.value)
    assert "cognito_client_id" in str(exc.value)


def test_from_settings_flags_runtime_port_mismatch_against_yaml_urls():
    with pytest.raises(CognitoConfigurationError) as exc:
        CognitoAuth.from_settings(
            _auth_settings(),
            expected_callback_url="https://localhost:8915/auth/callback",
            expected_logout_url="https://localhost:8915/",
        )

    assert "port mismatch" in str(exc.value)
