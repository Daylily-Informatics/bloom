from types import SimpleNamespace

import pytest

from auth.cognito.client import CognitoAuth
from auth.cognito.client import CognitoConfigurationError


def _auth_settings() -> SimpleNamespace:
    return SimpleNamespace(
        cognito_user_pool_id="us-east-1_POOL123",
        cognito_client_id="bloom-client",
        cognito_client_secret="",
        cognito_region="us-east-1",
        cognito_domain="bloom.auth.us-east-1.amazoncognito.com",
        cognito_redirect_uri="https://localhost:8912/auth/callback",
        cognito_logout_redirect_uri="https://localhost:8912/",
        cognito_scopes=["openid", "email", "profile"],
    )


def test_from_settings_uses_explicit_yaml_fields():
    auth = CognitoAuth.from_settings(_auth_settings())

    assert auth.config.client_id == "bloom-client"
    assert auth.config.redirect_uri == "https://localhost:8912/auth/callback"
    assert auth.config.logout_redirect_uri == "https://localhost:8912/"


def test_from_settings_requires_complete_yaml_fields():
    settings = _auth_settings()
    settings.cognito_client_id = ""

    with pytest.raises(CognitoConfigurationError) as exc:
        CognitoAuth.from_settings(settings)

    assert "cognito_client_id" in str(exc.value)
