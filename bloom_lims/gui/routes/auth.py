from __future__ import annotations

import logging
import os
from urllib.parse import quote

from daylily_cognito import (
    CognitoWebAuthError,
    SessionPrincipal,
    complete_cognito_callback,
    start_cognito_login,
)
from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth.cognito.client import CognitoConfigurationError, CognitoTokenError
from bloom_lims.auth.rbac import Role
from bloom_lims.auth.repositories.tapdb.users import resolve_user_record
from bloom_lims.auth.services.groups import GroupService, map_legacy_role
from bloom_lims.db import BLOOMdb3
from bloom_lims.gui.deps import (
    _get_request_cognito_auth,
    get_allowed_domains,
    get_user_preferences,
)
from bloom_lims.gui.errors import MissingCognitoEnvVarsException
from bloom_lims.gui.jinja import templates
from bloom_lims.gui.web_session import (
    build_bloom_web_session_config,
    clear_bloom_session,
    load_bloom_user_data,
    store_bloom_session,
)
from bloom_lims.config import get_settings

router = APIRouter()


class SessionBootstrapError(RuntimeError):
    """Raised when Bloom cannot establish the post-login session context."""


def _next_path(raw_value: str | None) -> str:
    value = str(raw_value or "").strip()
    return value if value.startswith("/") else "/"


@router.get("/login", include_in_schema=False)
async def get_login_page(request: Request, next: str = "/"):
    user_data = load_bloom_user_data(request) or {}
    auth_error = request.query_params.get("reason") or request.query_params.get("error")
    next_path = _next_path(next)

    if user_data.get("email") or user_data.get("user_id") or user_data.get("sub"):
        return RedirectResponse(url=next_path, status_code=303)

    cognito_login_url = f"/auth/login?next={quote(next_path, safe='/')}"

    template = templates.get_template("modern/login.html")
    context = {
        "request": request,
        "udat": user_data,
        "cognito_login_url": cognito_login_url,
        "auth_primary_href": f"/auth/login?next={quote(next_path, safe='/')}",
        "auth_error": auth_error,
        "version": "1.0.0",
    }
    return HTMLResponse(content=template.render(context))


@router.get("/auth/login", include_in_schema=False)
async def auth_login(request: Request, next: str = "/"):
    if os.environ.get("BLOOM_OAUTH", "yes") == "no":
        return RedirectResponse(url=_next_path(next), status_code=303)
    try:
        clear_bloom_session(request)
        return start_cognito_login(
            request,
            build_bloom_web_session_config(request),
            _next_path(next),
        )
    except CognitoConfigurationError as exc:
        raise MissingCognitoEnvVarsException(str(exc)) from exc


def _auth_error_redirect(reason: str, *, next_path: str = "/") -> RedirectResponse:
    safe_reason = (reason or "authentication_failed").strip()
    safe_next = _next_path(next_path)
    return RedirectResponse(
        url=f"/auth/error?reason={quote(safe_reason)}&next={quote(safe_next, safe='/')}",
        status_code=303,
    )


def _callback_error_response(error_message: str, *, status_code: int) -> JSONResponse:
    msg = (error_message or "authentication_failed").strip()
    return JSONResponse(content={"detail": msg}, status_code=status_code)


def _resolve_login_roles_and_groups(
    *,
    email: str,
    cognito_sub: str | None,
    fallback_role: str | None,
) -> tuple[list[str], list[str], str, str]:
    normalized_email = str(email or "").strip()
    normalized_sub = str(cognito_sub or "").strip()
    bdb = None
    bloom_settings = get_settings()
    try:
        bdb = BLOOMdb3(app_username=normalized_email or "cognito-login")
        service = GroupService(bdb.session)
        service.ensure_system_groups()
        found_user_id = ""
        found_fallback = map_legacy_role(fallback_role)

        for candidate in (normalized_sub, normalized_email):
            if not candidate:
                continue
            stored_user = resolve_user_record(
                bdb.session, candidate, include_inactive=True
            )
            fallback = map_legacy_role(
                stored_user.role if stored_user and stored_user.role else fallback_role
            )
            resolution = service.resolve_user_roles_and_groups(
                user_id=candidate,
                fallback_role=fallback,
            )
            if resolution.groups:
                return resolution.roles, resolution.groups, candidate, fallback
            if stored_user is not None and not found_user_id:
                found_user_id = candidate
                found_fallback = fallback

        if found_user_id:
            return [found_fallback], [], found_user_id, found_fallback

        allowed_domains = [
            str(domain or "").strip().lower()
            for domain in bloom_settings.auth.auto_provision_allowed_domains
            if str(domain or "").strip()
        ]
        normalized_domain = normalized_email.rsplit("@", 1)[-1].lower()
        if not allowed_domains:
            raise SessionBootstrapError(
                "Bloom access is restricted to approved auto-provision domains. "
                "Please contact your administrator for an invitation."
            )
        if allowed_domains != ["*"] and normalized_domain not in allowed_domains:
            raise SessionBootstrapError(
                "Bloom access is restricted to approved auto-provision domains. "
                "Please contact your administrator for an invitation."
            )

        default_user_id = normalized_sub or normalized_email
        fallback = map_legacy_role(fallback_role)
        resolution = service.resolve_user_roles_and_groups(
            user_id=default_user_id,
            fallback_role=fallback,
        )
        return resolution.roles, resolution.groups, default_user_id, fallback
    except Exception as exc:
        logging.warning(
            "Failed to resolve session RBAC for %s: %s", normalized_email, exc
        )
        raise SessionBootstrapError(
            "Bloom could not initialize your local access profile. Please try signing in again."
        ) from exc
    finally:
        if bdb is not None:
            bdb.close()


