import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List
from urllib.parse import urlencode

import jwt


class CognitoConfigurationError(Exception):
    """Raised when required Cognito environment variables are missing."""


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
                "response_type": "token",
                "redirect_uri": self.redirect_uri,
                "scope": " ".join(self.scopes),
            }
        )
        return f"https://{self.domain}/oauth2/authorize?{query}"

    @property
    def logout_url(self) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "logout_uri": self.logout_redirect_uri,
            }
        )
        return f"https://{self.domain}/logout?{query}"


class CognitoAuth:
    def __init__(self, config: CognitoConfig):
        self.config = config
        self._jwks_client = jwt.PyJWKClient(config.jwks_url)

    @classmethod
    def from_env(cls) -> "CognitoAuth":
        required_vars = {
            "COGNITO_USER_POOL_ID": os.getenv("COGNITO_USER_POOL_ID"),
            "COGNITO_REGION": os.getenv("COGNITO_REGION"),
            "COGNITO_CLIENT_ID": os.getenv("COGNITO_CLIENT_ID"),
            "COGNITO_DOMAIN": os.getenv("COGNITO_DOMAIN"),
        }
        missing = [name for name, value in required_vars.items() if not value]
        if missing:
            raise CognitoConfigurationError(
                f"Missing Cognito configuration values: {', '.join(sorted(missing))}"
            )

        redirect_uri = os.getenv("COGNITO_REDIRECT_URI", "")
        logout_redirect_uri = os.getenv("COGNITO_LOGOUT_REDIRECT_URI", redirect_uri)

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
            client_id=required_vars["COGNITO_CLIENT_ID"],
            region=required_vars["COGNITO_REGION"],
            domain=required_vars["COGNITO_DOMAIN"],
            redirect_uri=redirect_uri,
            logout_redirect_uri=logout_redirect_uri,
            scopes=scopes,
        )
        return cls(config)

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
    """Create (and cache) a CognitoAuth instance from environment variables."""
    return CognitoAuth.from_env()
