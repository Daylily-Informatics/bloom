"""HTTP client for Atlas API lookups and test status pushes."""

from __future__ import annotations

import logging
from typing import Any

import requests


logger = logging.getLogger(__name__)


class AtlasClientError(Exception):
    """Raised for Atlas connectivity or API contract errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        path: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.path = path


def _require_https_url(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        raise AtlasClientError(f"{field_name} is required")
    if not normalized.startswith("https://"):
        raise AtlasClientError(f"{field_name} must use an absolute https:// URL")
    return normalized


class AtlasClient:
    """Simple Atlas API client wrapper with explicit lookup methods."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: int = 10,
        verify_ssl: bool = True,
    ):
        self.base_url = _require_https_url(base_url, field_name="Atlas base URL")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def get_trf(self, trf_euid: str) -> dict[str, Any]:
        return self._get_json(f"/api/integrations/bloom/v1/lookups/trfs/{trf_euid}")

    def get_order(self, order_euid: str) -> dict[str, Any]:
        return self._get_json(f"/api/integrations/bloom/v1/lookups/orders/{order_euid}")

    def get_patient(self, patient_id: str) -> dict[str, Any]:
        return self._get_json(f"/api/integrations/bloom/v1/lookups/patients/{patient_id}")

    def get_shipment(self, shipment_euid: str) -> dict[str, Any]:
        return self._get_json(f"/api/integrations/bloom/v1/lookups/shipments/{shipment_euid}")

    def get_testkit(self, kit_barcode: str) -> dict[str, Any]:
        return self._get_json(f"/api/integrations/bloom/v1/lookups/testkits/{kit_barcode}")

    def get_container_trf_context(self, container_euid: str, tenant_id: str) -> dict[str, Any]:
        path = f"/api/integrations/bloom/v1/lookups/containers/{container_euid}/trf-context"
        clean_tenant = str(tenant_id or "").strip()
        if not clean_tenant:
            raise AtlasClientError("Atlas tenant ID is required for container TRF context lookup", path=path)
        return self._get_json(
            path,
            extra_headers={"X-Atlas-Tenant-Id": clean_tenant},
        )

    def get_graph_data(
        self,
        *,
        start_euid: str,
        depth: int,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        path = f"/api/graph/data?start_euid={start_euid}&depth={int(depth)}"
        clean_tenant = str(tenant_id or "").strip()
        if clean_tenant:
            path = f"{path}&tenant_id={clean_tenant}"
        return self._get_json(path)

    def get_graph_object_detail(
        self,
        *,
        euid: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        path = f"/api/graph/object/{euid}"
        clean_tenant = str(tenant_id or "").strip()
        if clean_tenant:
            path = f"{path}?tenant_id={clean_tenant}"
        return self._get_json(path)

    def push_test_status_event(
        self,
        *,
        test_euid: str,
        tenant_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        path = f"/api/integrations/bloom/v1/tests/{test_euid}/status-events"
        clean_tenant = str(tenant_id or "").strip()
        clean_idempotency = str(idempotency_key or "").strip()
        if not clean_tenant:
            raise AtlasClientError("Atlas tenant ID is required for status events", path=path)
        if not clean_idempotency:
            raise AtlasClientError("Idempotency key is required for status events", path=path)
        return self._post_json(
            path,
            payload,
            extra_headers={
                "X-Atlas-Tenant-Id": clean_tenant,
                "Idempotency-Key": clean_idempotency,
            },
            timeout_seconds=timeout_seconds,
        )

    def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if extra_headers:
            for key, value in extra_headers.items():
                if value is None:
                    continue
                headers[key] = value
        return headers

    def _get_json(
        self,
        path: str,
        *,
        extra_headers: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise AtlasClientError("Atlas client is not configured")
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(extra_headers),
                timeout=timeout_seconds or self.timeout_seconds,
                verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            raise AtlasClientError(f"Atlas request failed: {exc}", path=path) from exc
        if response.status_code >= 400:
            self._raise_http_error("GET", path, response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AtlasClientError("Atlas response was not valid JSON", path=path) from exc
        if not isinstance(payload, dict):
            raise AtlasClientError("Atlas response must be a JSON object", path=path)
        return payload

    def _post_json(
        self,
        path: str,
        data: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise AtlasClientError("Atlas client is not configured")
        url = f"{self.base_url}{path}"
        try:
            response = requests.post(
                url,
                headers=self._headers(extra_headers),
                json=data,
                timeout=timeout_seconds or self.timeout_seconds,
                verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            raise AtlasClientError(f"Atlas request failed: {exc}", path=path) from exc
        if response.status_code >= 400:
            self._raise_http_error("POST", path, response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AtlasClientError("Atlas response was not valid JSON", path=path) from exc
        if not isinstance(payload, dict):
            raise AtlasClientError("Atlas response must be a JSON object", path=path)
        return payload

    def _raise_http_error(self, method: str, path: str, response: requests.Response) -> None:
        status_code = int(response.status_code)
        detail = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("message") or payload.get("error") or "").strip()
        if not detail:
            detail = str(response.text or "").strip()
        if len(detail) > 200:
            detail = f"{detail[:200]}..."

        message = f"Atlas {method} {path} failed with status {status_code}"
        if detail:
            message = f"{message}: {detail}"
        raise AtlasClientError(message, status_code=status_code, path=path)
