import os
import re
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException

from daylily_cognito.auth import CognitoAuth as DaylilyCognitoAuth
from daylily_cognito.jwks import verify_token_with_jwks
from daylily_cognito.oauth import (
    build_authorization_url,
    build_logout_url,
    exchange_authorization_code,
)


class CognitoConfigurationError(Exception):
    """Raised when required Cognito values are missing."""


class CognitoTokenError(Exception):
    """Raised when Cognito tokens cannot be validated."""


@dataclass(frozen=True)
class CognitoConfig:
    user_pool_id: str
    client_id: str
    region: str
    domain: str
    redirect_uri: str
    logout_redirect_uri: str
    scopes: List[str]
    client_name: str = ""
    client_secret: str = ""
    source_path: str = ""

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def authorize_url(self) -> str:
        return build_authorization_url(
            domain=self.domain,
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            response_type="code",
            scope=" ".join(self.scopes),
        )

    @property
    def logout_url(self) -> str:
        return build_logout_url(
            domain=self.domain,
            client_id=self.client_id,
            logout_uri=self.logout_redirect_uri,
        )


@dataclass(frozen=True)
class _DaycogEntry:
    path: Path
    values: Dict[str, str]
    app_name: str


_DAYCOG_FILENAME_RE = re.compile(
    r"^(?P<pool>.+?)\.(?P<region>[a-z]{2}-[a-z]+-\d+)(?:\.(?P<app>.+))?\.env$"
)
LOGGER = logging.getLogger(__name__)


class CognitoAuth:
    def __init__(self, config: CognitoConfig):
        self.config = config
        self._auth = DaylilyCognitoAuth(
            region=config.region,
            user_pool_id=config.user_pool_id,
            app_client_id=config.client_id,
            app_client_secret=config.client_secret or None,
        )

    @property
    def auth(self) -> DaylilyCognitoAuth:
        """Expose the underlying daylily-cognito auth client."""
        return self._auth

    @classmethod
    def from_env(cls) -> "CognitoAuth":
        values = {
            "COGNITO_USER_POOL_ID": os.getenv("COGNITO_USER_POOL_ID", ""),
            "COGNITO_REGION": os.getenv("COGNITO_REGION", "") or os.getenv("AWS_REGION", ""),
            "COGNITO_APP_CLIENT_ID": os.getenv("COGNITO_APP_CLIENT_ID", "") or os.getenv("COGNITO_CLIENT_ID", ""),
            "COGNITO_DOMAIN": os.getenv("COGNITO_DOMAIN", ""),
            "COGNITO_CALLBACK_URL": os.getenv("COGNITO_CALLBACK_URL", "") or os.getenv("COGNITO_REDIRECT_URI", ""),
            "COGNITO_LOGOUT_URL": os.getenv("COGNITO_LOGOUT_URL", "") or os.getenv("COGNITO_LOGOUT_REDIRECT_URI", ""),
            "COGNITO_CLIENT_NAME": os.getenv("COGNITO_CLIENT_NAME", ""),
            "COGNITO_APP_CLIENT_SECRET": os.getenv("COGNITO_APP_CLIENT_SECRET", "") or os.getenv("COGNITO_CLIENT_SECRET", ""),
        }
        return cls(_build_config(values, scopes=os.getenv("COGNITO_SCOPES", "openid email profile").split()))

    @classmethod
    def from_settings(cls, auth_settings) -> "CognitoAuth":
        """Build Cognito auth from Bloom settings + daycog files.

        The Bloom YAML stores only `auth.cognito_user_pool_id` as the source of truth.
        Pool/app-specific client details are resolved from ~/.config/daycog/*.env.
        """
        pool_id = (auth_settings.cognito_user_pool_id or "").strip()
        if not pool_id:
            raise CognitoConfigurationError(
                "auth.cognito_user_pool_id must be set in ~/.config/bloom/bloom-config.yaml"
            )

        daycog_values: Dict[str, str] = {}
        try:
            daycog_values = _resolve_daycog_values_for_pool(pool_id)
        except CognitoConfigurationError as exc:
            # Backward-compatible fallback for existing YAML-driven deployments.
            LOGGER.debug("daycog resolution failed for %s: %s", pool_id, exc)

        # Backward-compatibility fallbacks from YAML.
        merged = {
            **daycog_values,
            "COGNITO_USER_POOL_ID": pool_id,
            "COGNITO_REGION": daycog_values.get("COGNITO_REGION") or auth_settings.cognito_region,
            "COGNITO_APP_CLIENT_ID": daycog_values.get("COGNITO_APP_CLIENT_ID") or auth_settings.cognito_client_id,
            "COGNITO_DOMAIN": daycog_values.get("COGNITO_DOMAIN") or auth_settings.cognito_domain,
            "COGNITO_CALLBACK_URL": daycog_values.get("COGNITO_CALLBACK_URL") or auth_settings.cognito_redirect_uri,
            "COGNITO_LOGOUT_URL": (
                daycog_values.get("COGNITO_LOGOUT_URL")
                or auth_settings.cognito_logout_redirect_uri
                or daycog_values.get("COGNITO_CALLBACK_URL")
                or auth_settings.cognito_redirect_uri
            ),
            "COGNITO_APP_CLIENT_SECRET": daycog_values.get("COGNITO_APP_CLIENT_SECRET")
            or daycog_values.get("COGNITO_CLIENT_SECRET")
            or auth_settings.cognito_client_secret,
        }

        config = _build_config(
            merged,
            scopes=auth_settings.cognito_scopes or ["openid", "email", "profile"],
            source_path=daycog_values.get("_SOURCE_PATH", ""),
        )
        return cls(config)

    def validate_token(self, token: str) -> Dict:
        """Validate access token first, then fallback to ID token validation."""
        try:
            return self._auth.verify_token(token)
        except HTTPException as access_exc:
            # daylily-cognito verifies access tokens (client_id). ID tokens use `aud`.
            try:
                claims = verify_token_with_jwks(token, self.config.region, self.config.user_pool_id)
                aud = claims.get("aud")
                aud_ok = False
                if isinstance(aud, str):
                    aud_ok = aud == self.config.client_id
                elif isinstance(aud, list):
                    aud_ok = self.config.client_id in aud
                if not aud_ok:
                    raise CognitoTokenError("Invalid token audience")
                return claims
            except CognitoTokenError:
                raise
            except Exception as id_exc:  # noqa: BLE001
                detail = getattr(access_exc, "detail", str(access_exc))
                raise CognitoTokenError(str(detail)) from id_exc
        except Exception as exc:  # noqa: BLE001
            raise CognitoTokenError(str(exc)) from exc

    def exchange_code_for_tokens(self, code: str) -> Dict:
        try:
            return exchange_authorization_code(
                domain=self.config.domain,
                client_id=self.config.client_id,
                code=code,
                redirect_uri=self.config.redirect_uri,
                client_secret=self.config.client_secret or None,
            )
        except Exception as exc:  # noqa: BLE001
            raise CognitoTokenError(f"OAuth code exchange failed: {exc}") from exc


