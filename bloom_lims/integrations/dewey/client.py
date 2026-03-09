"""Authenticated HTTPS client for Bloom -> Dewey artifact registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


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

    def register_artifact(
        self,
        *,
        artifact_type: str,
        storage_uri: str,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        url = f"{_require_https_url(self.base_url, field_name='Dewey base URL')}/api/v1/artifacts"
        payload = {
            "artifact_type": str(artifact_type or "").strip(),
            "storage_uri": str(storage_uri or "").strip(),
            "metadata": dict(metadata or {}),
        }
        if not payload["artifact_type"]:
            raise DeweyClientError("artifact_type is required")
        if not payload["storage_uri"]:
            raise DeweyClientError("storage_uri is required")

        headers = self._headers()
        clean_idempotency = str(idempotency_key or "").strip()
        if clean_idempotency:
            headers["Idempotency-Key"] = clean_idempotency

        try:
            response = requests.post(
                url,
                json=payload,
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
