"""Tests for Atlas lookup path preference, fallback, and cache staleness behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import bloom_lims.integrations.atlas.client as atlas_client_mod
import bloom_lims.integrations.atlas.service as atlas_service_mod
from bloom_lims.integrations.atlas.client import AtlasClient, AtlasClientError
from bloom_lims.integrations.atlas.service import AtlasService


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_atlas_client_prefers_integration_lookup_path(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None, verify=None):
        calls.append(url)
        return _FakeResponse(200, {"order_number": "ORD-100"})

    monkeypatch.setattr(atlas_client_mod.requests, "get", fake_get)
    client = AtlasClient(base_url="https://atlas.example.org", token="tok")

    payload = client.get_order("ORD-100")
    assert payload["order_number"] == "ORD-100"
    assert len(calls) == 1
    assert calls[0].endswith("/api/integrations/bloom/v1/lookups/orders/ORD-100")


def test_atlas_client_falls_back_to_legacy_lookup_path(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None, verify=None):
        calls.append(url)
        if url.endswith("/api/integrations/bloom/v1/lookups/orders/ORD-101"):
            return _FakeResponse(404, {"detail": "not found"})
        return _FakeResponse(200, {"order_number": "ORD-101"})

    monkeypatch.setattr(atlas_client_mod.requests, "get", fake_get)
    client = AtlasClient(base_url="https://atlas.example.org", token="tok")

    payload = client.get_order("ORD-101")
    assert payload["order_number"] == "ORD-101"
    assert len(calls) == 2
    assert calls[0].endswith("/api/integrations/bloom/v1/lookups/orders/ORD-101")
    assert calls[1].endswith("/api/orders/ORD-101")


def test_atlas_service_returns_stale_cached_payload_on_upstream_error(monkeypatch):
    AtlasService._cache.clear()
    settings = SimpleNamespace(
        atlas=SimpleNamespace(
            base_url="https://atlas.example.org",
            token="tok",
            timeout_seconds=5,
            verify_ssl=True,
            cache_ttl_seconds=600,
        )
    )
    monkeypatch.setattr(atlas_service_mod, "get_settings", lambda: settings)

    first_payload = {"order_number": "ORD-200"}
    calls = {"count": 0}

    def fake_get_order(self, order_number):
        calls["count"] += 1
        if calls["count"] == 1:
            return first_payload
        raise AtlasClientError("upstream timeout")

    monkeypatch.setattr(atlas_client_mod.AtlasClient, "get_order", fake_get_order)

    service = AtlasService()
    fresh = service.get_order("ORD-200")
    AtlasService._cache["order:ORD-200"].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    stale = service.get_order("ORD-200")

    assert fresh.payload == first_payload
    assert fresh.from_cache is False
    assert fresh.stale is False

    assert stale.payload == first_payload
    assert stale.from_cache is True
    assert stale.stale is True
    assert isinstance(stale.fetched_at, datetime)
    assert stale.fetched_at.tzinfo == UTC
