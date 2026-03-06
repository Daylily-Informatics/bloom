"""Signed, expiring download tokens for files under ./tmp.

This is used by action execution to provide real browser downloads without
leaking filesystem paths or exposing the tmp directory directly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EXPIRES_SECONDS = 600  # 10 minutes
TOKEN_VERSION = 1


class DownloadTokenError(Exception):
    pass


@dataclass(frozen=True)
class DownloadTokenClaims:
    rel_path: str
    exp: int


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - (len(raw) % 4)) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _get_secret() -> bytes:
    # Prefer explicit secret. Fall back to JWT secret if present.
    secret = (
        os.environ.get("BLOOM_DOWNLOAD_TOKEN_SECRET")
        or os.environ.get("BLOOM_AUTH__JWT_SECRET")
        or ""
    ).strip()
    if secret:
        return secret.encode("utf-8")
    # Dev/test fallback. Tokens are still auth-protected via /api/v1/downloads.
    return b"bloom-dev-download-secret"


def _tmp_root() -> Path:
    return (Path.cwd() / "tmp").resolve()


def _resolve_tmp_file(file_path: str | Path) -> tuple[Path, str]:
    """Return (absolute_path, rel_path_under_tmp) if file is under ./tmp."""
    tmp_root = _tmp_root()
    path = Path(file_path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()

    try:
        rel = path.relative_to(tmp_root)
    except ValueError as exc:
        raise DownloadTokenError("Only files under ./tmp are eligible for download tokens") from exc

    if not path.is_file():
        raise DownloadTokenError("Download file does not exist")

    return path, rel.as_posix()


def create_download_token(file_path: str | Path, *, expires_in_seconds: int = DEFAULT_EXPIRES_SECONDS) -> str:
    """Create a signed download token for a tmp file."""
    _, rel_path = _resolve_tmp_file(file_path)
    exp = int(time.time()) + int(expires_in_seconds)
    payload = {"v": TOKEN_VERSION, "p": rel_path, "exp": exp}
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_raw)

    sig = hmac.new(_get_secret(), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_download_token(token: str) -> tuple[Path, DownloadTokenClaims]:
    """Verify token and return (absolute_path, claims)."""
    token = str(token or "").strip()
    if "." not in token:
        raise DownloadTokenError("Invalid download token format")

    payload_b64, sig = token.rsplit(".", 1)
    expected_sig = hmac.new(_get_secret(), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig):
        raise DownloadTokenError("Invalid download token signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # noqa: BLE001 - token decode validation
        raise DownloadTokenError("Invalid download token payload") from exc

    if not isinstance(payload, dict):
        raise DownloadTokenError("Invalid download token payload")

    if int(payload.get("v") or 0) != TOKEN_VERSION:
        raise DownloadTokenError("Unsupported download token version")

    rel_path = str(payload.get("p") or "").strip()
    if not rel_path:
        raise DownloadTokenError("Invalid download token payload")

    exp = int(payload.get("exp") or 0)
    if exp <= int(time.time()):
        raise DownloadTokenError("Download token has expired")

    tmp_root = _tmp_root()
    abs_path = (tmp_root / rel_path).resolve()
    try:
        abs_path.relative_to(tmp_root)
    except ValueError as exc:
        raise DownloadTokenError("Invalid download token path") from exc

    if not abs_path.is_file():
        raise DownloadTokenError("Download file does not exist")

    return abs_path, DownloadTokenClaims(rel_path=rel_path, exp=exp)

