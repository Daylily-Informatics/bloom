"""Own Bloom database handles for the complete ASGI request lifetime."""

from contextlib import ExitStack
from contextvars import ContextVar
from typing import Protocol

from starlette.types import ASGIApp, Receive, Scope, Send


class DatabaseHandle(Protocol):
    def close(self) -> None: ...


_request_databases: ContextVar[ExitStack | None] = ContextVar(
    "bloom_request_databases", default=None
)


def register_request_database(database: DatabaseHandle) -> None:
    stack = _request_databases.get()
    if stack is not None:
        stack.callback(database.close)


class RequestDatabaseMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # The shared stack also reaches sync handlers through their copied context.
        # Keep it alive through streaming responses and response background tasks.
        with ExitStack() as databases:
            token = _request_databases.set(databases)
            try:
                await self.app(scope, receive, send)
            finally:
                _request_databases.reset(token)
