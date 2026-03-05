from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse


class AuthenticationRequiredException(HTTPException):
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(status_code=401, detail=detail)


class MissingCognitoEnvVarsException(HTTPException):
    def __init__(self, message: str = "The Cognito environment variables are not found."):
        super().__init__(status_code=401, detail=message)


class RequireAuthException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=403, detail=detail)


async def authentication_required_exception_handler(
    _request: Request, _exc: AuthenticationRequiredException
):
    return RedirectResponse(url="/login")


async def require_auth_exception_handler(_request: Request, _exc: RequireAuthException):
    return RedirectResponse(url="/login")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        AuthenticationRequiredException, authentication_required_exception_handler
    )
    app.add_exception_handler(RequireAuthException, require_auth_exception_handler)

