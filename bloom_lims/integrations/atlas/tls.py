"""Helpers for TLS verification when calling Atlas from Bloom.

`requests` defaults to certifi's CA bundle, which does not include mkcert's
local root CA. For local development where Atlas runs with mkcert-issued
certificates (https://localhost:...), we need to point `requests.verify` at the
mkcert root CA file to keep TLS verification enabled.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def resolve_requests_verify(*, base_url: str, verify_ssl: bool) -> bool | str:
    """Return a `requests` verify value for a given Atlas base_url.

    For non-localhost URLs:
    - True means use requests/certifi defaults.

    For https://localhost URLs:
    - When mkcert root CA is available, return its rootCA.pem path to keep
      verification enabled.
    - Otherwise fall back to True (and the caller will see a normal TLS error).
    """

    if not verify_ssl:
        return False

    candidate = str(base_url or "").strip()
    if not candidate:
        return True

    try:
        parsed = urlparse(candidate)
    except Exception:
        return True

    if (parsed.hostname or "").strip().lower() != "localhost":
        return True

    root_ca = _find_mkcert_root_ca()
    if root_ca:
        return str(root_ca)
    return True


def _find_mkcert_root_ca() -> Path | None:
    """Best-effort discovery for mkcert rootCA.pem."""
    caroot = str(os.environ.get("CAROOT") or "").strip()
    if caroot:
        path = Path(os.path.expanduser(caroot)) / "rootCA.pem"
        if path.exists():
            return path

    mkcert_bin = shutil.which("mkcert")
    if mkcert_bin:
        try:
            out = subprocess.check_output([mkcert_bin, "-CAROOT"], text=True, timeout=2).strip()
        except Exception:
            out = ""
        if out:
            path = Path(out) / "rootCA.pem"
            if path.exists():
                return path

    # Common mkcert defaults (OS-dependent).
    candidates = [
        Path.home() / "Library" / "Application Support" / "mkcert" / "rootCA.pem",
        Path.home() / ".local" / "share" / "mkcert" / "rootCA.pem",
        Path.home() / ".config" / "mkcert" / "rootCA.pem",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None

