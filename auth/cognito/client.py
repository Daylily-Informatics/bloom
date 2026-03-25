import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode, urlparse

import httpx
import jwt


class CognitoConfigurationError(Exception):
    """Raised when required Cognito environment variables are missing."""


class CognitoTokenError(Exception):
    """Raised when Cognito tokens cannot be validated."""


@dataclass(frozen=True)
class CognitoConfig:
    user_pool_id: str
    client_id: str
    client_secret: str
    region: str
    domain: str
    redirect_uri: str
    logout_redirect_uri: str
    scopes: List[str]

    @property
    def _bare_domain(self) -> str:
        """Domain without protocol prefix for URL construction."""
        d = (self.domain or "").strip().rstrip("/")
        if d.startswith("https://"):
            d = d[len("https://"):]
        elif d.startswith("http://"):
            d = d[len("http://"):]
        return d

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def authorize_url(self) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": " ".join(self.scopes),
            }
        )
        return f"https://{self._bare_domain}/oauth2/authorize?{query}"

    @property
    def token_url(self) -> str:
        return f"https://{self._bare_domain}/oauth2/token"

    @property
    def logout_url(self) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "logout_uri": self.logout_redirect_uri,
            }
        )
        return f"https://{self._bare_domain}/logout?{query}"


class CognitoAuth:
    def __init__(self, config: CognitoConfig):
        self.config = config
        self._jwks_client = jwt.PyJWKClient(config.jwks_url)

    @classmethod
    def from_env(cls) -> "CognitoAuth":
        client_id = os.getenv("COGNITO_APP_CLIENT_ID") or os.getenv("COGNITO_CLIENT_ID")
        client_secret = (
            os.getenv("COGNITO_APP_CLIENT_SECRET")
            or os.getenv("COGNITO_CLIENT_SECRET")
            or ""
        )
        redirect_uri = os.getenv("COGNITO_CALLBACK_URL") or os.getenv("COGNITO_REDIRECT_URI", "")

        required_vars = {
            "COGNITO_USER_POOL_ID": os.getenv("COGNITO_USER_POOL_ID"),
            "COGNITO_REGION": os.getenv("COGNITO_REGION"),
            "COGNITO_APP_CLIENT_ID": client_id,
            "COGNITO_DOMAIN": os.getenv("COGNITO_DOMAIN"),
            "COGNITO_CALLBACK_URL": redirect_uri,
        }
        missing = [name for name, value in required_vars.items() if not value]
        if missing:
            raise CognitoConfigurationError(
                f"Missing Cognito configuration values: {', '.join(sorted(missing))}"
            )

        logout_redirect_uri = (
            os.getenv("COGNITO_LOGOUT_URL")
            or os.getenv("COGNITO_LOGOUT_REDIRECT_URI")
            or redirect_uri
        )

        if not redirect_uri:
            raise CognitoConfigurationError("COGNITO_REDIRECT_URI must be set.")
        if not logout_redirect_uri:
            raise CognitoConfigurationError("COGNITO_LOGOUT_REDIRECT_URI must be set.")

        scopes = os.getenv(
            "COGNITO_SCOPES",
            "openid email profile",
        ).split()

        config = CognitoConfig(
            user_pool_id=required_vars["COGNITO_USER_POOL_ID"],
            client_id=required_vars["COGNITO_APP_CLIENT_ID"],
            client_secret=client_secret,
            region=required_vars["COGNITO_REGION"],
            domain=required_vars["COGNITO_DOMAIN"],
            redirect_uri=redirect_uri,
            logout_redirect_uri=logout_redirect_uri,
            scopes=scopes,
        )
        return cls(config)

    @staticmethod
    def _parse_env_file(path: Path) -> Dict[str, str]:
        values: Dict[str, str] = {}
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        except Exception:
            return {}
        return values

    @staticmethod
    def _normalize_url(url: str) -> str:
        return (url or "").strip().rstrip("/")

    @classmethod
    def _same_origin(cls, left_url: str, right_url: str) -> bool:
        left = cls._normalize_url(left_url)
        right = cls._normalize_url(right_url)
        if not left or not right:
            return False
        try:
            left_parts = urlparse(left)
            right_parts = urlparse(right)
            return (
                left_parts.scheme.lower() == right_parts.scheme.lower()
                and left_parts.netloc.lower() == right_parts.netloc.lower()
            )
        except Exception:
            return False

    @classmethod
    def _extract_port(cls, url: str) -> Optional[int]:
        normalized = (url or "").strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            return None
        if parsed.port is not None:
            return parsed.port
        if parsed.scheme.lower() == "https":
            return 443
        if parsed.scheme.lower() == "http":
            return 80
        return None

    @classmethod
    def _validate_runtime_uri_port_match(
        cls,
        *,
        label: str,
        stored_url: str,
        expected_url: str,
        pool_id: str,
        client_id: str,
    ) -> None:
        """Validate that stored Cognito app URI port matches current Bloom runtime port."""
        if not expected_url:
            return

        if not stored_url:
            raise CognitoConfigurationError(
                f"Unable to verify Cognito {label} URL for pool '{pool_id}' client '{client_id}'. "
                f"No stored {label} URL found."
            )

        stored_port = cls._extract_port(stored_url)
        expected_port = cls._extract_port(expected_url)
        if stored_port is None:
            raise CognitoConfigurationError(
                f"Stored Cognito {label} URL is invalid: '{stored_url}'."
            )
        if expected_port is None:
            raise CognitoConfigurationError(
                f"Bloom runtime {label} URL is invalid: '{expected_url}'."
            )

        if stored_port != expected_port:
            raise CognitoConfigurationError(
                f"Cognito {label} URL port mismatch for pool '{pool_id}' client '{client_id}': "
                f"stored '{stored_url}' uses port {stored_port}, but Bloom is running with '{expected_url}' "
                f"(port {expected_port}). Update the Cognito app callback/logout URLs to this Bloom port."
            )

    @classmethod
    def _load_daycog_values_for_pool(
        cls,
        user_pool_id: str,
        region: str = "",
        expected_callback_url: str = "",
        expected_logout_url: str = "",
        required_client_name: str = "",
    ) -> Dict[str, str]:
        """Load matching daycog env values for a given pool ID."""
        cfg_dir = Path.home() / ".config" / "daycog"
        if not cfg_dir.exists():
            return {}

        target_region = region or user_pool_id.split("_", 1)[0]
        normalized_expected_callback = cls._normalize_url(expected_callback_url)
        normalized_expected_logout = cls._normalize_url(expected_logout_url)
        normalized_required_client_name = (required_client_name or "").strip().lower()
        matches: List[tuple[int, Dict[str, str]]] = []
        for env_file in sorted(cfg_dir.glob("*.env")):
            values = cls._parse_env_file(env_file)
            if values.get("COGNITO_USER_POOL_ID") != user_pool_id:
                continue
            if target_region and values.get("COGNITO_REGION") and values.get("COGNITO_REGION") != target_region:
                continue

            score = 0
            lower_name = env_file.name.lower()
            if env_file.name != "default.env":
                # Prefer pool/app-scoped files over global default.env.
                score += 20
            else:
                score -= 5
            if "bloom" in lower_name:
                score += 10
            if target_region and target_region in lower_name:
                score += 5

            client_name = values.get("COGNITO_CLIENT_NAME", "").strip().lower()
            if normalized_required_client_name:
                if client_name == normalized_required_client_name:
                    score += 70
                elif client_name:
                    score -= 200
                else:
                    score -= 20

            callback_url = values.get("COGNITO_CALLBACK_URL", "")
            normalized_callback = cls._normalize_url(callback_url)
            if callback_url.startswith("https://localhost:8912"):
                score += 5

            if normalized_expected_callback:
                if normalized_callback == normalized_expected_callback:
                    score += 80
                elif cls._same_origin(normalized_callback, normalized_expected_callback):
                    score += 20
                elif normalized_callback:
                    score -= 10

            logout_url = values.get("COGNITO_LOGOUT_URL", "")
            normalized_logout = cls._normalize_url(logout_url)
            if normalized_expected_logout:
                if normalized_logout == normalized_expected_logout:
                    score += 40
                elif cls._same_origin(normalized_logout, normalized_expected_logout):
                    score += 10

            domain = values.get("COGNITO_DOMAIN", "")
            expected_domain_suffix = (
                f".auth.{target_region}.amazoncognito.com" if target_region else ""
            )
            if expected_domain_suffix and domain:
                if expected_domain_suffix in domain:
                    score += 3
                else:
                    score -= 10
            elif expected_domain_suffix and not domain:
                # Prefer candidate env files that include Hosted UI domain.
                score -= 5
            matches.append((score, values))

        if not matches:
            return {}

        if normalized_expected_callback:
            exact_callback_matches = [
                (score, values)
                for score, values in matches
                if cls._normalize_url(values.get("COGNITO_CALLBACK_URL", "")) == normalized_expected_callback
            ]
            if exact_callback_matches:
                exact_callback_matches.sort(key=lambda item: item[0], reverse=True)
                return exact_callback_matches[0][1]

        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    @classmethod
    def from_settings(
        cls,
        auth_settings,
        *,
        expected_callback_url: str = "",
        expected_logout_url: str = "",
        required_client_name: str = "",
    ) -> "CognitoAuth":
        """Create CognitoAuth from BloomSettings.auth instance.
        
        Args:
            auth_settings: AuthSettings instance from bloom_lims.config
        """
        pool_id = auth_settings.cognito_user_pool_id or os.getenv("COGNITO_USER_POOL_ID", "")
        env_pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
        expected_callback_url = (expected_callback_url or "").strip()
        expected_logout_url = (expected_logout_url or "").strip()
        required_client_name = (
            (required_client_name or os.getenv("BLOOM_COGNITO_APP_NAME") or "bloom")
            .strip()
        )

        region = auth_settings.cognito_region or ""
        if not region and pool_id:
            region = pool_id.split("_", 1)[0]
        if not region:
            region = os.getenv("COGNITO_REGION", "")

        daycog_values = (
            cls._load_daycog_values_for_pool(
                pool_id,
                region=region,
                expected_callback_url=expected_callback_url,
                expected_logout_url=expected_logout_url,
                required_client_name=required_client_name,
            )
            if pool_id
            else {}
        )

        # Only trust process-level COGNITO_* overrides when they target the same pool.
        # This prevents cross-service contamination when different apps share one shell.
        allow_env_overrides = not pool_id or not env_pool_id or env_pool_id == pool_id

        def env_value(*keys: str) -> str:
            if not allow_env_overrides:
                return ""
            for key in keys:
                value = os.getenv(key, "").strip()
                if value:
                    return value
            return ""

        client_id = (
            auth_settings.cognito_client_id
            or daycog_values.get("COGNITO_APP_CLIENT_ID")
            or daycog_values.get("COGNITO_CLIENT_ID")
            or env_value("COGNITO_APP_CLIENT_ID", "COGNITO_CLIENT_ID")
            or ""
        )
        client_secret = (
            auth_settings.cognito_client_secret
            or daycog_values.get("COGNITO_APP_CLIENT_SECRET")
            or daycog_values.get("COGNITO_CLIENT_SECRET")
            or env_value("COGNITO_APP_CLIENT_SECRET", "COGNITO_CLIENT_SECRET")
            or ""
        )
        client_name = (
            daycog_values.get("COGNITO_CLIENT_NAME")
            or env_value("COGNITO_CLIENT_NAME")
            or ""
        ).strip()
        domain = (
            auth_settings.cognito_domain
            or daycog_values.get("COGNITO_DOMAIN", "")
            or env_value("COGNITO_DOMAIN")
            or ""
        )
        stored_redirect_uri = (
            auth_settings.cognito_redirect_uri
            or daycog_values.get("COGNITO_CALLBACK_URL", "")
            or env_value("COGNITO_CALLBACK_URL", "COGNITO_REDIRECT_URI")
            or ""
        )
        stored_logout_uri = (
            auth_settings.cognito_logout_redirect_uri
            or daycog_values.get("COGNITO_LOGOUT_URL", "")
            or env_value("COGNITO_LOGOUT_URL", "COGNITO_LOGOUT_REDIRECT_URI")
            or stored_redirect_uri
        )
        redirect_uri = (
            auth_settings.cognito_redirect_uri
            or expected_callback_url
            or daycog_values.get("COGNITO_CALLBACK_URL", "")
            or env_value("COGNITO_CALLBACK_URL", "COGNITO_REDIRECT_URI")
            or ""
        )
        logout_uri = (
            auth_settings.cognito_logout_redirect_uri
            or expected_logout_url
            or daycog_values.get("COGNITO_LOGOUT_URL")
            or env_value("COGNITO_LOGOUT_URL", "COGNITO_LOGOUT_REDIRECT_URI")
            or redirect_uri
        )

        if required_client_name:
            if not client_name:
                raise CognitoConfigurationError(
                    "Cognito client name is missing from the selected daycog/env context. "
                    f"Bloom requires app client name '{required_client_name}'."
                )
            if client_name.lower() != required_client_name.lower():
                raise CognitoConfigurationError(
                    f"Cognito app client name mismatch for pool '{pool_id or '(unset)'}' client "
                    f"'{client_id or '(unset)'}': selected '{client_name}', expected '{required_client_name}'. "
                    "Create/select a Cognito app client named 'bloom' and set it as active."
                )

        cls._validate_runtime_uri_port_match(
            label="callback",
            stored_url=stored_redirect_uri,
            expected_url=expected_callback_url,
            pool_id=pool_id or "(unset)",
            client_id=client_id or "(unset)",
        )
        cls._validate_runtime_uri_port_match(
            label="logout",
            stored_url=stored_logout_uri,
            expected_url=expected_logout_url,
            pool_id=pool_id or "(unset)",
            client_id=client_id or "(unset)",
        )

        required = {
            "cognito_user_pool_id": pool_id,
            "cognito_client_id": client_id,
            "cognito_region": region,
            "cognito_domain": domain,
            "cognito_redirect_uri": redirect_uri,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise CognitoConfigurationError(
                f"Missing Cognito configuration in YAML config: {', '.join(sorted(missing))}"
            )

        config = CognitoConfig(
            user_pool_id=pool_id,
            client_id=client_id,
            client_secret=client_secret,
            region=region,
            domain=domain,
            redirect_uri=redirect_uri,
            logout_redirect_uri=logout_uri,
            scopes=auth_settings.cognito_scopes or ["openid", "email", "profile"],
        )
        return cls(config)

    def exchange_authorization_code(self, code: str) -> Dict:
        """Exchange an OAuth2 authorization code for Cognito tokens."""
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.config.client_id,
            "code": code,
            "redirect_uri": self.config.redirect_uri,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret

        try:
            response = httpx.post(
                self.config.token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001
            raise CognitoTokenError(f"Token exchange request failed: {exc}") from exc

        if response.status_code != 200:
            detail = (response.text or "").strip()[:500]
            raise CognitoTokenError(
                f"Token exchange failed ({response.status_code}): {detail}"
            )

        try:
            token_payload = response.json()
        except ValueError as exc:
            raise CognitoTokenError("Token exchange returned non-JSON response") from exc

        if not token_payload.get("id_token") and not token_payload.get("access_token"):
            raise CognitoTokenError("Token exchange returned no usable tokens")

        return token_payload

    def validate_token(self, token: str) -> Dict:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.config.client_id,
                issuer=self.config.issuer,
            )
        except Exception as exc:  # noqa: BLE001
            raise CognitoTokenError(str(exc)) from exc


@lru_cache(maxsize=1)
def get_cognito_auth() -> CognitoAuth:
    """Create (and cache) a CognitoAuth instance from YAML config.
    
    Falls back to environment variables if YAML config is incomplete.
    """
    try:
        from bloom_lims.config import get_settings
        settings = get_settings()
        # Pool ID is sufficient when daycog env files are present.
        if settings.auth.cognito_user_pool_id:
            return CognitoAuth.from_settings(settings.auth)
    except CognitoConfigurationError:
        raise
    except Exception:
        pass
    # Fall back to environment variables
    return CognitoAuth.from_env()
