from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from daylily_cognito import SessionPrincipal
from fastapi.testclient import TestClient

os.environ.setdefault("BLOOM_DEV_AUTH_BYPASS", "true")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main
from bloom_lims.gui.routes.auth import SessionBootstrapError
from bloom_lims.gui.web_session import _normalize_user_data


def _fake_cognito_config() -> SimpleNamespace:
    return SimpleNamespace(
        domain="example.auth.us-west-2.amazoncognito.com",
        client_id="client-123",
        client_secret="client-secret",
        redirect_uri="https://localhost:8912/auth/callback",
        logout_redirect_uri="https://localhost:8912/auth/logout",
        scopes=["openid", "email", "profile"],
        logout_url="/",
    )


class _FakeCognitoAuth:
    def __init__(self, *, payload: dict | None = None):
        self._payload = payload or {}
        self.config = _fake_cognito_config()

    def exchange_authorization_code(self, code: str) -> dict:
        assert code == "auth-code"
        return dict(self._payload)

    def validate_token(self, token: str) -> dict:
        payload = dict(self._payload)
        assert token == payload.get("id_token", "id-token-123")
        return {
            "email": payload.get("email", "johnm@lsmc.com"),
            "sub": payload.get("sub", "sub-123"),
            "name": payload.get("name", "John M"),
            "cognito:username": payload.get("cognito:username", "johnm@lsmc.com"),
        }


class _MappedCognitoAuth:
    def __init__(self, payloads: dict[str, dict]):
        self._payloads = payloads
        self._token_payloads = {}
        self.config = _fake_cognito_config()
        for payload in payloads.values():
            token = str(payload.get("id_token") or "").strip()
            if token:
                self._token_payloads[token] = payload

    def exchange_authorization_code(self, code: str) -> dict:
        payload = self._payloads.get(code)
        assert payload is not None
        return dict(payload)

    def validate_token(self, token: str) -> dict:
        payload = self._token_payloads.get(token)
        assert payload is not None
        return {
            "email": payload["email"],
            "sub": payload["sub"],
            "name": payload["name"],
            "cognito:username": payload["cognito:username"],
        }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BLOOM_OAUTH", "yes")
    return TestClient(
        main.app, raise_server_exceptions=False, base_url="https://localhost:8912"
    )


def _begin_login(client: TestClient, next_path: str = "/") -> str:
    response = client.get(f"/auth/login?next={next_path}", follow_redirects=False)
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    params = parse_qs(urlparse(location).query)
    state = params.get("state", [""])[0]
    assert state
    return state


