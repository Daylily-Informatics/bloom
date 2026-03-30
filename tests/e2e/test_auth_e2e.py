from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.auth_helpers import assert_authenticated_page, perform_login, perform_logout


@pytest.mark.e2e
def test_login_round_trip(page: Page, base_url: str, e2e_email: str, e2e_password: str):
    perform_login(page, base_url=base_url, email=e2e_email, password=e2e_password)
    expect(page).to_have_url(f"{base_url}/")
    assert_authenticated_page(page)


@pytest.mark.e2e
def test_logout_round_trip(page: Page, base_url: str, e2e_email: str, e2e_password: str):
    perform_login(page, base_url=base_url, email=e2e_email, password=e2e_password)
    perform_logout(page, base_url=base_url)
    current_url = page.url
    assert (
        current_url.startswith(f"{base_url}/login")
        or "auth.us-west-2.amazoncognito.com/login" in current_url
        or "auth.us-west-2.amazoncognito.com/logout" in current_url
    ), f"Unexpected logout landing URL: {current_url}"

    response = page.goto(f"{base_url}/")
    assert response is not None
    assert response.status in {200, 302, 303}
    page.wait_for_load_state("domcontentloaded")
    current_url = page.url
    assert (
        current_url.startswith(f"{base_url}/login")
        or "auth.us-west-2.amazoncognito.com/login" in current_url
        or "auth.us-west-2.amazoncognito.com/logout" in current_url
    ), f"Unexpected protected-route logout URL: {current_url}"
