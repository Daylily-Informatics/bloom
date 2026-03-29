from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app
from bloom_lims import observability_routes
from bloom_lims.anomalies import AnomalyRecord, TapdbAnomalyRepository
from bloom_lims.gui.routes import operations


class _FakeSession:
    def add(self, _obj) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


def _build_fake_repository() -> TapdbAnomalyRepository:
    repository = TapdbAnomalyRepository(_FakeSession())
    instances: list[SimpleNamespace] = []
    counter = {"value": 0}

    def create_instance(*, template_code: str, name: str, properties: dict, session) -> SimpleNamespace:
        counter["value"] += 1
        category, type_name, subtype, version = template_code.strip("/").split("/")
        instance = SimpleNamespace(
            euid=f"BAN-{counter['value']:04d}",
            name=name,
            json_addl={"properties": properties},
            created_dt=datetime.now(UTC),
            category=category,
            type=type_name,
            subtype=subtype,
            version=version,
            is_deleted=False,
        )
        instances.append(instance)
        return instance

    repository._ensure_templates = lambda: None  # type: ignore[method-assign]
    repository._instances = lambda: list(instances)  # type: ignore[method-assign]
    repository.factory = SimpleNamespace(create_instance=create_instance)
    return repository


def _sample_record() -> AnomalyRecord:
    now = datetime.now(UTC).isoformat()
    return AnomalyRecord(
        id="BAN-0001",
        service="bloom",
        environment="dev",
        category="database",
        severity="error",
        fingerprint="db-fingerprint",
        summary="Bloom database probe failed",
        first_seen_at=now,
        last_seen_at=now,
        occurrence_count=2,
        redacted_context={"token": "[redacted]", "sql": "[redacted-sql]"},
        source_view_url="/admin/anomalies/BAN-0001",
    )


class _StubRepository:
    def __init__(self):
        self._record = _sample_record()

    def list(self, *, skip: int = 0, limit: int = 100):
        return [self._record][skip : skip + limit]

    def get(self, anomaly_id: str):
        if anomaly_id == self._record.id:
            return self._record
        return None

    def projection(self):
        return SimpleNamespace(
            observed_at=self._record.last_seen_at,
            model_dump=lambda: {
                "state": "ready",
                "stale": False,
                "observed_at": self._record.last_seen_at,
                "last_synced_at": self._record.last_seen_at,
                "detail": None,
            },
        )


class _StubBloomDB:
    def __init__(self, app_username: str = ""):
        self.app_username = app_username
        self.session = None

    def close(self) -> None:
        return None


def test_anomaly_repository_upserts_and_redacts_context() -> None:
    repository = _build_fake_repository()
    context = {
        "authorization": "Bearer super-secret-token",
        "nested": {
            "cookie": "session=abc123",
            "path": "/documents/123456/details",
            "sql": "SELECT * FROM users WHERE id = 123456",
        },
        "items": [{"password": "open-sesame"}, "/patients/987654321"],
    }

    first = repository.record(
        category="database",
        severity="error",
        fingerprint="db-fingerprint",
        summary="Bloom database probe failed",
        redacted_context=context,
    )
    second = repository.record(
        category="database",
        severity="error",
        fingerprint="db-fingerprint",
        summary="Bloom database probe failed",
        redacted_context=context,
    )

    assert first.id == second.id
    assert len(repository.list()) == 1
    assert second.occurrence_count == 2
    assert second.redacted_context["authorization"] == "[redacted]"
    assert second.redacted_context["nested"]["cookie"] == "[redacted]"
    assert second.redacted_context["nested"]["path"] == "/documents/{id}/details"
    assert second.redacted_context["nested"]["sql"] == "[redacted-sql]"
    assert second.redacted_context["items"][0]["password"] == "[redacted]"
    assert second.redacted_context["items"][1] == "/patients/{id}"


def test_anomaly_api_lists_and_reads_records(monkeypatch) -> None:
    monkeypatch.setattr(
        observability_routes,
        "_anomaly_repository",
        lambda _app_username: (_StubBloomDB(), _StubRepository()),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        listing = client.get("/api/anomalies")
        detail = client.get("/api/anomalies/BAN-0001")
        missing = client.get("/api/anomalies/BAN-DOES-NOT-EXIST")

    assert listing.status_code == 200
    payload = listing.json()
    assert payload["service"] == "bloom"
    assert payload["projection"]["state"] == "ready"
    assert payload["count"] == 1
    assert payload["items"][0]["redacted_context"]["token"] == "[redacted]"

    assert detail.status_code == 200
    assert detail.json()["item"]["id"] == "BAN-0001"

    assert missing.status_code == 404


def test_admin_anomalies_views_render(monkeypatch) -> None:
    monkeypatch.setattr(operations, "BLOOMdb3", _StubBloomDB)
    monkeypatch.setattr(operations, "TapdbAnomalyRepository", lambda _session: _StubRepository())

    with TestClient(app, raise_server_exceptions=False) as client:
        listing = client.get("/admin/anomalies")
        detail = client.get("/admin/anomalies/BAN-0001")
        missing = client.get("/admin/anomalies/BAN-DOES-NOT-EXIST")

    assert listing.status_code == 200
    assert "Operational Anomalies" in listing.text
    assert "Bloom database probe failed" in listing.text

    assert detail.status_code == 200
    assert "BAN-0001" in detail.text
    assert "[redacted]" in detail.text

    assert missing.status_code == 404
