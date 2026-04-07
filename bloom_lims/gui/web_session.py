from __future__ import annotations

import os
import secrets
from typing import Any
from urllib.parse import urlparse

from daylily_auth_cognito.browser.session import (
    CognitoWebSessionConfig,
    SessionPrincipal,
    clear_session_principal,
    configure_session_middleware,
    load_session_principal,
    store_session_principal,
)
from fastapi import FastAPI, Request

from bloom_lims.config import get_settings

_SERVER_INSTANCE_ID = secrets.token_urlsafe(16)
_SESSION_SECRET_FALLBACK = secrets.token_urlsafe(32)


def get_server_instance_id() -> str:
    return _SERVER_INSTANCE_ID


def setup_bloom_session_middleware(app: FastAPI) -> None:
    configure_session_middleware(app, build_bloom_web_session_config())


def build_bloom_web_session_config(
    request: Request | None = None,
) -> CognitoWebSessionConfig:
    settings = get_settings()
    auth_settings = settings.auth
    public_base_url = _origin(auth_settings.cognito_redirect_uri or "https://localhost:8912")
    explicit_secret = str(os.environ.get("BLOOM_SESSION_SECRET") or "").strip()
    base_secret = (
        explicit_secret
        or auth_settings.jwt_secret
        or auth_settings.cognito_client_secret
        or _SESSION_SECRET_FALLBACK
    )
    scopes = auth_settings.cognito_scopes or ["openid", "email", "profile"]

    return CognitoWebSessionConfig(
        domain=auth_settings.cognito_domain,
        client_id=auth_settings.cognito_client_id,
        redirect_uri=auth_settings.cognito_redirect_uri,
        logout_uri=auth_settings.cognito_logout_redirect_uri or f"{public_base_url}/auth/logout",
        public_base_url=public_base_url,
        session_secret_key=base_secret,
        session_cookie_name="bloom_session",
        session_max_age=max(int(auth_settings.session_timeout_minutes or 30) * 60, 300),
        client_secret=auth_settings.cognito_client_secret or None,
        scope=" ".join(scopes),
        allow_insecure_http=public_base_url.startswith("http://"),
        server_instance_id=get_server_instance_id(),
    )


def store_bloom_session(
    request: Request,
    principal: SessionPrincipal,
    *,
    user_data: dict[str, Any],
) -> SessionPrincipal:
    config = build_bloom_web_session_config(request)
    stored = store_session_principal(request, config, principal)
    request.session["user_data"] = _normalize_user_data(dict(user_data), stored)
    return stored


def load_bloom_user_data(request: Request) -> dict[str, Any] | None:
    try:
        principal = load_session_principal(request)
    except RuntimeError:
        principal = None
    if principal is None:
        request.session.pop("user_data", None)
        return None

    user_data = request.session.get("user_data")
    if isinstance(user_data, dict):
        normalized = _normalize_user_data(dict(user_data), principal)
        request.session["user_data"] = normalized
        return normalized

    normalized = _user_data_from_principal(principal)
    request.session["user_data"] = normalized
    return normalized


def clear_bloom_session(request: Request) -> None:
    clear_session_principal(request)
    request.session.pop("_cognito_oauth_state", None)
    request.session.pop("_cognito_post_auth_redirect", None)
    request.session.pop("user_data", None)
    request.session.pop("bloom_post_auth_redirect", None)


def _user_data_from_principal(principal: SessionPrincipal) -> dict[str, Any]:
    app_context = (
        principal.app_context if isinstance(principal.app_context, dict) else {}
    )
    user_data = app_context.get("user_data")
    if not isinstance(user_data, dict):
        user_data = {}
    return _normalize_user_data(dict(user_data), principal)


def _normalize_user_data(
    user_data: dict[str, Any], principal: SessionPrincipal
) -> dict[str, Any]:
    normalized = dict(user_data)
    normalized.pop("access_token", None)
    normalized.pop("id_token", None)
    normalized.pop("refresh_token", None)
    normalized["email"] = str(normalized.get("email") or principal.email)
    normalized["name"] = normalized.get("name") or principal.name or normalized["email"]
    normalized["sub"] = str(normalized.get("sub") or principal.user_sub)
    normalized["cognito_sub"] = str(normalized.get("cognito_sub") or principal.user_sub)
    normalized["user_id"] = str(normalized.get("user_id") or normalized["sub"])
    normalized["roles"] = list(normalized.get("roles") or principal.roles or [])
    if normalized["roles"]:
        normalized["role"] = str(
            normalized.get("role") or normalized["roles"][0]
        ).upper()
        normalized["roles"] = [
            str(role).upper() for role in normalized["roles"] if str(role).strip()
        ]
    else:
        normalized["role"] = str(normalized.get("role") or "READ_WRITE").upper()
        normalized["roles"] = [normalized["role"]]
    normalized["identity_groups"] = list(
        normalized.get("identity_groups")
        or normalized.get("cognito_groups")
        or principal.cognito_groups
        or []
    )
    normalized["cognito_groups"] = list(normalized["identity_groups"])
    normalized["service_groups"] = list(
        normalized.get("service_groups") or normalized.get("groups") or []
    )
    normalized["groups"] = list(normalized["service_groups"])
    return normalized


def _origin(url: str) -> str:
    parsed = urlparse((url or "").strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or "localhost:8912"
    return f"{scheme}://{netloc}"