def test_auth_callback_get_completes_login(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    fake_auth = _FakeCognitoAuth(
        payload={"id_token": "id-token-123", "access_token": "access-token-456"}
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: fake_auth,
    )
    monkeypatch.setattr(
        "daylily_cognito.web_session.exchange_authorization_code",
        lambda **kwargs: fake_auth.exchange_authorization_code(kwargs["code"]),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_allowed_domains", lambda: ["lsmc.com"]
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._resolve_login_roles_and_groups",
        lambda **_kwargs: (["ADMIN"], ["API_ACCESS"], "sub-123", "ADMIN"),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_user_preferences",
        lambda email: {"email": email, "display_timezone": "UTC"},
    )

    state = _begin_login(client)
    response = client.get(
        f"/auth/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/"
    assert client.cookies.get("bloom_session")
    assert not client.cookies.get("session")


def test_auth_callback_get_requires_prior_login_state(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    fake_auth = _FakeCognitoAuth(
        payload={"id_token": "id-token-123", "access_token": "access-token-456"}
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: fake_auth,
    )
    monkeypatch.setattr(
        "daylily_cognito.web_session.exchange_authorization_code",
        lambda **kwargs: fake_auth.exchange_authorization_code(kwargs["code"]),
    )

    response = client.get(
        "/auth/callback?code=auth-code&state=missing", follow_redirects=False
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"].startswith("/auth/error?reason=invalid_state")


def test_auth_callback_get_redirects_when_session_bootstrap_fails(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    fake_auth = _FakeCognitoAuth(
        payload={"id_token": "id-token-123", "access_token": "access-token-456"}
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: fake_auth,
    )
    monkeypatch.setattr(
        "daylily_cognito.web_session.exchange_authorization_code",
        lambda **kwargs: fake_auth.exchange_authorization_code(kwargs["code"]),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_allowed_domains", lambda: ["lsmc.com"]
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._resolve_login_roles_and_groups",
        lambda **_kwargs: (_ for _ in ()).throw(
            SessionBootstrapError(
                "Bloom could not initialize your local access profile. Please try signing in again."
            )
        ),
    )

    state = _begin_login(client)
    response = client.get(
        f"/auth/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"].startswith(
        "/auth/error?reason=session_bootstrap_failed"
    )


def test_auth_callback_get_redirects_exchange_errors(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setattr(
        "daylily_cognito.web_session.exchange_authorization_code",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("code exchange failed")),
    )

    state = _begin_login(client)
    response = client.get(
        f"/auth/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"].startswith(
        "/auth/error?reason=token_exchange_failed"
    )


def test_auth_callback_get_unexpected_error_redirects_cleanly(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    fake_auth = _FakeCognitoAuth(
        payload={"id_token": "id-token-123", "access_token": "access-token-456"}
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: fake_auth,
    )
    monkeypatch.setattr(
        "daylily_cognito.web_session.exchange_authorization_code",
        lambda **kwargs: fake_auth.exchange_authorization_code(kwargs["code"]),
    )

    def _explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._resolve_principal_from_token_payload", _explode
    )

    state = _begin_login(client)
    response = client.get(
        f"/auth/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"].startswith(
        "/auth/error?reason=authentication_failed"
    )


def test_auth_callback_post_requires_tokens(client: TestClient) -> None:
    response = client.post("/auth/callback", json={})

    assert response.status_code == 400
    assert response.json() == {"detail": "No Cognito tokens provided."}


def test_auth_callback_post_invalid_json_returns_clean_error(
    client: TestClient,
) -> None:
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


def test_empty_allowed_domain_config_blocks_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bloom_lims.config.get_settings",
        lambda: SimpleNamespace(auth=SimpleNamespace(cognito_allowed_domains=[])),
    )

    from bloom_lims.gui.deps import get_allowed_domains

    assert get_allowed_domains() == ["__BLOCK_ALL__"]


def test_resolve_login_roles_and_groups_blocks_missing_user_outside_autoprovision_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_settings",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(auto_provision_allowed_domains=["lsmc.com"])
        ),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.resolve_user_record",
        lambda *_args, **_kwargs: None,
    )

    class _FakeGroupService:
        def __init__(self, _db):
            pass

        def ensure_system_groups(self):
            return None

        def resolve_user_roles_and_groups(self, *, user_id, fallback_role):
            return SimpleNamespace(roles=[fallback_role or "READ_WRITE"], groups=[])

    monkeypatch.setattr("bloom_lims.gui.routes.auth.GroupService", _FakeGroupService)

    class _FakeBDB:
        session = object()

        def close(self):
            return None

    monkeypatch.setattr("bloom_lims.gui.routes.auth.BLOOMdb3", lambda *_, **__: _FakeBDB())

    from bloom_lims.gui.routes.auth import _resolve_login_roles_and_groups

    with pytest.raises(SessionBootstrapError, match="could not initialize your local access profile"):
        _resolve_login_roles_and_groups(
            email="new@daylilyinformatics.com",
            cognito_sub="sub-123",
            fallback_role=None,
        )


def test_resolve_login_roles_and_groups_allows_missing_user_on_autoprovision_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_settings",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(auto_provision_allowed_domains=["lsmc.com"])
        ),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.resolve_user_record",
        lambda *_args, **_kwargs: None,
    )

    class _FakeGroupService:
        def __init__(self, _db):
            pass

        def ensure_system_groups(self):
            return None

        def resolve_user_roles_and_groups(self, *, user_id, fallback_role):
            return SimpleNamespace(roles=[fallback_role or "READ_WRITE"], groups=["API"])

    monkeypatch.setattr("bloom_lims.gui.routes.auth.GroupService", _FakeGroupService)

    class _FakeBDB:
        session = object()

        def close(self):
            return None

    monkeypatch.setattr("bloom_lims.gui.routes.auth.BLOOMdb3", lambda *_, **__: _FakeBDB())

    from bloom_lims.gui.routes.auth import _resolve_login_roles_and_groups

    roles, groups, user_id, persisted_role = _resolve_login_roles_and_groups(
        email="new@lsmc.com",
        cognito_sub="sub-123",
        fallback_role=None,
    )

    assert roles == ["READ_WRITE"]
    assert groups == ["API"]
    assert user_id == "sub-123"
    assert persisted_role == "READ_WRITE"


