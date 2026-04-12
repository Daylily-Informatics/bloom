"""FastAPI application factory for BLOOM.

This keeps `main.py` as a thin entrypoint while preserving `uvicorn main:app`.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bloom_lims.api import RateLimitMiddleware, api_v1_router
from bloom_lims import __version__
from bloom_lims.config import atlas_webhook_secret_warning, get_settings
from bloom_lims.domain_access import (
    build_allowed_origin_regex,
    build_trusted_hosts,
    is_allowed_origin,
)
from bloom_lims.gui.errors import register_exception_handlers
from bloom_lims.gui.jinja import refresh_template_globals
from bloom_lims.gui.web_session import setup_bloom_session_middleware
from bloom_lims.health import health_router, probe_router
from bloom_lims.integrations.tapdb_mount import mount_tapdb_admin_subapp
from bloom_lims.observability import BloomObservabilityStore
from bloom_lims.observability_routes import router as observability_router
from bloom_lims.tapdb_metrics import (
    request_method_var,
    request_path_var,
    stop_all_writers,
)


def _validate_required_config(settings) -> None:
    """Fail hard at startup if critical configuration is missing.

    Bypass with BLOOM_SKIP_STARTUP_VALIDATION=1 (tests only).
    """
    if os.environ.get("BLOOM_SKIP_STARTUP_VALIDATION", "").strip() in ("1", "true", "yes"):
        logging.getLogger(__name__).warning(
            "Startup config validation skipped (BLOOM_SKIP_STARTUP_VALIDATION)"
        )
        return

    errors: list[str] = []

    # TapDB config must be resolvable
    try:
        from bloom_lims.config import get_tapdb_db_config

        get_tapdb_db_config()
    except Exception as exc:
        errors.append(f"TapDB config: {exc}")

    # Cognito auth must be configured
    auth = settings.auth
    if not auth.cognito_user_pool_id:
        errors.append("auth.cognito_user_pool_id is empty")
    if not auth.cognito_client_id:
        errors.append("auth.cognito_client_id is empty")
    if not auth.cognito_domain:
        errors.append("auth.cognito_domain is empty")
    if not auth.cognito_redirect_uri:
        errors.append("auth.cognito_redirect_uri is empty")

    if errors:
        msg = "BLOOM startup aborted — missing required configuration:\n" + "\n".join(
            f"  • {e}" for e in errors
        )
        raise RuntimeError(msg)


def create_app() -> FastAPI:
    settings = get_settings()
    _validate_required_config(settings)
    atlas_secret_warning = atlas_webhook_secret_warning(settings)
    if atlas_secret_warning:
        logging.getLogger(__name__).warning(atlas_secret_warning)
    allow_local_domain_access = not settings.is_production

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        try:
            yield
        finally:
            # Best-effort shutdown to flush/stop metrics writer.
            stop_all_writers()

    app = FastAPI(lifespan=_lifespan, version=__version__)
    app.state.observability = BloomObservabilityStore()
    refresh_template_globals()

    @app.middleware("http")
    async def _observability_request_context(request, call_next):
        request.state.request_id = request.headers.get("x-request-id", str(uuid4()))
        request.state.correlation_id = request.headers.get("x-correlation-id", request.state.request_id)
        started = monotonic()
        try:
            response = await call_next(request)
        except Exception:
            route = request.scope.get("route")
            route_template = getattr(route, "path", "")
            if route_template:
                app.state.observability.record_http_request(
                    method=request.method,
                    route_template=route_template,
                    status_code=500,
                    duration_ms=(monotonic() - started) * 1000,
                )
            raise
        route = request.scope.get("route")
        route_template = getattr(route, "path", "")
        if route_template:
            app.state.observability.record_http_request(
                method=request.method,
                route_template=route_template,
                status_code=response.status_code,
                duration_ms=(monotonic() - started) * 1000,
            )
        return response

    # Request attribution context for TapDB-style DB metrics.
    @app.middleware("http")
    async def _metrics_request_context(request, call_next):
        token_path = request_path_var.set(request.url.path)
        token_method = request_method_var.set(request.method)
        try:
            return await call_next(request)
        finally:
            request_path_var.reset(token_path)
            request_method_var.reset(token_method)

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.mount("/templates", StaticFiles(directory="templates"), name="templates")

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=build_trusted_hosts(allow_local=allow_local_domain_access),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=build_allowed_origin_regex(
            allow_local=allow_local_domain_access
        ),
        allow_credentials=settings.api.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _enforce_origin_allowlist(request, call_next):
        origin = request.headers.get("origin")
        if origin and not is_allowed_origin(origin, allow_local=allow_local_domain_access):
            return PlainTextResponse("Origin not allowed", status_code=403)
        return await call_next(request)

    setup_bloom_session_middleware(app)

    mount_tapdb_admin_subapp(app)

    # Add rate limiting middleware for API endpoints (disable with BLOOM_RATE_LIMIT=no)
    if os.environ.get("BLOOM_RATE_LIMIT", "yes").lower() != "no":
        app.add_middleware(RateLimitMiddleware)

    # Include routers
    app.include_router(health_router)
    app.include_router(probe_router)
    app.include_router(observability_router)
    app.include_router(api_v1_router)
    try:
        from bloom_lims.gui.router import router as gui_router
    except ModuleNotFoundError as exc:
        logging.warning("Skipping GUI router due to missing optional dependency: %s", exc.name)
    else:
        app.include_router(gui_router)

    register_exception_handlers(app)
    return app
