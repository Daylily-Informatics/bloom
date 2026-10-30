"""Authenticated HTTPS client for Bloom -> Dewey artifact registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from daylily_tapdb.web.dag_v2 import validate_dag_v2_manifest


class DeweyClientError(RuntimeError):
    """Raised when Dewey integration requests fail."""


def _require_https_url(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        raise DeweyClientError(f"{field_name} is required")
    if not normalized.startswith("https://"):
        raise DeweyClientError(f"{field_name} must use an absolute https:// URL")
    return normalized


@dataclass
class DeweyArtifactClient:
    """Simple Dewey API client for artifact registration."""

    base_url: str
    token: str
    timeout_seconds: int = 10
    verify_ssl: bool = True

    def _headers(self) -> dict[str, str]:
        token = str(self.token or "").strip()
        if not token:
            raise DeweyClientError("Dewey API bearer token is required")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def require_persisted_artifact(self, artifact_euid: str) -> dict[str, Any]:
        """Verify an exact owner-issued artifact through Dewey's native DAG contract."""
        value = str(artifact_euid or "")
        if not value or value != value.strip():
            raise DeweyClientError("Dewey artifact EUID must be exact")
        base = _require_https_url(self.base_url, field_name="Dewey base URL")
        try:
            manifest_response = requests.get(
                f"{base}/api/dag/manifest", headers=self._headers(),
                timeout=max(1, int(self.timeout_seconds)), verify=self.verify_ssl,
            )
            manifest_response.raise_for_status()
            reason = validate_dag_v2_manifest(
                manifest_response.json(), expected_service_id="dewey"
            )
            if reason is not None:
                raise DeweyClientError(f"Dewey native manifest rejected: {reason.value}")
            from urllib.parse import quote

            response = requests.get(
                f"{base}/api/dag/v2/object/{quote(value, safe='')}",
                headers=self._headers(), timeout=max(1, int(self.timeout_seconds)),
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DeweyClientError(f"Dewey native artifact lookup failed: {exc}") from exc
        if (
            not isinstance(body, dict)
            or body.get("service_id") != "dewey"
            or body.get("euid") != value
            or body.get("record_type") != "instance"
            or body.get("category") != "data"
            or body.get("type") != "artifact"
        ):
            raise DeweyClientError("Dewey native object is not the exact artifact")
        return body

    def register_artifact(
        self,
        *,
        artifact_type: str,
        storage_uri: str,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        payload = {
            "artifact_type": str(artifact_type or "").strip(),
            "storage_uri": str(storage_uri or "").strip(),
            "metadata": dict(metadata or {}),
        }
        if not payload["artifact_type"]:
            raise DeweyClientError("artifact_type is required")
        if not payload["storage_uri"]:
            raise DeweyClientError("storage_uri is required")
        parsed = urlparse(payload["storage_uri"])
        if str(parsed.scheme or "").strip().lower() != "s3":
            raise DeweyClientError("storage_uri must use an s3:// URL")
        bucket = str(parsed.netloc or "").strip()
        key = str(parsed.path or "").lstrip("/")
        if not bucket or not key:
            raise DeweyClientError("storage_uri must include both bucket and key")

        headers = self._headers()
        clean_idempotency = str(idempotency_key or "").strip()
        if clean_idempotency:
            headers["Idempotency-Key"] = clean_idempotency
        request_payload = {
            "artifact_type": payload["artifact_type"],
            "storage_backend": "s3",
            "bucket": bucket,
            "key": key,
            "producer_system": str((payload["metadata"] or {}).get("producer_system") or "").strip()
            or None,
            "producer_object_euid": str(
                (payload["metadata"] or {}).get("producer_object_euid") or ""
            ).strip()
            or None,
            "metadata": payload["metadata"],
        }

        try:
            response = requests.post(
                f"{_require_https_url(self.base_url, field_name='Dewey base URL')}/api/v1/artifacts",
                json=request_payload,
                headers=headers,
                timeout=max(1, int(self.timeout_seconds)),
                verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            raise DeweyClientError(f"Dewey request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = str(response.text or "").strip()
            raise DeweyClientError(
                f"Dewey register artifact failed ({response.status_code}): {detail}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise DeweyClientError("Dewey returned non-JSON artifact response") from exc
        if not isinstance(body, dict):
            raise DeweyClientError("Dewey returned invalid artifact response shape")
        artifact_euid = str(body.get("artifact_euid") or "").strip()
        if not artifact_euid:
            raise DeweyClientError("Dewey artifact response missing artifact_euid")
        return artifact_euid
