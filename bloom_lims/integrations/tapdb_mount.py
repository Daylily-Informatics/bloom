"""Bloom embedding surface for TapDB admin sub-application."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from daylily_tapdb.web import TapdbHostBridge, TapdbHostNavLink, create_tapdb_gui_app
from fastapi import FastAPI

from bloom_lims.config import apply_runtime_environment

logger = logging.getLogger(__name__)


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
        mount_path = "/tapdb"
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


def _tapdb_user_from_bloom_user_data(user_data: dict[str, Any]) -> dict[str, Any]:
    email = str(user_data.get("email") or "").strip().lower()
    display_name = str(
        user_data.get("display_name") or user_data.get("name") or email
    ).strip()
    return {
        "uid": 0,
        "username": email,
        "email": email,
        "display_name": display_name or email,
        "role": "admin" if _is_admin_user(user_data) else "user",
        "is_active": True,
        "require_password_change": False,
    }


def _request_next_path(request: Any) -> str:
    next_path = str(request.url.path or "/")
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return next_path


def _tapdb_host_user(request: Any) -> dict[str, Any] | None:
    user_data = _resolve_bloom_user_data(request.scope)
    if user_data is None:
        return None
    return _tapdb_user_from_bloom_user_data(user_data)


def _build_tapdb_host_bridge() -> TapdbHostBridge:
    return TapdbHostBridge(
        auth_mode="host_session",
        service_name="bloom",
        app_name="Bloom",
        shell_title="Bloom",
        shell_subtitle="TapDB substrate",
        home_url="/",
        login_url=lambda request: f"/login?next={quote(_request_next_path(request), safe='/')}",
        logout_url="/logout",
        change_password_url=None,
        resolve_user=_tapdb_host_user,
        nav_links=(
            TapdbHostNavLink(label="Dashboard", href="/"),
            TapdbHostNavLink(label="Queue", href="/queue"),
            TapdbHostNavLink(label="Graph", href="/graph"),
            TapdbHostNavLink(label="Admin", href="/admin"),
        ),
        extra_stylesheets=("/static/modern/css/bloom_modern.css",),
        extra_context=lambda _request: {"bloom_embedded": True},
    )


def _load_tapdb_admin_app(
    *,
    config_path: str,
    client_id: str,
    database_name: str,
):
    if not str(config_path or "").strip():
        raise RuntimeError("TapDB admin mount requires an explicit tapdb_config_path.")
    candidate_config_path = Path(config_path).expanduser()
    if not candidate_config_path.is_absolute():
        raise RuntimeError("TapDB admin mount requires an absolute tapdb_config_path.")
    resolved_config_path = candidate_config_path.resolve()
    _ = client_id, database_name
    return create_tapdb_gui_app(
        config_path=str(resolved_config_path),
        host_bridge=_build_tapdb_host_bridge(),
    )


def mount_tapdb_admin_subapp(app: FastAPI) -> TapDBMountConfig | None:
    config = load_tapdb_mount_config()
    if not config.enabled:
        logger.info("TapDB mount disabled by BLOOM_TAPDB_MOUNT_ENABLED=0")
        return None

    runtime_ctx = apply_runtime_environment()
    try:
        tapdb_admin_app = _load_tapdb_admin_app(
            config_path=runtime_ctx.config_path,
            client_id=runtime_ctx.client_id,
            database_name=runtime_ctx.database_name,
        )
    except Exception as exc:
        raise RuntimeError(
            "Bloom startup aborted: TapDB mount is enabled but TapDB admin app failed to load"
        ) from exc

    app.mount(config.mount_path, tapdb_admin_app, name="tapdb_gui")
    logger.info("Mounted TapDB GUI app at %s", config.mount_path)
    return config
