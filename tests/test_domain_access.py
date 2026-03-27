from __future__ import annotations

from fastapi.testclient import TestClient

from bloom_lims.app import create_app


def test_bloom_allows_approved_origin_preflight() -> None:
    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.options(
            "/",
            headers={
                "Origin": "https://portal.lsmc.bio",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://portal.lsmc.bio"


def test_bloom_rejects_disallowed_origin() -> None:
    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.options(
            "/",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 403
    assert response.text == "Origin not allowed"


def test_bloom_rejects_disallowed_host() -> None:
    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/", headers={"host": "evil.example.com"}, follow_redirects=False)

    assert response.status_code == 400
