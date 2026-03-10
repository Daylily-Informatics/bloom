from __future__ import annotations

from types import SimpleNamespace

import pytest

from bloom_lims.config import DeweySettings
from bloom_lims.domain.beta_lab import BetaLabService
from bloom_lims.integrations.dewey.client import DeweyArtifactClient, DeweyClientError


def test_dewey_settings_rejects_non_https_base_url():
    with pytest.raises(ValueError, match="absolute https:// URL"):
        DeweySettings(base_url="http://dewey.example")


def test_dewey_settings_requires_credentials_when_enabled():
    with pytest.raises(ValueError, match="base_url"):
        DeweySettings(enabled=True, token="token-1")
    with pytest.raises(ValueError, match="token"):
        DeweySettings(enabled=True, base_url="https://dewey.example")


def test_dewey_client_rejects_non_https_base_url():
    client = DeweyArtifactClient(base_url="http://dewey.example", token="token-1")
    with pytest.raises(DeweyClientError, match="absolute https:// URL"):
        client.register_artifact(
            artifact_type="fastq",
            storage_uri="s3://bucket/RUN-1/read1.fastq.gz",
        )


def test_dewey_client_rejects_missing_token():
    client = DeweyArtifactClient(base_url="https://dewey.example", token="")
    with pytest.raises(DeweyClientError, match="bearer token"):
        client.register_artifact(
            artifact_type="fastq",
            storage_uri="s3://bucket/RUN-1/read1.fastq.gz",
        )


def test_dewey_client_registers_artifact_with_bearer_auth(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, json=None, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["verify"] = verify
        return SimpleNamespace(
            status_code=200,
            text='{"artifact_euid":"AT-1"}',
            json=lambda: {"artifact_euid": "AT-1"},
        )

    import bloom_lims.integrations.dewey.client as client_mod

    monkeypatch.setattr(client_mod.requests, "post", fake_post)

    client = DeweyArtifactClient(
        base_url="https://dewey.example",
        token="token-1",
        timeout_seconds=7,
        verify_ssl=True,
    )
    artifact_euid = client.register_artifact(
        artifact_type="vcf",
        storage_uri="s3://bucket/RUN-1/sample.vcf.gz",
        metadata={"run_euid": "RUN-1"},
        idempotency_key="idem-1",
    )

    assert artifact_euid == "AT-1"
    assert captured["url"] == "https://dewey.example/api/v1/artifacts/import"
    assert captured["json"] == {
        "artifact_type": "vcf",
        "storage_uri": "s3://bucket/RUN-1/sample.vcf.gz",
        "metadata": {"run_euid": "RUN-1"},
    }
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer token-1"
    assert headers["Idempotency-Key"] == "idem-1"


def test_register_run_artifact_in_dewey_adds_producer_metadata():
    captured: dict[str, object] = {}

    class _FakeDeweyClient:
        def register_artifact(self, **kwargs):
            captured.update(kwargs)
            return "AT-123"

    service = object.__new__(BetaLabService)
    service.dewey_client = _FakeDeweyClient()

    artifact_euid = service._register_run_artifact_in_dewey(
        run_euid="RUN-1",
        artifact_type="fastq",
        storage_uri="s3://bucket/RUN-1/read1.fastq.gz",
        lane="1",
        library_barcode="BC-1",
        metadata={"instrument_euid": "INS-1"},
    )

    assert artifact_euid == "AT-123"
    metadata = captured["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["producer_system"] == "bloom"
    assert metadata["producer_object_euid"] == "RUN-1"
    assert metadata["lane"] == "1"
    assert metadata["library_barcode"] == "BC-1"
    assert metadata["instrument_euid"] == "INS-1"


def test_register_run_artifact_in_dewey_is_noop_when_integration_disabled():
    service = object.__new__(BetaLabService)
    service.dewey_client = None

    artifact_euid = service._register_run_artifact_in_dewey(
        run_euid="RUN-1",
        artifact_type="fastq",
        storage_uri="s3://bucket/RUN-1/read1.fastq.gz",
        lane=None,
        library_barcode=None,
        metadata={},
    )

    assert artifact_euid is None
