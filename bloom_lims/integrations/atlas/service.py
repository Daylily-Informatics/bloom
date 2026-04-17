"""Atlas lookup service with short TTL caching."""

from __future__ import annotations

import hashlib
import random
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from bloom_lims.config import get_settings
from bloom_lims.integrations.atlas.client import AtlasClient, AtlasClientError
from bloom_lims.integrations.atlas.contracts import (
    AtlasLookupResult,
    AtlasStatusEventPushResult,
)


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
        self.atlas_tenant_id = str(settings.atlas.organization_id or "").strip()
        self.status_events_timeout_seconds = max(
            1,
            int(
                getattr(
                    settings.atlas,
                    "status_events_timeout_seconds",
                    settings.atlas.timeout_seconds,
                )
            ),
        )
        self.status_events_max_retries = max(
            0,
            int(getattr(settings.atlas, "status_events_max_retries", 5)),
        )
        self.status_events_backoff_base_seconds = max(
            0.05,
            float(getattr(settings.atlas, "status_events_backoff_base_seconds", 0.5)),
        )
        # Keep retry backoff bounded near guidance defaults (0.5, 1, 2, 4).
        self.status_events_backoff_max_seconds = max(
            self.status_events_backoff_base_seconds,
            self.status_events_backoff_base_seconds * 8.0,
        )

    def get_trf(self, trf_euid: str) -> AtlasLookupResult:
        key = f"trf:{trf_euid}"
        return self._cached_lookup(key, lambda: self.client.get_trf(trf_euid))

    def get_order(self, order_euid: str) -> AtlasLookupResult:
        key = f"order:{order_euid}"
        return self._cached_lookup(key, lambda: self.client.get_order(order_euid))

    def get_patient(self, patient_id: str) -> AtlasLookupResult:
        key = f"patient:{patient_id}"
        return self._cached_lookup(key, lambda: self.client.get_patient(patient_id))

    def get_shipment(self, shipment_euid: str) -> AtlasLookupResult:
        key = f"shipment:{shipment_euid}"
        return self._cached_lookup(key, lambda: self.client.get_shipment(shipment_euid))

    def get_testkit(self, kit_barcode: str) -> AtlasLookupResult:
        key = f"testkit:{kit_barcode}"
        return self._cached_lookup(key, lambda: self.client.get_testkit(kit_barcode))

    def get_container_trf_context(
        self,
        container_euid: str,
        *,
        tenant_id: str | None = None,
    ) -> AtlasLookupResult:
        resolved_tenant = str(tenant_id or self.get_required_tenant_id()).strip()
        key = f"container_trf_context:{resolved_tenant}:{container_euid}"
        return self._cached_lookup(
            key,
            lambda: self.client.get_container_trf_context(
                container_euid, resolved_tenant
            ),
        )

    def get_required_tenant_id(self) -> str:
        tenant_id = str(self.atlas_tenant_id or "").strip()
        if not tenant_id:
            raise AtlasDependencyError(
                "Atlas tenant UUID not configured (atlas.organization_id)"
            )
        return tenant_id

    @staticmethod
    def make_status_event_idempotency_key(
        *,
        tenant_id: str,
        test_euid: str,
        event_id: str,
        status: str,
    ) -> str:
        seed = f"{tenant_id}:{test_euid}:{event_id}:{status}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def push_test_status_event(
        self,
        *,
        test_euid: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        tenant_id: str | None = None,
    ) -> AtlasStatusEventPushResult:
        resolved_tenant = str(tenant_id or self.get_required_tenant_id()).strip()
        event_id = str(payload.get("event_id", "")).strip()
        status = str(payload.get("status", "")).strip()
        if not event_id:
            raise ValueError("Status event payload requires event_id")
        if not status:
            raise ValueError("Status event payload requires status")

        resolved_idempotency = str(idempotency_key or "").strip()
        if not resolved_idempotency:
            resolved_idempotency = self.make_status_event_idempotency_key(
                tenant_id=resolved_tenant,
                test_euid=str(test_euid).strip(),
                event_id=event_id,
                status=status,
            )

        retryable_status_codes = {429, 500, 502, 503, 504}
        for attempt in range(self.status_events_max_retries + 1):
            try:
                response_payload = self.client.push_test_status_event(
                    test_euid=str(test_euid).strip(),
                    tenant_id=resolved_tenant,
                    idempotency_key=resolved_idempotency,
                    payload=payload,
                    timeout_seconds=self.status_events_timeout_seconds,
                )
                return AtlasStatusEventPushResult(
                    tenant_id=resolved_tenant,
                    test_euid=str(test_euid).strip(),
                    idempotency_key=resolved_idempotency,
                    payload=response_payload,
                )
            except AtlasClientError as exc:
                if (
                    exc.status_code not in retryable_status_codes
                    or attempt >= self.status_events_max_retries
                ):
                    raise AtlasDependencyError(str(exc)) from exc
                sleep_seconds = self._retry_sleep_seconds(attempt)
                time.sleep(sleep_seconds)

        # Defensive fallback; loop above either returns or raises.
        raise AtlasDependencyError("Failed to push Atlas status event")

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

    def _retry_sleep_seconds(self, attempt: int) -> float:
        base = self.status_events_backoff_base_seconds * (2**attempt)
        capped = min(base, self.status_events_backoff_max_seconds)
        jitter = random.uniform(0, max(capped * 0.1, 0.01))
        return capped + jitter
