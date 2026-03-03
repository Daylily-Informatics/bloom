"""Atlas lookup service with short TTL caching."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from bloom_lims.config import get_settings
from bloom_lims.integrations.atlas.client import AtlasClient, AtlasClientError
from bloom_lims.integrations.atlas.contracts import AtlasLookupResult


class AtlasDependencyError(Exception):
    """Raised when Atlas validation cannot be completed safely."""


@dataclass
class _CacheEntry:
    payload: dict[str, Any]
    fetched_at: datetime
    expires_at: datetime


class AtlasService:
    """Atlas-backed validation service for external references."""

    _cache: dict[str, _CacheEntry] = {}
    _cache_lock = threading.Lock()

    def __init__(self):
        settings = get_settings()
        self.client = AtlasClient(
            base_url=settings.atlas.base_url,
            token=settings.atlas.token,
            timeout_seconds=settings.atlas.timeout_seconds,
            verify_ssl=settings.atlas.verify_ssl,
        )
        self.cache_ttl_seconds = max(1, int(settings.atlas.cache_ttl_seconds))

    def get_order(self, order_number: str) -> AtlasLookupResult:
        key = f"order:{order_number}"
        return self._cached_lookup(key, lambda: self.client.get_order(order_number))

    def get_patient(self, patient_id: str) -> AtlasLookupResult:
        key = f"patient:{patient_id}"
        return self._cached_lookup(key, lambda: self.client.get_patient(patient_id))

    def get_shipment(self, shipment_number: str) -> AtlasLookupResult:
        key = f"shipment:{shipment_number}"
        return self._cached_lookup(key, lambda: self.client.get_shipment(shipment_number))

    def get_testkit(self, kit_barcode: str) -> AtlasLookupResult:
        key = f"testkit:{kit_barcode}"
        return self._cached_lookup(key, lambda: self.client.get_testkit(kit_barcode))

    def _cached_lookup(
        self,
        key: str,
        fetcher: Callable[[], dict[str, Any]],
    ) -> AtlasLookupResult:
        now = datetime.now(UTC)
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry and entry.expires_at > now:
                return AtlasLookupResult(
                    key=key,
                    payload=entry.payload,
                    from_cache=True,
                    stale=False,
                    fetched_at=entry.fetched_at,
                )

        try:
            payload = fetcher()
        except AtlasClientError as exc:
            with self._cache_lock:
                entry = self._cache.get(key)
                if entry:
                    return AtlasLookupResult(
                        key=key,
                        payload=entry.payload,
                        from_cache=True,
                        stale=True,
                        fetched_at=entry.fetched_at,
                    )
            raise AtlasDependencyError(str(exc)) from exc

        fetched_at = datetime.now(UTC)
        cache_entry = _CacheEntry(
            payload=payload,
            fetched_at=fetched_at,
            expires_at=fetched_at + timedelta(seconds=self.cache_ttl_seconds),
        )
        with self._cache_lock:
            self._cache[key] = cache_entry
        return AtlasLookupResult(
            key=key,
            payload=payload,
            from_cache=False,
            stale=False,
            fetched_at=fetched_at,
        )
