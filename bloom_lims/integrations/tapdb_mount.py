"""Bloom embedding surface for TapDB admin sub-application."""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)
_BLOOM_TAPDB_SCOPE_USER_KEY = "bloom_tapdb_user"

ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]


@dataclass(frozen=True)
class TapDBMountConfig:
    enabled: bool
    mount_path: str


def _is_truthy(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    lowered = str(raw).strip().lower()
    if not lowered:
        return default
    return lowered in {"1", "true", "yes", "on"}


def _normalize_mount_path(raw_path: str | None) -> str:
    mount_path = str(raw_path or "").strip()
    if not mount_path:
        mount_path = "/admin/tapdb"
    if not mount_path.startswith("/"):
        mount_path = f"/{mount_path}"
    if len(mount_path) > 1:
        mount_path = mount_path.rstrip("/")
    if mount_path == "/":
        raise ValueError("BLOOM_TAPDB_MOUNT_PATH must not be root '/'")
    return mount_path


def load_tapdb_mount_config() -> TapDBMountConfig:
    enabled = _is_truthy(os.environ.get("BLOOM_TAPDB_MOUNT_ENABLED"), default=True)
    mount_path = _normalize_mount_path(os.environ.get("BLOOM_TAPDB_MOUNT_PATH"))
    return TapDBMountConfig(enabled=enabled, mount_path=mount_path)


def _prefers_json(scope: dict[str, Any]) -> bool:
    headers = Headers(scope=scope)
    accept = str(headers.get("accept") or "").lower()
    return "application/json" in accept


def _resolve_bloom_user_data(scope: dict[str, Any]) -> dict[str, Any] | None:
    session = scope.get("session")
    if not isinstance(session, dict):
        return None
    user_data = session.get("user_data")
    if not isinstance(user_data, dict):
        return None
    email = str(user_data.get("email") or "").strip()
    if not email:
        return None
    return user_data


def _is_admin_user(user_data: dict[str, Any]) -> bool:
    role = str(user_data.get("role") or "").strip().upper()
    if role == "ADMIN":
        return True
    roles = user_data.get("roles")
    if not isinstance(roles, list):
        return False
    return any(str(item).strip().upper() == "ADMIN" for item in roles)


def _tapdb_admin_user_from_bloom_user_data(user_data: dict[str, Any]) -> dict[str, Any]:
    email = str(user_data.get("email") or "").strip().lower()
    display_name = str(user_data.get("display_name") or user_data.get("name") or email).strip()
    return {
        "uid": 0,
        "username": email,
        "email": email,
        "display_name": display_name or email,
        "role": "admin" if _is_admin_user(user_data) else "user",
        "is_active": True,
        "require_password_change": False,
    }


def _configure_embedded_tapdb_auth(admin_main_module: Any, admin_auth_module: Any) -> None:
    if getattr(admin_main_module, "_bloom_embedded_auth_configured", False):
        return

    async def _get_current_user(request: Any) -> dict[str, Any] | None:
        user = request.scope.get(_BLOOM_TAPDB_SCOPE_USER_KEY)
        if isinstance(user, dict) and str(user.get("email") or "").strip():
            return user
        return None

    admin_auth_module.get_current_user = _get_current_user
    admin_main_module.get_current_user = _get_current_user
    setattr(admin_main_module, "_bloom_embedded_auth_configured", True)


class BloomAdminGuardedASGI:
    """ASGI guard that enforces Bloom admin checks before forwarding."""

    def __init__(self, inner_app: ASGIApp):
        self._inner_app = inner_app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if scope.get("type") != "http":
            await self._inner_app(scope, receive, send)
            return

        user_data = _resolve_bloom_user_data(scope)
        if user_data is None:
            if _prefers_json(scope):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                )
            else:
                response = RedirectResponse(url="/login", status_code=303)
            await response(scope, receive, send)
            return

        if not _is_admin_user(user_data):
            if _prefers_json(scope):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Admin privileges required"},
                )
            else:
                response = RedirectResponse(url="/user_home?admin_required=1", status_code=303)
            await response(scope, receive, send)
            return

        forward_scope = dict(scope)
        forward_scope[_BLOOM_TAPDB_SCOPE_USER_KEY] = _tapdb_admin_user_from_bloom_user_data(
            user_data
        )
        await self._inner_app(forward_scope, receive, send)


def _load_tapdb_admin_app() -> ASGIApp:
    try:
        module = importlib.import_module("admin.main")
        auth_module = importlib.import_module("admin.auth")
    except Exception as exc:  # pragma: no cover - exercised by startup failure paths
        raise RuntimeError("Failed importing TapDB admin FastAPI app") from exc

    _configure_embedded_tapdb_auth(module, auth_module)
    tapdb_admin_app = getattr(module, "app", None)
    if tapdb_admin_app is None:
        raise RuntimeError("TapDB admin module does not expose FastAPI app")
    if not callable(tapdb_admin_app):
        raise RuntimeError("TapDB admin app is not callable as ASGI application")
    return tapdb_admin_app


def mount_tapdb_admin_subapp(app: FastAPI) -> TapDBMountConfig | None:
    config = load_tapdb_mount_config()
    if not config.enabled:
        logger.info("TapDB mount disabled by BLOOM_TAPDB_MOUNT_ENABLED=0")
        return None

    try:
        tapdb_admin_app = _load_tapdb_admin_app()
    except Exception as exc:
        raise RuntimeError(
            "Bloom startup aborted: TapDB mount is enabled but TapDB admin app failed to load"
        ) from exc

    app.mount(config.mount_path, BloomAdminGuardedASGI(tapdb_admin_app), name="tapdb_admin")
    logger.info("Mounted TapDB admin app at %s", config.mount_path)
    return config
