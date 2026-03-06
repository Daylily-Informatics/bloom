"""FastAPI application factory for BLOOM.

This keeps `main.py` as a thin entrypoint while preserving `uvicorn main:app`.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from bloom_lims.api import RateLimitMiddleware, api_v1_router
from bloom_lims.gui.errors import register_exception_handlers
from bloom_lims.gui.router import router as gui_router
from bloom_lims.tapdb_metrics import request_method_var, request_path_var, stop_all_writers

try:
    from admin.main import app as tapdb_admin_app
except ImportError:
    tapdb_admin_app = None


def _effective_request_scheme(request: Request) -> str:
    """Resolve effective request scheme from trusted forwarded headers first."""
    forwarded = str(request.headers.get("x-forwarded-proto") or "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip().lower()
    return str(request.url.scheme or "").strip().lower()


def create_app() -> FastAPI:
    app = FastAPI()

    @app.on_event("shutdown")
    def _shutdown_cleanup() -> None:
        # Best-effort shutdown to flush/stop metrics writer.
        stop_all_writers()

    # Request attribution context for TapDB-style DB metrics.
    @app.middleware("http")
    async def _enforce_https_transport(request: Request, call_next):
        scheme = _effective_request_scheme(request)
        if scheme != "https":
            detail = "HTTPS required"
            if request.url.path.startswith("/api/"):
                return JSONResponse(status_code=426, content={"detail": detail})
            return PlainTextResponse(detail, status_code=426)

        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

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
    if tapdb_admin_app is not None:
        app.mount("/tapdb", tapdb_admin_app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(SessionMiddleware, secret_key="your-secret-key", https_only=True)

    # Add rate limiting middleware for API endpoints (disable with BLOOM_RATE_LIMIT=no)
    if os.environ.get("BLOOM_RATE_LIMIT", "yes").lower() != "no":
        app.add_middleware(RateLimitMiddleware)

    # Include routers
    app.include_router(api_v1_router)
    app.include_router(gui_router)

    register_exception_handlers(app)
    return app
