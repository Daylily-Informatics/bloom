from __future__ import annotations

import logging
import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth.cognito.client import CognitoConfigurationError, CognitoTokenError
from bloom_lims.gui.deps import _get_request_cognito_auth, get_allowed_domains, get_user_preferences, require_auth
from bloom_lims.gui.errors import MissingCognitoEnvVarsException
from bloom_lims.gui.jinja import templates


router = APIRouter()


@router.get("/login", include_in_schema=False)
async def get_login_page(request: Request):
    user_data = request.session.get("user_data", {})
    auth_error = request.query_params.get("error")

    if os.environ.get("BLOOM_OAUTH", "yes") == "no":
        cognito_login_url = "#auth-disabled"
    else:
        try:
            cognito = _get_request_cognito_auth(request)
            cognito_login_url = cognito.config.authorize_url
        except CognitoConfigurationError as exc:
            raise MissingCognitoEnvVarsException(str(exc)) from exc

    template = templates.get_template("modern/login.html")
    context = {
        "request": request,
        "udat": user_data,
        "cognito_login_url": cognito_login_url,
        "auth_error": auth_error,
        "version": "1.0.0",
    }
    return HTMLResponse(content=template.render(context))


def _login_error_redirect(error_message: str) -> RedirectResponse:
    msg = (error_message or "authentication_failed").strip()
    return RedirectResponse(url=f"/login?error={quote(msg)}", status_code=303)


async def _complete_cognito_login(
    request: Request,
    *,
    id_token: str | None,
    access_token: str | None,
) -> RedirectResponse:
    if not id_token and not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Cognito tokens provided.",
        )

    try:
        cognito = _get_request_cognito_auth(request)
        decoded_token = cognito.validate_token(id_token or access_token)
    except CognitoConfigurationError as exc:
        raise MissingCognitoEnvVarsException(str(exc)) from exc
    except CognitoTokenError as exc:
        logging.error("Unable to validate Cognito token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Cognito token"
        ) from exc

    primary_email = decoded_token.get("email") or decoded_token.get("username")
    if not primary_email:
        primary_email = decoded_token.get("cognito:username")

    if not primary_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to determine email from Cognito token",
        )

    allowed_domains = get_allowed_domains()
    if allowed_domains == ["__BLOCK_ALL__"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email domain authentication is not enabled",
        )
    if allowed_domains:
        user_domain = primary_email.split("@")[-1]
        if user_domain not in allowed_domains:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email domain not allowed",
            )

    user_data = get_user_preferences(primary_email)
    user_data.update(
        {
            "id_token": id_token,
            "access_token": access_token,
            "cognito_username": decoded_token.get("cognito:username"),
            "cognito_sub": decoded_token.get("sub"),
        }
    )
    request.session["user_data"] = user_data

    return RedirectResponse(url="/", status_code=303)


@router.get("/oauth_callback")
async def oauth_callback_get(request: Request):
    callback_error = request.query_params.get("error")
    if callback_error:
        callback_description = request.query_params.get("error_description")
        return _login_error_redirect(callback_description or callback_error)

    auth_code = request.query_params.get("code")
    if auth_code:
        try:
            cognito = _get_request_cognito_auth(request)
            token_payload = cognito.exchange_authorization_code(auth_code)
            return await _complete_cognito_login(
                request,
                id_token=token_payload.get("id_token"),
                access_token=token_payload.get("access_token"),
            )
        except HTTPException as exc:
            return _login_error_redirect(str(exc.detail))
        except CognitoConfigurationError as exc:
            raise MissingCognitoEnvVarsException(str(exc)) from exc
        except CognitoTokenError as exc:
            logging.error("Authorization code exchange failed: %s", exc)
            return _login_error_redirect(str(exc))

    html_content = """<!DOCTYPE html>
<html>
<head><title>Processing login...</title></head>
<body>
    <p>Processing your login...</p>
    <script>
        const fragment = new URLSearchParams(window.location.hash.substring(1));
        const accessToken = fragment.get('access_token');
        const idToken = fragment.get('id_token');
        const error = fragment.get('error');
        const errorDescription = fragment.get('error_description');
        
        if (error) {
            window.location.href = '/login?error=' + encodeURIComponent(errorDescription || error);
        } else if (accessToken || idToken) {
            fetch('/oauth_callback', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({access_token: accessToken, id_token: idToken}),
                credentials: 'same-origin'
            }).then(response => {
                if (response.redirected) {
                    window.location.href = response.url;
                } else if (response.ok) {
                    window.location.href = '/';
                } else {
                    return response.json().then(data => {
                        window.location.href = '/login?error=' + encodeURIComponent(data.detail || 'Authentication failed');
                    });
                }
            }).catch(err => {
                console.error('Error:', err);
                window.location.href = '/login?error=authentication_failed';
            });
        } else {
            window.location.href = '/login?error=no_tokens';
        }
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@router.post("/oauth_callback")
async def oauth_callback(request: Request):
    body = await request.json()
    access_token = body.get("access_token") or body.get("accessToken")
    id_token = body.get("id_token")
    return await _complete_cognito_login(
        request,
        id_token=id_token,
        access_token=access_token,
    )


@router.get("/auth/callback")
async def auth_callback_get(request: Request):
    return await oauth_callback_get(request)


@router.post("/auth/callback")
async def auth_callback(request: Request):
    return await oauth_callback(request)


@router.post("/login", include_in_schema=False)
async def login(_: Request, __: Response, email: str = Form(None)):
    if not email:
        return JSONResponse(
            content={"message": "Direct login is disabled. Please authenticate with Cognito SSO."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return JSONResponse(
        content={"message": "Direct login is disabled. Please authenticate with Cognito SSO."},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.get("/logout")
async def logout(request: Request, response: Response):
    try:
        logging.warning("Logging out user: clearing session data")

        cognito_logout_url = "/"
        try:
            cognito_logout_url = _get_request_cognito_auth(request).config.logout_url
        except CognitoConfigurationError as exc:
            logging.error("Cognito configuration missing during logout: %s", exc)

        request.session.clear()
        response.delete_cookie("session", path="/")
        logging.info("User session cleared.")
    except Exception as exc:
        logging.error("Error during logout: %s", exc)
        return JSONResponse(
            content={"message": "An error occurred during logout: " + str(exc)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return RedirectResponse(url=cognito_logout_url, status_code=status.HTTP_303_SEE_OTHER)