def _build_config(values: Dict[str, str], scopes: Optional[List[str]] = None, source_path: str = "") -> CognitoConfig:
    pool_id = (values.get("COGNITO_USER_POOL_ID") or "").strip()
    region = (values.get("COGNITO_REGION") or values.get("AWS_REGION") or "").strip()
    if not region and pool_id and "_" in pool_id:
        region = pool_id.split("_", 1)[0]

    client_id = (values.get("COGNITO_APP_CLIENT_ID") or values.get("COGNITO_CLIENT_ID") or "").strip()
    domain = (values.get("COGNITO_DOMAIN") or "").strip()
    callback_url = (values.get("COGNITO_CALLBACK_URL") or values.get("COGNITO_REDIRECT_URI") or "").strip()
    logout_url = (
        values.get("COGNITO_LOGOUT_URL")
        or values.get("COGNITO_LOGOUT_REDIRECT_URI")
        or callback_url
        or ""
    ).strip()

    missing: List[str] = []
    if not pool_id:
        missing.append("COGNITO_USER_POOL_ID")
    if not region:
        missing.append("COGNITO_REGION")
    if not client_id:
        missing.append("COGNITO_APP_CLIENT_ID")
    if not domain:
        missing.append("COGNITO_DOMAIN")
    if not callback_url:
        missing.append("COGNITO_CALLBACK_URL")

    if missing:
        src = f" (source: {source_path})" if source_path else ""
        hint = ""
        if "COGNITO_DOMAIN" in missing and source_path:
            hint = (
                " Missing COGNITO_DOMAIN usually means no Hosted UI domain is attached. "
                "For daycog 0.1.22+, use `daycog setup --attach-domain --domain-prefix <prefix>` "
                "or attach a domain and rerun `daycog config update`."
            )
        raise CognitoConfigurationError(
            f"Missing Cognito configuration values: {', '.join(sorted(missing))}{src}.{hint}".rstrip()
        )

    resolved_scopes = scopes or ["openid", "email", "profile"]

    return CognitoConfig(
        user_pool_id=pool_id,
        client_id=client_id,
        region=region,
        domain=domain,
        redirect_uri=callback_url,
        logout_redirect_uri=logout_url,
        scopes=resolved_scopes,
        client_name=(values.get("COGNITO_CLIENT_NAME") or "").strip(),
        client_secret=(values.get("COGNITO_APP_CLIENT_SECRET") or values.get("COGNITO_CLIENT_SECRET") or "").strip(),
        source_path=source_path,
    )


