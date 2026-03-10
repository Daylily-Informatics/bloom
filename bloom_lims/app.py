"""FastAPI application factory for BLOOM.

This keeps `main.py` as a thin entrypoint while preserving `uvicorn main:app`.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bloom_lims.api import RateLimitMiddleware, api_v1_router
from bloom_lims.config import get_settings
from bloom_lims.domain_access import (
    build_allowed_origin_regex,
    build_trusted_hosts,
    is_allowed_origin,
)
from bloom_lims.gui.errors import register_exception_handlers
from bloom_lims.integrations.tapdb_mount import mount_tapdb_admin_subapp
from bloom_lims.tapdb_metrics import (
    request_method_var,
    request_path_var,
    stop_all_writers,
)


def create_app() -> FastAPI:
    settings = get_settings()
    allow_local_domain_access = not settings.is_production
    app = FastAPI()

    @app.on_event("shutdown")
    def _shutdown_cleanup() -> None:
        # Best-effort shutdown to flush/stop metrics writer.
        stop_all_writers()

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
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
    app.mount("/tmp", StaticFiles(directory="tmp"), name="tmp")

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

    app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

    mount_tapdb_admin_subapp(app)

    # Add rate limiting middleware for API endpoints (disable with BLOOM_RATE_LIMIT=no)
    if os.environ.get("BLOOM_RATE_LIMIT", "yes").lower() != "no":
        app.add_middleware(RateLimitMiddleware)

    # Include routers
    app.include_router(api_v1_router)
    try:
        from bloom_lims.gui.router import router as gui_router
    except ModuleNotFoundError as exc:
        logging.warning("Skipping GUI router due to missing optional dependency: %s", exc.name)
    else:
        app.include_router(gui_router)

    register_exception_handlers(app)
    return app
