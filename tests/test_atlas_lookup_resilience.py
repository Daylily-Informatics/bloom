"""Tests for Atlas lookup path preference, fallback, and cache staleness behavior."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import bloom_lims.integrations.atlas.client as atlas_client_mod
import bloom_lims.integrations.atlas.service as atlas_service_mod
from bloom_lims.integrations.atlas.client import AtlasClient, AtlasClientError
from bloom_lims.integrations.atlas.service import AtlasDependencyError, AtlasService


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_atlas_client_prefers_trf_lookup_path(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None, verify=None):
        calls.append(url)
        return _FakeResponse(200, {"trf_euid": "TRF-100"})

    monkeypatch.setattr(atlas_client_mod.requests, "get", fake_get)
    client = AtlasClient(base_url="https://atlas.example.org", token="tok")

    payload = client.get_trf("TRF-100")
    assert payload["trf_euid"] == "TRF-100"
    assert len(calls) == 1
    assert calls[0].endswith("/api/integrations/bloom/v1/lookups/trfs/TRF-100")


def test_atlas_client_does_not_fall_back_to_legacy_trf_lookup_path(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None, verify=None):
        calls.append(url)
        return _FakeResponse(404, {"detail": "not found"})

    monkeypatch.setattr(atlas_client_mod.requests, "get", fake_get)
    client = AtlasClient(base_url="https://atlas.example.org", token="tok")

    try:
        client.get_trf("TRF-101")
    except AtlasClientError as exc:
        assert exc.status_code == 404
        assert exc.path == "/api/integrations/bloom/v1/lookups/trfs/TRF-101"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected AtlasClientError for 404 lookup response")

    assert len(calls) == 1
    assert calls[0].endswith("/api/integrations/bloom/v1/lookups/trfs/TRF-101")


def test_atlas_service_returns_stale_cached_payload_on_upstream_error(monkeypatch):
    AtlasService._cache.clear()
    settings = SimpleNamespace(
        atlas=SimpleNamespace(
            base_url="https://atlas.example.org",
            token="tok",
            timeout_seconds=5,
            verify_ssl=True,
            cache_ttl_seconds=600,
            organization_id="00000000-0000-0000-0000-000000000001",
            status_events_timeout_seconds=10,
            status_events_max_retries=5,
            status_events_backoff_base_seconds=0.5,
        )
    )
    monkeypatch.setattr(atlas_service_mod, "get_settings", lambda: settings)

    first_payload = {"trf_euid": "TRF-200"}
    calls = {"count": 0}

    def fake_get_trf(self, trf_euid):
        calls["count"] += 1
        if calls["count"] == 1:
            return first_payload
        raise AtlasClientError("upstream timeout")

    monkeypatch.setattr(atlas_client_mod.AtlasClient, "get_trf", fake_get_trf)

    service = AtlasService()
    fresh = service.get_trf("TRF-200")
    AtlasService._cache["trf:TRF-200"].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    stale = service.get_trf("TRF-200")

    assert fresh.payload == first_payload
    assert fresh.from_cache is False
    assert fresh.stale is False

    assert stale.payload == first_payload
    assert stale.from_cache is True
    assert stale.stale is True
    assert isinstance(stale.fetched_at, datetime)
    assert stale.fetched_at.tzinfo == UTC


def test_atlas_client_container_trf_context_sends_tenant_header(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return _FakeResponse(200, {"tenant_id": "tid", "order": {}, "patient": {}, "test_orders": [], "links": {}})

    monkeypatch.setattr(atlas_client_mod.requests, "get", fake_get)
    client = AtlasClient(base_url="https://atlas.example.org", token="tok")
    payload = client.get_container_trf_context("CX-55", "00000000-0000-0000-0000-000000000001")

    assert payload["tenant_id"] == "tid"
    assert captured["url"].endswith("/api/integrations/bloom/v1/lookups/containers/CX-55/trf-context")
    assert captured["headers"]["X-Atlas-Tenant-Id"] == "00000000-0000-0000-0000-000000000001"


def test_atlas_client_test_status_event_push_sends_headers(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, verify=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["json"] = json or {}
        return _FakeResponse(200, {"applied": True, "idempotent_replay": False})

    monkeypatch.setattr(atlas_client_mod.requests, "post", fake_post)
    client = AtlasClient(base_url="https://atlas.example.org", token="tok")
    payload = client.push_test_status_event(
        test_euid="TST-123",
        tenant_id="00000000-0000-0000-0000-000000000001",
        idempotency_key="idem-123",
        payload={"event_id": "evt-1", "status": "IN_PROGRESS"},
    )

    assert payload["applied"] is True
    assert captured["url"].endswith(
        "/api/integrations/bloom/v1/tests/TST-123/status-events"
    )
    assert captured["headers"]["X-Atlas-Tenant-Id"] == "00000000-0000-0000-0000-000000000001"
    assert captured["headers"]["Idempotency-Key"] == "idem-123"
    assert captured["json"]["event_id"] == "evt-1"


def test_atlas_service_generates_deterministic_test_status_idempotency_key():
    key1 = AtlasService.make_status_event_idempotency_key(
        tenant_id="00000000-0000-0000-0000-000000000001",
        test_euid="TST-123",
        event_id="evt-1",
        status="IN_PROGRESS",
    )
    key2 = AtlasService.make_status_event_idempotency_key(
        tenant_id="00000000-0000-0000-0000-000000000001",
        test_euid="TST-123",
        event_id="evt-1",
        status="IN_PROGRESS",
    )
    expected = hashlib.sha256(
        b"00000000-0000-0000-0000-000000000001:TST-123:evt-1:IN_PROGRESS"
    ).hexdigest()
    assert key1 == key2 == expected


def test_atlas_service_retries_status_push_on_retryable_codes(monkeypatch):
    AtlasService._cache.clear()
    settings = SimpleNamespace(
        atlas=SimpleNamespace(
            base_url="https://atlas.example.org",
            token="tok",
            timeout_seconds=5,
            verify_ssl=True,
            cache_ttl_seconds=600,
            organization_id="00000000-0000-0000-0000-000000000001",
            status_events_timeout_seconds=10,
            status_events_max_retries=5,
            status_events_backoff_base_seconds=0.5,
        )
    )
    monkeypatch.setattr(atlas_service_mod, "get_settings", lambda: settings)

    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_push(self, *, test_euid, tenant_id, idempotency_key, payload, timeout_seconds=None):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise AtlasClientError(
                "Atlas POST /status-events failed with status 503",
                status_code=503,
                path="/api/integrations/bloom/v1/tests/x/status-events",
            )
        return {"applied": True, "idempotent_replay": False, "test_euid": test_euid}

    monkeypatch.setattr(atlas_client_mod.AtlasClient, "push_test_status_event", fake_push)
    monkeypatch.setattr(atlas_service_mod.random, "uniform", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(atlas_service_mod.time, "sleep", lambda seconds: sleeps.append(seconds))

    service = AtlasService()
    result = service.push_test_status_event(
        test_euid="TST-1",
        payload={"event_id": "evt-1", "status": "IN_PROGRESS"},
    )

    assert result.payload["applied"] is True
    assert attempts["count"] == 3
    assert sleeps == [0.5, 1.0]


def test_atlas_service_does_not_retry_non_retryable_codes(monkeypatch):
    AtlasService._cache.clear()
    settings = SimpleNamespace(
        atlas=SimpleNamespace(
            base_url="https://atlas.example.org",
            token="tok",
            timeout_seconds=5,
            verify_ssl=True,
            cache_ttl_seconds=600,
            organization_id="00000000-0000-0000-0000-000000000001",
            status_events_timeout_seconds=10,
            status_events_max_retries=5,
            status_events_backoff_base_seconds=0.5,
        )
    )
    monkeypatch.setattr(atlas_service_mod, "get_settings", lambda: settings)

    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_push(self, *, test_euid, tenant_id, idempotency_key, payload, timeout_seconds=None):
        attempts["count"] += 1
        raise AtlasClientError(
            "Atlas POST /status-events failed with status 400",
            status_code=400,
            path="/api/integrations/bloom/v1/tests/x/status-events",
        )

    monkeypatch.setattr(atlas_client_mod.AtlasClient, "push_test_status_event", fake_push)
    monkeypatch.setattr(atlas_service_mod.time, "sleep", lambda seconds: sleeps.append(seconds))

    service = AtlasService()
    try:
        service.push_test_status_event(
            test_euid="TST-1",
            payload={"event_id": "evt-1", "status": "IN_PROGRESS"},
        )
        assert False, "Expected AtlasDependencyError"
    except AtlasDependencyError:
        pass

    assert attempts["count"] == 1
    assert sleeps == []
