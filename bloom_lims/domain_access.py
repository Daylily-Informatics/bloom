from __future__ import annotations

import re
from urllib.parse import urlsplit

APPROVED_WEB_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "lsmc.com",
    "lsmc.bio",
    "lsmc.life",
    "dyly.bio",
    "daylilyinformatics.bio",
    "inflectionmedicine.com",
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "testserver"})


def _normalize_host(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    netloc = parsed.netloc or parsed.path
    netloc = netloc.rsplit("@", 1)[-1]
    if netloc.startswith("["):
        closing = netloc.find("]")
        host = netloc[1:closing] if closing != -1 else netloc[1:]
    else:
        host = netloc.split(":", 1)[0]
    return host.rstrip(".").lower()


def is_approved_domain(host: str) -> bool:
    normalized = _normalize_host(host)
    if not normalized:
        return False
    return any(
        normalized == item or normalized.endswith(f".{item}")
        for item in APPROVED_WEB_DOMAIN_SUFFIXES
    )


def is_local_host(host: str) -> bool:
    return _normalize_host(host) in _LOCAL_HOSTS


def is_allowed_origin(origin: str, *, allow_local: bool) -> bool:
    candidate = str(origin or "").strip()
    if not candidate:
        return False
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = _normalize_host(candidate)
    if not host:
        return False
    if is_local_host(host):
        return allow_local
    return parsed.scheme == "https" and is_approved_domain(host)


def build_trusted_hosts(*, allow_local: bool) -> list[str]:  # noqa: ARG001
    # Host filtering is now handled upstream (security groups / load balancer).
    return ["*"]


def build_allowed_origin_regex(*, allow_local: bool) -> str:
    domain_expr = "|".join(re.escape(item) for item in APPROVED_WEB_DOMAIN_SUFFIXES)
    patterns = [
        rf"https://(?:[A-Za-z0-9-]+\.)*(?:{domain_expr})(?::\d+)?",
    ]
    if allow_local:
        patterns.append(
            r"https?://(?:localhost|127\.0\.0\.1|testserver|\[::1\])(?::\d+)?"
        )
    return rf"^(?:{'|'.join(patterns)})$"