def _build_bloom_principal(decoded_token: dict) -> tuple[SessionPrincipal, dict]:
    primary_email = decoded_token.get("email") or decoded_token.get("username")
    if not primary_email:
        primary_email = decoded_token.get("cognito:username")

    if not primary_email:
        raise CognitoWebAuthError(
            "missing_email",
            "Unable to determine email from Cognito token",
            status_code=status.HTTP_400_BAD_REQUEST,
            redirect_to_error=True,
        )

    allowed_domains = get_allowed_domains()
    if allowed_domains == ["__BLOCK_ALL__"]:
        raise CognitoWebAuthError(
            "email_domain_auth_disabled",
            "Email domain authentication is not enabled",
            status_code=status.HTTP_403_FORBIDDEN,
            redirect_to_error=True,
        )
    if allowed_domains:
        user_domain = primary_email.split("@")[-1]
        if user_domain not in allowed_domains:
            raise CognitoWebAuthError(
                "email_domain_not_allowed",
                "Email domain not allowed",
                status_code=status.HTTP_403_FORBIDDEN,
                redirect_to_error=True,
            )

    cognito_sub = decoded_token.get("sub")
    cognito_groups = decoded_token.get("cognito:groups")
    identity_groups = (
        [str(item).strip() for item in cognito_groups if str(item).strip()]
        if isinstance(cognito_groups, list)
        else []
    )
    try:
        roles, groups, resolved_user_id, persisted_role = (
            _resolve_login_roles_and_groups(
                email=primary_email,
                cognito_sub=cognito_sub,
                fallback_role=None,
            )
        )
    except SessionBootstrapError as exc:
        raise CognitoWebAuthError(
            "session_bootstrap_failed",
            str(exc),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            redirect_to_error=True,
        ) from exc

    normalized_roles = [str(role).upper() for role in roles if str(role).strip()]
    primary_role = (
        persisted_role
        or (normalized_roles[0] if normalized_roles else Role.READ_WRITE.value)
    ).upper()
    service_groups = list(dict.fromkeys(groups))
    user_data = get_user_preferences(primary_email)
    user_data.update(
        {
            "cognito_username": decoded_token.get("cognito:username"),
            "cognito_sub": cognito_sub,
            "sub": cognito_sub,
            "user_id": resolved_user_id,
            "name": decoded_token.get("name")
            or decoded_token.get("cognito:username")
            or primary_email,
            "role": primary_role,
            "roles": normalized_roles or [primary_role],
            "identity_groups": identity_groups,
            "cognito_groups": list(identity_groups),
            "service_groups": service_groups,
            "groups": service_groups,
        }
    )

    principal = SessionPrincipal(
        user_sub=str(cognito_sub or resolved_user_id),
        email=primary_email,
        name=str(user_data.get("name") or primary_email),
        roles=list(user_data["roles"]),
        cognito_groups=list(identity_groups),
        auth_mode="cognito",
        app_context={"user_data": dict(user_data)},
    )
    return principal, user_data


