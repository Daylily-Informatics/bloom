from __future__ import annotations

import os

import pytest

from tests.e2e.cognito_test_user import ensure_test_user


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("BLOOM_BASE_URL", "https://localhost:18912").rstrip("/")


@pytest.fixture(scope="session")
def e2e_credentials():
    return ensure_test_user()


@pytest.fixture(scope="session")
def e2e_email(e2e_credentials) -> str:
    return e2e_credentials.email


@pytest.fixture(scope="session")
def e2e_password(e2e_credentials) -> str:
    return e2e_credentials.password


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "ignore_https_errors": True}
