from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("BLOOM_DEV_AUTH_BYPASS", "true")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main
from auth.cognito.client import CognitoTokenError
from bloom_lims.gui.routes.auth import SessionBootstrapError


class _FakeCognitoAuth:
    def __init__(self, *, payload: dict | None = None, exchange_error: Exception | None = None):
        self._payload = payload or {}
        self._exchange_error = exchange_error

    def exchange_authorization_code(self, code: str) -> dict:
        assert code == "auth-code"
        if self._exchange_error is not None:
            raise self._exchange_error
        return dict(self._payload)

    def validate_token(self, token: str) -> dict:
        assert token == "id-token-123"
        return {
            "email": "johnm@lsmc.com",
            "sub": "sub-123",
            "name": "John M",
            "cognito:username": "johnm@lsmc.com",
        }


class _MappedCognitoAuth:
    def __init__(self, payloads: dict[str, dict]):
        self._payloads = payloads
        self._token_payloads = {}
        self.config = SimpleNamespace(logout_url="/")
        for payload in payloads.values():
            for token_key in ("id_token", "access_token"):
                token = str(payload.get(token_key) or "").strip()
                if token:
                    self._token_payloads[token] = payload

    def exchange_authorization_code(self, code: str) -> dict:
        payload = self._payloads.get(code)
        assert payload is not None
        return dict(payload)

    def validate_token(self, token: str) -> dict:
        payload = self._token_payloads.get(token)
        assert payload is not None
        return dict(payload)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app, raise_server_exceptions=False)