def _resolve_principal_from_token_payload(
    token_payload: dict, request: Request
) -> SessionPrincipal:
    id_token = token_payload.get("id_token")
    access_token = token_payload.get("access_token")
    if not id_token and not access_token:
        raise CognitoWebAuthError(
            "missing_tokens",
            "No Cognito tokens provided.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        cognito = _get_request_cognito_auth(request)
        decoded_token = cognito.validate_token(id_token or access_token)
    except CognitoConfigurationError as exc:
        raise MissingCognitoEnvVarsException(str(exc)) from exc
    except CognitoTokenError as exc:
        logging.error("Unable to validate Cognito token: %s", exc)
        raise CognitoWebAuthError(
            "invalid_cognito_token",
            "Invalid Cognito token",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc

    principal, user_data = _build_bloom_principal(decoded_token)
    request.state.bloom_user_data = user_data
    return principal


async def _complete_cognito_login(
    request: Request,
    *,
    id_token: str | None,
    access_token: str | None,
) -> RedirectResponse:
    principal = _resolve_principal_from_token_payload(
        {"id_token": id_token, "access_token": access_token},
        request,
    )
    user_data = getattr(request.state, "bloom_user_data", None) or {}
    store_bloom_session(request, principal, user_data=user_data)
    config = build_bloom_web_session_config(request)
    redirect_to = request.session.pop(config.next_path_session_key, None)
    if not redirect_to:
        redirect_to = request.session.pop("bloom_post_auth_redirect", "/")
    redirect_to = _next_path(redirect_to)
    return RedirectResponse(url=redirect_to, status_code=303)


@router.get("/oauth_callback")
async def oauth_callback_get(request: Request):
    callback_error = request.query_params.get("error")
    if callback_error:
        callback_description = request.query_params.get("error_description")
        return _auth_error_redirect(callback_description or callback_error)

    auth_code = request.query_params.get("code")
    if auth_code:
        try:
            response = await complete_cognito_callback(
                request,
                build_bloom_web_session_config(request),
                auth_code,
                request.query_params.get("state"),
                _resolve_principal_from_token_payload,
            )
            load_bloom_user_data(request)
            return response
        except CognitoWebAuthError as exc:
            return _auth_error_redirect(exc.reason)
        except CognitoConfigurationError as exc:
            raise MissingCognitoEnvVarsException(str(exc)) from exc
        except Exception:
            logging.exception("Unhandled error completing Cognito callback")
            return _auth_error_redirect("authentication_failed")
    return _auth_error_redirect("missing_code")


@router.post("/oauth_callback")
async def oauth_callback(request: Request):
    try:
        body = await request.json()
    except Exception:
        logging.exception("Invalid Cognito callback payload")
        return _callback_error_response(
            "Invalid callback payload",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    access_token = body.get("access_token") or body.get("accessToken")
    id_token = body.get("id_token")
    try:
        return await _complete_cognito_login(
            request,
            id_token=id_token,
            access_token=access_token,
        )
    except CognitoWebAuthError as exc:
        return _callback_error_response(exc.detail, status_code=exc.status_code)
    except HTTPException as exc:
        return _callback_error_response(str(exc.detail), status_code=exc.status_code)
    except Exception:
        logging.exception("Unhandled error completing Cognito callback")
        return _callback_error_response(
            "Unable to complete login. Please try again.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get("/auth/callback")
async def auth_callback_get(request: Request):
    return await oauth_callback_get(request)


@router.post("/auth/callback")
async def auth_callback(request: Request):
    return await oauth_callback(request)


@router.get("/auth/error", include_in_schema=False)
async def auth_error(
    request: Request, reason: str = "authentication_failed", next: str = "/"
):
    next_path = _next_path(next)
    template = templates.get_template("modern/login.html")
    context = {
        "request": request,
        "udat": load_bloom_user_data(request) or {},
        "cognito_login_url": f"/auth/login?next={quote(next_path, safe='/')}",
        "auth_primary_href": f"/auth/login?next={quote(next_path, safe='/')}",
        "auth_error": reason,
        "version": "1.0.0",
    }
    return HTMLResponse(content=template.render(context), status_code=403)


@router.post("/login", include_in_schema=False)
async def login(_: Request, __: Response, email: str = Form(None)):
    if not email:
        return JSONResponse(
            content={
                "message": "Direct login is disabled. Please authenticate with Cognito SSO."
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return JSONResponse(
        content={
            "message": "Direct login is disabled. Please authenticate with Cognito SSO."
        },
        status_code=status.HTTP_400_BAD_REQUEST,
    )


async def _logout_response(request: Request, response: Response):
    try:
        logging.warning("Logging out user: clearing session data")

        cognito_logout_url = "/login"
        try:
            cognito_logout_url = _get_request_cognito_auth(request).config.logout_url
        except CognitoConfigurationError as exc:
            logging.error("Cognito configuration missing during logout: %s", exc)

        clear_bloom_session(request)
        logging.info("User session cleared.")
    except Exception as exc:
        logging.error("Error during logout: %s", exc)
        return JSONResponse(
            content={"message": "An error occurred during logout: " + str(exc)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    logout_response = RedirectResponse(
        url=cognito_logout_url, status_code=status.HTTP_303_SEE_OTHER
    )
    logout_response.delete_cookie("bloom_session", path="/")
    logout_response.delete_cookie("session", path="/")
    return logout_response


@router.get("/auth/logout", include_in_schema=False)
async def auth_logout_get(request: Request, response: Response):
    return await _logout_response(request, response)


@router.post("/auth/logout", include_in_schema=False)
async def auth_logout_post(request: Request, response: Response):
    return await _logout_response(request, response)


@router.get("/logout")
async def logout(request: Request, response: Response):
    return await _logout_response(request, response)
