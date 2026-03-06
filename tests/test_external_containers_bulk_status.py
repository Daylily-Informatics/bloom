"""Tests for /api/v1/external/containers/status/bulk."""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _create_tube(client: TestClient, name: str) -> str:
    response = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": "container",
            "type": "tube",
            "subtype": "tube-generic-10ml",
            "version": "1.0",
            "name": name,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["euid"]


def test_bulk_container_status_returns_found_and_unknown(client: TestClient):
    euid_a = _create_tube(client, "bulk-status-a")
    euid_b = _create_tube(client, "bulk-status-b")

    response = client.post(
        "/api/v1/external/containers/status/bulk",
        json={"container_euids": [euid_a, euid_b, "CNT-DOES-NOT-EXIST"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["requested_count"] == 3
    assert payload["found_count"] >= 2
    assert payload["statuses"][euid_a]
    assert payload["statuses"][euid_b]
    assert payload["statuses"]["CNT-DOES-NOT-EXIST"] == "unknown"

    items = {row["container_euid"]: row["status"] for row in payload["items"]}
    assert items[euid_a] == payload["statuses"][euid_a]
    assert items[euid_b] == payload["statuses"][euid_b]
    assert items["CNT-DOES-NOT-EXIST"] == "unknown"


def test_bulk_container_status_rejects_empty_payload(client: TestClient):
    response = client.post(
        "/api/v1/external/containers/status/bulk",
        json={"container_euids": []},
    )
    assert response.status_code == 422

