"""HTTP client for Atlas API lookups."""

from __future__ import annotations

import logging
from typing import Any

import requests

from bloom_lims.security.transport import InsecureTransportError, require_https_url
from bloom_lims.integrations.atlas.tls import resolve_requests_verify

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
        clean_base_url = str(base_url or "").strip()
        if clean_base_url:
            try:
                clean_base_url = require_https_url(clean_base_url, context_label="atlas.base_url")
            except InsecureTransportError as exc:
                raise AtlasClientError(str(exc), path="atlas.base_url") from exc
        self.base_url = clean_base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = resolve_requests_verify(base_url=self.base_url, verify_ssl=bool(verify_ssl))

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _get_with_fallback(self, preferred_path: str, fallback_path: str, *, label: str) -> dict[str, Any]:
        try:
            return self._get_json(preferred_path)
        except AtlasClientError:
            logger.warning(
                "Atlas preferred lookup path failed for %s; falling back to legacy path (%s -> %s)",
                label,
                preferred_path,
                fallback_path,
            )
            return self._get_json(fallback_path)

    def get_order(self, order_number: str) -> dict[str, Any]:
        return self._get_with_fallback(
            f"/api/integrations/bloom/v1/lookups/orders/{order_number}",
            f"/api/orders/{order_number}",
            label="order lookup",
        )

    def get_patient(self, patient_id: str) -> dict[str, Any]:
        return self._get_with_fallback(
            f"/api/integrations/bloom/v1/lookups/patients/{patient_id}",
            f"/api/patients/{patient_id}",
            label="patient lookup",
        )

    def get_shipment(self, shipment_number: str) -> dict[str, Any]:
        return self._get_with_fallback(
            f"/api/integrations/bloom/v1/lookups/shipments/{shipment_number}",
            f"/api/shipments/{shipment_number}",
            label="shipment lookup",
        )

    def get_testkit(self, kit_barcode: str) -> dict[str, Any]:
        # Preferred org-scoped integration lookup route.
        try:
            return self._get_json(f"/api/integrations/bloom/v1/lookups/testkits/{kit_barcode}")
        except AtlasClientError:
            logger.warning(
                "Atlas preferred integration testkit lookup failed; falling back to legacy paths"
            )

        # Secondary fallback direct route if Atlas exposes it.
        try:
            return self._get_json(f"/api/testkits/{kit_barcode}")
        except AtlasClientError:
            logger.debug("Direct Atlas testkit endpoint not available, falling back to search")

        payload = {
            "query": kit_barcode,
            "record_types": ["testkit"],
            "filters": {"barcode": [kit_barcode]},
            "page": 1,
            "page_size": 10,
        }
        result = self._post_json("/api/search/v2/query", payload)
        items = result.get("items", [])
        if not isinstance(items, list):
            raise AtlasClientError("Atlas testkit search returned malformed payload")
        for item in items:
            barcode = (
                item.get("barcode")
                or item.get("kit_barcode")
                or item.get("properties", {}).get("barcode")
            )
            if str(barcode).strip() == str(kit_barcode).strip():
                return item
        if items:
            return items[0]
        raise AtlasClientError(f"Atlas testkit not found for barcode '{kit_barcode}'")

    def get_container_trf_context(self, container_euid: str, tenant_id: str) -> dict[str, Any]:
        path = f"/api/integrations/bloom/v1/lookups/containers/{container_euid}/trf-context"
        clean_tenant = str(tenant_id or "").strip()
        if not clean_tenant:
            raise AtlasClientError("Atlas tenant ID is required for container TRF context lookup", path=path)
        return self._get_json(
            path,
            extra_headers={"X-Atlas-Tenant-Id": clean_tenant},
        )

    def push_test_order_status_event(
        self,
        *,
        test_order_id: str,
        tenant_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        path = f"/api/integrations/bloom/v1/test-orders/{test_order_id}/status-events"
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
