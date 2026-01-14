from auth.cognito.client import (
    CognitoConfigurationError,
    CognitoTokenError,
    get_cognito_auth,
)


class UserContext:
    """
    Lightweight helper for working with Cognito tokens.

    This wrapper centralizes validation logic so other modules do not need to know
    the Cognito configuration details.
    """

    def __init__(self):
        self.cognito = get_cognito_auth()

    def validate_token(self, token: str):
        """Validate and decode a Cognito JWT."""
        return self.cognito.validate_token(token)
