"""Atlas-facing Bloom workflow contract tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import bloom_lims.domain.external_specimens as external_domain
import bloom_lims.integrations.atlas.events as events_mod
from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.config import AtlasSettings
from bloom_lims.integrations.atlas.events import AtlasEventClient

pytestmark = pytest.mark.skip(
    reason="Bloom accessioning workflow contracts are retired; Atlas owns accessioning."
)


os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


def _suffix(nbytes: int = 4) -> str:
    return secrets.token_hex(nbytes)


def _opaque(prefix: str, nbytes: int = 8) -> str:
    return f"{prefix}-{_suffix(nbytes)}"


class _FakeAtlasLookupService:
    def _result(self):
        return SimpleNamespace(
            from_cache=False, stale=False, fetched_at=datetime.now(UTC)
        )

    def get_required_tenant_id(self):
        return "00000000-0000-0000-0000-000000000001"

    def get_order(self, order_euid: str):
        return self._result()

    def get_patient(self, patient_id: str):
        return self._result()

    def get_shipment(self, shipment_euid: str):
        return self._result()

    def get_testkit(self, kit_barcode: str):
        return self._result()

    def get_container_trf_context(
        self, container_euid: str, *, tenant_id: str | None = None
    ):
        _ = container_euid
        _ = tenant_id
        return SimpleNamespace(
            payload={
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "order": {},
                "patient": {},
                "test_orders": [],
                "links": {},
            },
            from_cache=False,
            stale=False,
            fetched_at=datetime.now(UTC),
        )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _token_user() -> APIUser:
    return APIUser(
        email="atlas-contract@example.com",
        user_id=_opaque("user"),
        roles=["READ_WRITE"],
        auth_source="token",
        is_service_account=True,
        token_scope="internal_rw",
        token_id=_opaque("token"),
    )


def _resolve_tube_template(client: TestClient) -> tuple[str, str]:
    response = client.get(
        "/api/v1/object-creation/subtypes",
        params={"category": "container", "type": "tube"},
    )
    assert response.status_code == 200
    subtypes = response.json()["subtypes"]
    assert subtypes

    preferred = None
    for item in subtypes:
        if item["name"] == "tube-generic-10ml":
            preferred = item
            break
    selected = preferred or subtypes[0]
    versions = selected.get("versions", [])
    assert versions
    version = "1.0" if "1.0" in versions else versions[0]
    return selected["name"], version


def _create_container(client: TestClient, *, name: str) -> dict:
    subtype, version = _resolve_tube_template(client)
    response = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": "container",
            "type": "tube",
            "subtype": subtype,
            "version": version,
            "name": name,
            "properties": {"name": name},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_specimen_payload(
    *,
    order_euid: str,
    patient_id: str,
    container_euid: str | None = None,
) -> dict:
    payload = {
        "specimen_template_code": "content/specimen/blood-whole/1.0",
        "specimen_name": f"specimen-{_suffix()}",
        "status": "active",
        "properties": {"source": "atlas-contract-test"},
        "atlas_refs": {
            "order_euid": order_euid,
            "patient_id": patient_id,
            "kit_barcode": f"KIT-{_suffix(3)}",
        },
    }
    if container_euid:
        payload["container_euid"] = container_euid
    else:
        payload["container_template_code"] = "container/tube/tube-generic-10ml/1.0"
    return payload


def _create_specimen(
    client: TestClient, *, payload: dict, idempotency_key: str
) -> dict:
    response = client.post(
        "/api/v1/external/specimens",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        external_domain, "AtlasService", lambda: _FakeAtlasLookupService()
    )
    app.dependency_overrides[require_external_token_auth] = _token_user
    return TestClient(app)


def test_create_empty_container_via_object_creation_contract(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = _create_container(client, name=f"atlas-contract-{_suffix()}")
        assert created["euid"]
        assert "uuid" not in created
        assert created["category"] == "container"
        assert created["type"] == "tube"
        assert created["subtype"]


def test_put_container_accepts_metadata(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = _create_container(client, name=f"atlas-patch-{_suffix()}")
        euid = created["euid"]
        response = client.put(
            f"/api/v1/containers/{euid}",
            json={"status": "in_progress", "metadata": {"atlas_sync": "ok"}},
        )
        assert response.status_code == 200, response.text

        fetched = client.get(f"/api/v1/containers/{euid}")
        assert fetched.status_code == 200
        payload = fetched.json()
        assert payload["status"] == "in_progress"
        assert payload["json_addl"]["properties"]["metadata"]["atlas_sync"] == "ok"


def test_create_specimen_with_existing_container_contract(monkeypatch):
    with _build_client(monkeypatch) as client:
        container = _create_container(
            client, name=f"atlas-existing-container-{_suffix()}"
        )
        specimen = _create_specimen(
            client,
            payload=_create_specimen_payload(
                order_euid=f"ORD-{_suffix()}",
                patient_id=f"PAT-{_suffix()}",
                container_euid=container["euid"],
            ),
            idempotency_key=_opaque("idem", 16),
        )
        assert specimen["specimen_euid"]
        assert specimen["container_euid"] == container["euid"]
        assert specimen["atlas_refs"]["order_euid"].startswith("ORD-")
        assert "atlas_refs" not in specimen["properties"]
        assert "atlas_validation" not in specimen["properties"]


def test_container_context_validation_mismatch_returns_400(monkeypatch):
    class _ContextMismatchAtlasService(_FakeAtlasLookupService):
        def get_container_trf_context(
            self, container_euid: str, *, tenant_id: str | None = None
        ):
            _ = container_euid
            _ = tenant_id
            return SimpleNamespace(
                payload={
                    "tenant_id": "00000000-0000-0000-0000-000000000001",
                    "order": {"order_euid": "ORD-CONTEXT"},
                    "patient": {"patient_id": "PAT-CONTEXT"},
                    "test_orders": [],
                    "links": {"testkit_barcode": "KIT-CONTEXT"},
                },
                from_cache=False,
                stale=False,
                fetched_at=datetime.now(UTC),
            )

    monkeypatch.setattr(
        external_domain, "AtlasService", lambda: _ContextMismatchAtlasService()
    )
    app.dependency_overrides[require_external_token_auth] = _token_user

    with TestClient(app) as client:
        container = _create_container(
            client, name=f"atlas-context-mismatch-{_suffix()}"
        )
        response = client.post(
            "/api/v1/external/specimens",
            headers={"Idempotency-Key": _opaque("idem", 16)},
            json={
                "specimen_template_code": "content/specimen/blood-whole/1.0",
                "specimen_name": "context-mismatch",
                "container_euid": container["euid"],
                "status": "active",
                "properties": {"source": "atlas-contract-test"},
                "atlas_refs": {
                    "order_euid": "ORD-DIFFERENT",
                    "patient_id": "PAT-DIFFERENT",
                    "kit_barcode": "KIT-DIFFERENT",
                },
            },
        )

    assert response.status_code == 400
    assert "mismatch" in response.json()["detail"].lower()


def test_container_context_summary_is_projected_through_explicit_reference_objects(
    monkeypatch,
):
    class _ContextMatchingAtlasService(_FakeAtlasLookupService):
        def get_container_trf_context(
            self, container_euid: str, *, tenant_id: str | None = None
        ):
            _ = container_euid
            _ = tenant_id
            return SimpleNamespace(
                payload={
                    "tenant_id": "00000000-0000-0000-0000-000000000001",
                    "order": {"order_euid": "ORD-MATCH"},
                    "patient": {"patient_id": "PAT-MATCH"},
                    "test_orders": [
                        {"test_order_id": "TO-1"},
                        {"test_order_id": "TO-2"},
                    ],
                    "links": {
                        "testkit_barcode": "KIT-MATCH",
                        "shipment_euid": "SHIP-MATCH",
                    },
                },
                from_cache=False,
                stale=False,
                fetched_at=datetime.now(UTC),
            )

    monkeypatch.setattr(
        external_domain, "AtlasService", lambda: _ContextMatchingAtlasService()
    )
    app.dependency_overrides[require_external_token_auth] = _token_user

    with TestClient(app) as client:
        container = _create_container(client, name=f"atlas-context-match-{_suffix()}")
        created = _create_specimen(
            client,
            payload={
                "specimen_template_code": "content/specimen/blood-whole/1.0",
                "specimen_name": "context-match",
                "container_euid": container["euid"],
                "status": "active",
                "properties": {"source": "atlas-contract-test"},
                "atlas_refs": {
                    "order_euid": "ORD-MATCH",
                    "patient_id": "PAT-MATCH",
                    "kit_barcode": "KIT-MATCH",
                    "shipment_euid": "SHIP-MATCH",
                },
            },
            idempotency_key=_opaque("idem", 16),
        )

    assert created["atlas_refs"]["order_euid"] == "ORD-MATCH"
    assert created["atlas_refs"]["patient_id"] == "PAT-MATCH"
    assert created["atlas_refs"]["kit_barcode"] == "KIT-MATCH"
    assert created["atlas_refs"]["shipment_euid"] == "SHIP-MATCH"
    assert "atlas_refs" not in created["properties"]
    assert "atlas_validation" not in created["properties"]


def test_create_specimen_auto_container_contract(monkeypatch):
    with _build_client(monkeypatch) as client:
        specimen = _create_specimen(
            client,
            payload=_create_specimen_payload(
                order_euid=f"ORD-{_suffix()}",
                patient_id=f"PAT-{_suffix()}",
            ),
            idempotency_key=_opaque("idem", 16),
        )
        assert specimen["specimen_euid"]
        assert specimen["container_euid"]


def test_get_patch_delete_specimen_contract_sequence(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = _create_specimen(
            client,
            payload=_create_specimen_payload(
                order_euid=f"ORD-{_suffix()}",
                patient_id=f"PAT-{_suffix()}",
            ),
            idempotency_key=_opaque("idem", 16),
        )
        specimen_euid = created["specimen_euid"]

        fetched = client.get(f"/api/v1/external/specimens/{specimen_euid}")
        assert fetched.status_code == 200
        assert fetched.json()["specimen_euid"] == specimen_euid

        patched = client.patch(
            f"/api/v1/external/specimens/{specimen_euid}",
            json={"status": "inactive", "properties": {"qc_state": "failed"}},
        )
        assert patched.status_code == 200
        assert patched.json()["status"] == "inactive"

        deleted = client.delete(f"/api/v1/content/{specimen_euid}")
        assert deleted.status_code == 200
        assert deleted.json()["success"] is True

        missing = client.get(f"/api/v1/external/specimens/{specimen_euid}")
        assert missing.status_code == 404


def test_lookup_specimens_by_reference_order_euid(monkeypatch):
    with _build_client(monkeypatch) as client:
        order_euid = f"ORD-{_suffix()}"
        created = _create_specimen(
            client,
            payload=_create_specimen_payload(
                order_euid=order_euid,
                patient_id=f"PAT-{_suffix()}",
            ),
            idempotency_key=_opaque("idem", 16),
        )
        lookup = client.get(
            "/api/v1/external/specimens/by-reference",
            params={"order_euid": order_euid},
        )
        assert lookup.status_code == 200
        items = lookup.json()["items"]
        assert any(item["specimen_euid"] == created["specimen_euid"] for item in items)


def test_unsupported_template_returns_validation_error(monkeypatch):
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/api/v1/external/specimens",
            json={
                "specimen_template_code": "content/specimen/saliva/1.0",
                "specimen_name": "unsupported-template",
                "status": "active",
                "atlas_refs": {"patient_id": f"PAT-{_suffix()}"},
            },
            headers={"Idempotency-Key": _opaque("idem", 16)},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert (
            "template" in detail.lower()
            or "failed to create specimen instance" in detail.lower()
        )


def test_event_emitter_signs_and_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["verify"] = verify
        return SimpleNamespace(status_code=202, text="accepted")

    monkeypatch.setattr(events_mod.requests, "post", fake_post)
    settings = AtlasSettings(
        base_url="https://atlas.example.org",
        token="",
        verify_ssl=True,
        events_enabled=True,
        organization_id="00000000-0000-0000-0000-000000000001",
        webhook_secret="super-secret",
        events_path="/api/integrations/bloom/v1/events",
        events_timeout_seconds=9,
        events_max_retries=0,
    )

    event_id = AtlasEventClient(settings).emit(
        event_type="specimen.updated",
        payload={"euid": "SP-1", "status": "active"},
    )
    assert event_id
    assert (
        captured["url"] == "https://atlas.example.org/api/integrations/bloom/v1/events"
    )
    assert captured["timeout"] == 9

    raw = captured["data"]
    body = json.loads(raw.decode("utf-8"))
    assert body["organization_id"] == "00000000-0000-0000-0000-000000000001"
    assert body["event_type"] == "specimen.updated"
    assert body["event_id"] == event_id
    assert body["payload"]["euid"] == "SP-1"

    expected_sig = hmac.new(b"super-secret", raw, hashlib.sha256).hexdigest()
    assert captured["headers"]["X-Bloom-Event-Id"] == event_id
    assert captured["headers"]["X-Bloom-Signature"] == f"sha256={expected_sig}"


def test_event_delivery_failure_is_fail_open(monkeypatch):
    monkeypatch.setattr(
        external_domain, "AtlasService", lambda: _FakeAtlasLookupService()
    )
    app.dependency_overrides[require_external_token_auth] = _token_user

    failing_settings = SimpleNamespace(
        atlas=AtlasSettings(
            base_url="https://atlas.example.org",
            token="",
            verify_ssl=True,
            events_enabled=True,
            organization_id="00000000-0000-0000-0000-000000000001",
            webhook_secret="super-secret",
            events_path="/api/integrations/bloom/v1/events",
            events_timeout_seconds=3,
            events_max_retries=1,
        )
    )
    monkeypatch.setattr(events_mod, "get_settings", lambda: failing_settings)

    def fake_post(*args, **kwargs):
        raise requests.RequestException("atlas unavailable")

    monkeypatch.setattr(events_mod.requests, "post", fake_post)

    with TestClient(app) as client:
        created = _create_container(client, name=f"atlas-fail-open-{_suffix()}")
        assert created["euid"]
        fetched = client.get(f"/api/v1/containers/{created['euid']}")
        assert fetched.status_code == 200