def test_normalize_user_data_strips_raw_tokens() -> None:
    principal = SessionPrincipal(
        user_sub="sub-123",
        email="johnm@lsmc.com",
        roles=["ADMIN"],
        cognito_groups=["platform-admin", "bloom-admin"],
        auth_mode="cognito",
    )

    normalized = _normalize_user_data(
        {
            "email": "johnm@lsmc.com",
            "service_groups": ["API_ACCESS", "ENABLE_ATLAS_API"],
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
        },
        principal,
    )

    assert "access_token" not in normalized
    assert "id_token" not in normalized
    assert "refresh_token" not in normalized
    assert normalized["identity_groups"] == ["platform-admin", "bloom-admin"]
    assert normalized["cognito_groups"] == ["platform-admin", "bloom-admin"]
    assert normalized["service_groups"] == ["API_ACCESS", "ENABLE_ATLAS_API"]
    assert normalized["groups"] == ["API_ACCESS", "ENABLE_ATLAS_API"]


def test_multiple_gui_clients_keep_distinct_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLOOM_OAUTH", "yes")
    fake_auth = _MappedCognitoAuth(
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
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._get_request_cognito_auth",
        lambda _request: fake_auth,
    )
    monkeypatch.setattr(
        "daylily_cognito.web_session.exchange_authorization_code",
        lambda **kwargs: fake_auth.exchange_authorization_code(kwargs["code"]),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_allowed_domains", lambda: ["lsmc.com"]
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth._resolve_login_roles_and_groups",
        lambda **kwargs: (
            ["READ_WRITE"],
            [],
            kwargs.get("cognito_sub") or kwargs.get("email"),
            "READ_WRITE",
        ),
    )
    monkeypatch.setattr(
        "bloom_lims.gui.routes.auth.get_user_preferences",
        lambda email: {"email": email, "display_timezone": "UTC"},
    )

    alice_1 = TestClient(
        main.app, raise_server_exceptions=False, base_url="https://localhost:8912"
    )
    alice_2 = TestClient(
        main.app, raise_server_exceptions=False, base_url="https://localhost:8912"
    )
    bob = TestClient(
        main.app, raise_server_exceptions=False, base_url="https://localhost:8912"
    )

    try:
        for client, code, expected_email in [
            (alice_1, "alice-1", "alice@lsmc.com"),
            (alice_2, "alice-2", "alice@lsmc.com"),
            (bob, "bob-1", "bob@lsmc.com"),
        ]:
            state = _begin_login(client)
            response = client.get(
                f"/auth/callback?code={code}&state={state}", follow_redirects=False
            )
            assert response.status_code in (302, 303)
            home = client.get("/user_home")
            assert home.status_code == 200
            assert expected_email in home.text

        logout = alice_1.get("/auth/logout", follow_redirects=False)
        assert logout.status_code in (302, 303)

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
