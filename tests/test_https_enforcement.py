"""HTTPS transport enforcement tests."""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

from bloom_lims.config import AtlasSettings
from bloom_lims.integrations.atlas.client import AtlasClient, AtlasClientError


os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


def test_http_api_request_is_rejected_with_426():
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)
    response = client.get("/api/v1/")
    assert response.status_code == 426
    assert response.json().get("detail") == "HTTPS required"


def test_http_gui_request_is_rejected_with_426():
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)
    response = client.get("/help")
    assert response.status_code == 426
    assert "HTTPS required" in response.text


def test_https_request_succeeds_and_sets_hsts():
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    response = client.get("/help")
    assert response.status_code == 200
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_forwarded_proto_http_is_rejected_even_on_https_base_url():
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    response = client.get("/help", headers={"X-Forwarded-Proto": "http,https"})
    assert response.status_code == 426
    assert "HTTPS required" in response.text


def test_atlas_client_rejects_non_https_base_url():
    with pytest.raises(AtlasClientError, match="atlas.base_url must use https://"):
        AtlasClient(base_url="http://localhost:8915", token="token")


def test_atlas_settings_reject_non_https_base_url():
    with pytest.raises(ValueError, match="atlas.base_url must use https://"):
        AtlasSettings(base_url="http://localhost:8915", token="token")

