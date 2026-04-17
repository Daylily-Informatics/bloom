from __future__ import annotations

import re
from collections.abc import Iterable
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
    elif netloc.count(":") > 1:
        host = netloc
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


def _normalized_configured_hosts(additional_hosts: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in additional_hosts or ():
        normalized = _normalize_host(str(value or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _trusted_host_entries(additional_hosts: Iterable[str] | None) -> list[str]:
    entries: list[str] = []
    for host in _normalized_configured_hosts(additional_hosts):
        entries.append(host)
        if ":" in host:
            entries.append(f"[{host}]")
    return entries


def _is_configured_host(host: str, additional_hosts: Iterable[str] | None) -> bool:
    return _normalize_host(host) in set(_normalized_configured_hosts(additional_hosts))


def _origin_pattern_for_host(host: str, *, allow_http: bool) -> str:
    normalized = _normalize_host(host)
    if not normalized:
        return ""
    scheme_expr = "https?" if allow_http else "https"
    host_expr = (
        re.escape(f"[{normalized}]") if ":" in normalized else re.escape(normalized)
    )
    return rf"{scheme_expr}://{host_expr}(?::\d+)?"


def is_allowed_origin(
    origin: str,
    *,
    allow_local: bool,
    additional_hosts: Iterable[str] | None = None,
) -> bool:
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
        return allow_local or _is_configured_host(host, additional_hosts)
    if _is_configured_host(host, additional_hosts):
        return parsed.scheme == "https"
    return parsed.scheme == "https" and is_approved_domain(host)


def build_trusted_hosts(
    *,
    allow_local: bool,
    additional_hosts: Iterable[str] | None = None,
) -> list[str]:
    hosts: list[str] = []
    for domain in APPROVED_WEB_DOMAIN_SUFFIXES:
        hosts.extend([domain, f"*.{domain}"])
    if allow_local:
        hosts.extend(sorted(_LOCAL_HOSTS | {"::1"}))
    for host in _trusted_host_entries(additional_hosts):
        if host not in hosts:
            hosts.append(host)
    return hosts


def build_allowed_origin_regex(
    *,
    allow_local: bool,
    additional_hosts: Iterable[str] | None = None,
) -> str:
    domain_expr = "|".join(re.escape(item) for item in APPROVED_WEB_DOMAIN_SUFFIXES)
    patterns = [
        rf"https://(?:[A-Za-z0-9-]+\.)*(?:{domain_expr})(?::\d+)?",
    ]
    if allow_local:
        patterns.append(
            r"https?://(?:localhost|127\.0\.0\.1|testserver|\[::1\])(?::\d+)?"
        )
    for host in _normalized_configured_hosts(additional_hosts):
        pattern = _origin_pattern_for_host(host, allow_http=is_local_host(host))
        if pattern:
            patterns.append(pattern)
    return rf"^(?:{'|'.join(patterns)})$"
