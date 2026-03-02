"""HTTP client for Atlas API lookups."""

from __future__ import annotations

import logging
from typing import Any

import requests


logger = logging.getLogger(__name__)


class AtlasClientError(Exception):
    """Raised for Atlas connectivity or API contract errors."""


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
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def get_order(self, order_number: str) -> dict[str, Any]:
        return self._get_json(f"/api/orders/{order_number}")

    def get_patient(self, patient_id: str) -> dict[str, Any]:
        return self._get_json(f"/api/patients/{patient_id}")

    def get_shipment(self, shipment_number: str) -> dict[str, Any]:
        return self._get_json(f"/api/shipments/{shipment_number}")

    def get_testkit(self, kit_barcode: str) -> dict[str, Any]:
        # Preferred direct route if Atlas exposes it.
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

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get_json(self, path: str) -> dict[str, Any]:
        if not self.is_configured:
            raise AtlasClientError("Atlas client is not configured")
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                timeout=self.timeout_seconds,
                verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            raise AtlasClientError(f"Atlas request failed: {exc}") from exc
        if response.status_code >= 400:
            raise AtlasClientError(f"Atlas GET {path} failed with status {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AtlasClientError("Atlas response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise AtlasClientError("Atlas response must be a JSON object")
        return payload

    def _post_json(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured:
            raise AtlasClientError("Atlas client is not configured")
        url = f"{self.base_url}{path}"
        try:
            response = requests.post(
                url,
                headers=self._headers(),
                json=data,
                timeout=self.timeout_seconds,
                verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            raise AtlasClientError(f"Atlas request failed: {exc}") from exc
        if response.status_code >= 400:
            raise AtlasClientError(f"Atlas POST {path} failed with status {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AtlasClientError("Atlas response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise AtlasClientError("Atlas response must be a JSON object")
        return payload