def test_auth_callback_get_completes_login(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: _FakeCognitoAuth(
            payload={"id_token": "id-token-123", "access_token": "access-token-456"}
        ),
    )
    monkeypatch.setattr("bloom_lims.gui.routes.auth.get_allowed_domains", lambda: ["lsmc.com"])
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._resolve_login_roles_and_groups",
        lambda **_kwargs: (["ADMIN"], ["bloom-admin"], "sub-123"),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_user_preferences",
        lambda email: {"email": email, "display_timezone": "UTC"},
    )

    response = client.get("/auth/callback?code=auth-code", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.cookies.get("session")


def test_auth_callback_get_redirects_when_rbac_lookup_fails(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: _FakeCognitoAuth(
            payload={"id_token": "id-token-123", "access_token": "access-token-456"}
        ),
    )
    monkeypatch.setattr("bloom_lims.gui.routes.auth.get_allowed_domains", lambda: ["lsmc.com"])
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.BLOOMdb3",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tapdb unavailable")),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_user_preferences",
        lambda email: {"email": email, "display_timezone": "UTC"},
    )

    response = client.get("/auth/callback?code=auth-code", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=")
    assert "local%20access%20profile" in response.headers["location"]


def test_auth_callback_get_redirects_when_session_bootstrap_fails(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: _FakeCognitoAuth(
            payload={"id_token": "id-token-123", "access_token": "access-token-456"}
        ),
    )
    monkeypatch.setattr("bloom_lims.gui.routes.auth.get_allowed_domains", lambda: ["lsmc.com"])
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._resolve_login_roles_and_groups",
        lambda **_kwargs: (_ for _ in ()).throw(
            SessionBootstrapError(
                "Bloom could not initialize your local access profile. Please try signing in again."
            )
        ),
    )

    response = client.get("/auth/callback?code=auth-code", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=")
    assert "local%20access%20profile" in response.headers["location"]


def test_auth_callback_get_redirects_exchange_errors(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: _FakeCognitoAuth(exchange_error=CognitoTokenError("code exchange failed")),
    )

    response = client.get("/auth/callback?code=auth-code", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].endswith("code%20exchange%20failed")


def test_auth_callback_get_unexpected_error_redirects_cleanly(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    async def _explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: _FakeCognitoAuth(
            payload={"id_token": "id-token-123", "access_token": "access-token-456"}
        ),
    )
    monkeypatch.setattr("bloom_lims.gui.routes.auth._complete_cognito_login", _explode)

    response = client.get("/auth/callback?code=auth-code", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=")
    assert response.headers["location"].endswith(
        "Unable%20to%20complete%20login.%20Please%20try%20again."
    )


def test_auth_callback_post_requires_tokens(client: TestClient) -> None:
    response = client.post("/auth/callback", json={})

    assert response.status_code == 400
    assert response.json() == {"detail": "No Cognito tokens provided."}


def test_auth_callback_post_invalid_json_returns_clean_error(client: TestClient) -> None:
    response = client.post(
        "/auth/callback",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid callback payload"}


def test_auth_callback_post_unexpected_error_returns_service_unavailable(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    async def _explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("bloom_lims.gui.routes.auth._complete_cognito_login", _explode)

    response = client.post("/auth/callback", json={"id_token": "id-token-123"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Unable to complete login. Please try again."}


def test_empty_allowed_domain_config_blocks_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bloom_lims.config.get_settings",
        lambda: SimpleNamespace(auth=SimpleNamespace(cognito_allowed_domains=[])),
    )

    from bloom_lims.gui.deps import get_allowed_domains

    assert get_allowed_domains() == ["__BLOCK_ALL__"]


def test_multiple_gui_clients_keep_distinct_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLOOM_OAUTH", "yes")
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: _MappedCognitoAuth(
            {
                "alice-1": {
                    "id_token": "id-token-alice-1",
                    "access_token": "access-token-alice-1",
                    "email": "alice@lsmc.com",
                    "sub": "alice-sub",
                    "name": "Alice",
                    "cognito:username": "alice@lsmc.com",
                },
                "alice-2": {
                    "id_token": "id-token-alice-2",
                    "access_token": "access-token-alice-2",
                    "email": "alice@lsmc.com",
                    "sub": "alice-sub",
                    "name": "Alice",
                    "cognito:username": "alice@lsmc.com",
                },
                "bob-1": {
                    "id_token": "id-token-bob-1",
                    "access_token": "access-token-bob-1",
                    "email": "bob@lsmc.com",
                    "sub": "bob-sub",
                    "name": "Bob",
                    "cognito:username": "bob@lsmc.com",
                },
            }
        ),
    )
    monkeypatch.setattr("bloom_lims.gui.routes.auth.get_allowed_domains", lambda: ["lsmc.com"])
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._resolve_login_roles_and_groups",
        lambda **kwargs: (["READ_WRITE"], [], kwargs.get("cognito_sub") or kwargs.get("email")),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_user_preferences",
        lambda email: {"email": email, "display_timezone": "UTC"},
    )

    alice_1 = TestClient(main.app, raise_server_exceptions=False)
    alice_2 = TestClient(main.app, raise_server_exceptions=False)
    bob = TestClient(main.app, raise_server_exceptions=False)

    try:
        for client, code, expected_email in [
            (alice_1, "alice-1", "alice@lsmc.com"),
            (alice_2, "alice-2", "alice@lsmc.com"),
            (bob, "bob-1", "bob@lsmc.com"),
        ]:
            response = client.get(f"/auth/callback?code={code}", follow_redirects=False)
            assert response.status_code == 303
            home = client.get("/user_home")
            assert home.status_code == 200
            assert expected_email in home.text

        logout = alice_1.get("/logout", follow_redirects=False)
        assert logout.status_code == 303

        alice_2_home = alice_2.get("/user_home")
        bob_home = bob.get("/user_home")
        alice_1_home = alice_1.get("/user_home", follow_redirects=False)

        assert alice_2_home.status_code == 200
        assert "alice@lsmc.com" in alice_2_home.text
        assert bob_home.status_code == 200
        assert "bob@lsmc.com" in bob_home.text
        assert alice_1_home.status_code in {302, 303, 307}
    finally:
        alice_1.close()
        alice_2.close()
        bob.close()
