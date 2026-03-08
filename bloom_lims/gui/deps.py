from __future__ import annotations

import os
import socket
import logging
from typing import Dict, List

from fastapi import HTTPException, Request, status

from auth.cognito.client import (
    CognitoAuth,
    CognitoConfigurationError,
    get_cognito_auth,
)

from bloom_lims.gui.errors import AuthenticationRequiredException, MissingCognitoEnvVarsException


DEFAULT_USER_PREFERENCES = {
    "style_css": "/static/modern/css/bloom_modern.css",
}


def get_user_preferences(email: str) -> dict:
    """Get user preferences with defaults. Preferences are stored in session only."""
    return {
        "email": email,
        **DEFAULT_USER_PREFERENCES,
    }


def _get_request_cognito_auth(request: Request) -> CognitoAuth:
    """Resolve Cognito auth with request-origin callback/logout URLs."""
    try:
        from bloom_lims.config import get_settings

        settings = get_settings()
        callback_url = str(request.url_for("auth_callback_get"))
        logout_url = str(request.base_url).rstrip("/") + "/"
        return CognitoAuth.from_settings(
            settings.auth,
            expected_callback_url=callback_url,
            expected_logout_url=logout_url,
        )
    except CognitoConfigurationError:
        raise
    except Exception:
        return get_cognito_auth()


def get_allowed_domains() -> List[str]:
    """Get allowed email domains from YAML config or environment.

    Returns:
        Empty list [] = allow all domains
        List with domains = only those domains allowed
        List with ["__BLOCK_ALL__"] = block all domains (when config is empty)
    """
    try:
        from bloom_lims.config import get_settings

        settings = get_settings()
        domains = settings.auth.cognito_allowed_domains

        # If YAML config has domains, use them
        if domains:
            # ["*"] = allow all
            if domains == ["*"]:
                return []
            return domains

        # Empty list in YAML = block all
        return ["__BLOCK_ALL__"]
    except Exception:
        pass

    whitelist_domains = os.getenv("COGNITO_WHITELIST_DOMAINS", "all")

    # Empty string = block all domains
    if whitelist_domains == "":
        return ["__BLOCK_ALL__"]

    if whitelist_domains.lower() in ("all", "*"):
        return []

    return [domain.strip() for domain in whitelist_domains.split(",") if domain.strip()]


async def require_auth(request: Request):
    """Require authentication for a route.

    In development mode (BLOOM_OAUTH=no), defaults to admin role.
    """

    if os.environ.get("BLOOM_OAUTH", "yes") == "no":
        request.session["user_data"] = {
            "email": "john@daylilyinformatics.com",
            "dag_fnv2": "",
            "role": "admin",
        }
        return request

    try:
        _get_request_cognito_auth(request)
    except CognitoConfigurationError as exc:
        msg = (
            "Cognito configuration missing. Check ~/.config/bloom/bloom-config.yaml "
            f"or BLOOM_AUTH__* env vars. ({exc})"
        )
        logging.error(msg)
        raise MissingCognitoEnvVarsException(msg)

    if "user_data" not in request.session:
        raise AuthenticationRequiredException()

    if "role" not in request.session["user_data"]:
        request.session["user_data"]["role"] = "user"

    return request.session["user_data"]


def _resolve_auth_email(auth: Dict, request: Request) -> str:
    if isinstance(auth, dict) and auth.get("email"):
        return auth["email"]
    return request.session.get("user_data", {}).get("email", "anonymous")


def _resolve_auth_role(auth: Dict, request: Request) -> str:
    if isinstance(auth, dict) and auth.get("role"):
        return str(auth["role"])
    return str(request.session.get("user_data", {}).get("role", "user"))


def _require_graph_admin(auth: Dict, request: Request) -> None:
    role = _resolve_auth_role(auth, request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


def _is_tapdb_reachable(timeout_seconds: float = 0.75) -> bool:
    """Fast TCP reachability check to avoid blocking UI routes on dead DB endpoints."""
    try:
        from bloom_lims.config import get_tapdb_db_config

        cfg = get_tapdb_db_config()
        host = str(cfg.get("host", "")).strip()
        port_raw = cfg.get("port", "")
        port = int(str(port_raw).strip()) if str(port_raw).strip() else 0
        if not host or port <= 0:
            return False

        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False
