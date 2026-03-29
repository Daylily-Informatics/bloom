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

        await self._inner_app(scope, receive, send)


def _load_tapdb_admin_app() -> ASGIApp:
    os.environ["TAPDB_ADMIN_DISABLE_AUTH"] = "1"
    try:
        module = importlib.import_module("admin.main")
    except Exception as exc:  # pragma: no cover - exercised by startup failure paths
        raise RuntimeError("Failed importing TapDB admin FastAPI app") from exc

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
