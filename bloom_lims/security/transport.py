"""Helpers for enforcing HTTPS transport policy."""

from __future__ import annotations

from urllib.parse import urlparse


class InsecureTransportError(ValueError):
    """Raised when a URL violates HTTPS-only transport policy."""


def is_https_url(url: str | None) -> bool:
    """Return True when url is an absolute HTTPS URL with a host."""
    candidate = str(url or "").strip()
    if not candidate:
        return False
    parsed = urlparse(candidate)
    return parsed.scheme.lower() == "https" and bool(parsed.netloc)


def require_https_url(url: str | None, *, context_label: str) -> str:
    """Validate and normalize an absolute HTTPS URL."""
    candidate = str(url or "").strip()
    if not candidate:
        raise InsecureTransportError(f"{context_label} is required")
    parsed = urlparse(candidate)
    if parsed.scheme.lower() != "https":
        raise InsecureTransportError(f"{context_label} must use https://")
    if not parsed.netloc:
        raise InsecureTransportError(f"{context_label} must include a valid host")
    return candidate