def _read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            values[key] = value
    return values


def _entry_from_path(path: Path) -> Optional[_DaycogEntry]:
    if path.name == "default.env":
        app_name = ""
    else:
        match = _DAYCOG_FILENAME_RE.match(path.name)
        app_name = (match.group("app") if match else "") or ""
    values = _read_env_file(path)
    if not values:
        return None
    return _DaycogEntry(path=path, values=values, app_name=app_name)


def _resolve_daycog_values_for_pool(pool_id: str) -> Dict[str, str]:
    config_dir = Path.home() / ".config" / "daycog"
    if not config_dir.exists():
        raise CognitoConfigurationError(
            "daycog config directory not found. Expected ~/.config/daycog"
        )

    entries: List[_DaycogEntry] = []
    for path in sorted(config_dir.glob("*.env")):
        entry = _entry_from_path(path)
        if not entry:
            continue
        if (entry.values.get("COGNITO_USER_POOL_ID") or "").strip() == pool_id:
            entries.append(entry)

    if not entries:
        raise CognitoConfigurationError(
            f"No daycog env file found for pool ID {pool_id}. "
            "Run daycog setup/config commands first."
        )

    selected = _select_daycog_entry(entries)
    values = dict(selected.values)
    values["_SOURCE_PATH"] = str(selected.path)
    return values


def _select_daycog_entry(entries: List[_DaycogEntry]) -> _DaycogEntry:
    app_name = (os.environ.get("BLOOM_COGNITO_APP_NAME") or "").strip().lower()

    # App-scoped files: <pool>.<region>.<app>.env
    app_entries = [e for e in entries if e.app_name]
    # Pool-scoped files: <pool>.<region>.env (default app context for that pool/region)
    pool_entries = [e for e in entries if not e.app_name and e.path.name != "default.env"]
    # Global fallback context
    default_entries = [e for e in entries if e.path.name == "default.env"]

    if app_name:
        matched = [
            e
            for e in (app_entries or entries)
            if e.app_name.lower() == app_name
            or (e.values.get("COGNITO_CLIENT_NAME") or "").strip().lower() == app_name
        ]
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            raise CognitoConfigurationError(
                "Multiple daycog app files matched BLOOM_COGNITO_APP_NAME. "
                f"Matches: {', '.join(str(e.path) for e in matched)}"
            )
        raise CognitoConfigurationError(
            f"No daycog app file matched BLOOM_COGNITO_APP_NAME={app_name}"
        )

    # 0.1.22 pattern: prefer pool-scoped file by default because `daycog add-app/edit-app
    # --set-default` updates this file to the active app context for the pool.
    if len(pool_entries) == 1:
        return pool_entries[0]
    if len(pool_entries) > 1:
        raise CognitoConfigurationError(
            "Multiple pool-scoped daycog files found for this pool ID. "
            f"Candidates: {', '.join(str(e.path) for e in pool_entries)}"
        )

    if len(app_entries) == 1:
        return app_entries[0]
    if len(app_entries) > 1:
        bloom_named = [
            e
            for e in app_entries
            if "bloom" in (
                f"{e.app_name} {(e.values.get('COGNITO_CLIENT_NAME') or '')}".lower()
            )
        ]
        if len(bloom_named) == 1:
            return bloom_named[0]

        raise CognitoConfigurationError(
            "Multiple daycog app files found for this pool. "
            "Set BLOOM_COGNITO_APP_NAME or set an active app via daycog --set-default. "
            f"Candidates: {', '.join(str(e.path) for e in app_entries)}"
        )

    if len(default_entries) == 1:
        return default_entries[0]
    if len(entries) == 1:
        return entries[0]

    raise CognitoConfigurationError(
        "Unable to select a single daycog env file for this pool. "
        f"Candidates: {', '.join(str(e.path) for e in entries)}"
    )


@lru_cache(maxsize=1)
def get_cognito_auth() -> CognitoAuth:
    """Create and cache a CognitoAuth instance.

    Primary source is Bloom YAML pool-id + daycog per-pool/per-app env files.
    Falls back to legacy COGNITO_* environment variables.
    """
    try:
        from bloom_lims.config import get_settings
        settings = get_settings()
    except Exception:
        # If Bloom settings cannot be loaded at all, fall back to env-only mode.
        return CognitoAuth.from_env()

    if settings.auth.cognito_user_pool_id:
        # Do not swallow configuration errors when pool-id mode is active.
        return CognitoAuth.from_settings(settings.auth)

    return CognitoAuth.from_env()
