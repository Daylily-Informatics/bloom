"""Outbound Bloom -> Atlas event delivery client."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

import requests

from bloom_lims.config import AtlasSettings, get_settings


logger = logging.getLogger(__name__)


class AtlasEventClient:
    """Signs and posts Bloom events to the Atlas integration webhook."""

    def __init__(self, settings: AtlasSettings | None = None):
        self.settings = settings or get_settings().atlas

    def _endpoint(self) -> str:
        base = str(self.settings.base_url or "").strip().rstrip("/")
        path = str(self.settings.events_path or "").strip()
        if not path:
            path = "/api/integrations/bloom/v1/events"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base}{path}"

    def _is_configured(self) -> tuple[bool, str]:
        if not self.settings.events_enabled:
            return False, "events disabled"
        if not self.settings.base_url:
            return False, "atlas.base_url not configured"
        if not self.settings.organization_id:
            return False, "atlas.organization_id not configured"
        if not self.settings.webhook_secret:
            return False, "atlas.webhook_secret not configured"
        return True, ""

    def emit(self, *, event_type: str, payload: dict[str, Any], event_id: str | None = None) -> str | None:
        """Send event to Atlas; return event_id on success, else None (fail-open)."""
        configured, reason = self._is_configured()
        if not configured:
            if self.settings.events_enabled:
                logger.warning("Atlas event skipped (%s)", reason)
            return None

        resolved_event_id = (event_id or f"event_{secrets.token_hex(16)}").strip()
        body = {
            "organization_id": str(self.settings.organization_id).strip(),
            "event_id": resolved_event_id,
            "event_type": str(event_type).strip(),
            "payload": payload or {},
        }
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = hmac.new(
            str(self.settings.webhook_secret).encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Bloom-Signature": f"sha256={signature}",
            "X-Bloom-Event-Id": resolved_event_id,
        }

        endpoint = self._endpoint()
        timeout_seconds = max(1, int(self.settings.events_timeout_seconds))
        max_retries = max(0, int(self.settings.events_max_retries))
        last_error = ""

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    endpoint,
                    data=body_bytes,
                    headers=headers,
                    timeout=timeout_seconds,
                    verify=self.settings.verify_ssl,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                response = None
            else:
                if 200 <= response.status_code < 300:
                    return resolved_event_id
                last_error = f"status={response.status_code} body={response.text[:256]}"

            if attempt < max_retries:
                continue

        logger.warning(
            "Atlas event delivery failed (fail-open): event_id=%s event_type=%s endpoint=%s error=%s",
            resolved_event_id,
            event_type,
            endpoint,
            last_error,
        )
        return None


def emit_bloom_event(event_type: str, payload: dict[str, Any]) -> str | None:
    """Best-effort event emission wrapper that never raises."""
    try:
        return AtlasEventClient().emit(event_type=event_type, payload=payload)
    except Exception as exc:
        logger.warning(
            "Atlas event delivery crashed (fail-open): event_type=%s error=%s",
            event_type,
            exc,
        )
        return None
