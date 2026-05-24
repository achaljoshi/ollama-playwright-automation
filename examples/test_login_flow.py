"""Example: Login flow with oapw — AI-powered interactions + multiple assertions.

Demonstrates:
  - oapw_page fixture (managed browser + AiPage)
  - oapw_factory for test data generation
  - oapw_accessibility for WCAG audit
  - oapw_performance for Web Vitals
  - page.ai() for natural-language interactions
  - page.ai_assert() for natural-language assertions

Run with::

    poetry run pytest examples/test_login_flow.py -v \
        --OAPW_APP_BASE_URL=http://localhost:3000
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

BASE_URL = "http://localhost:3000"  # override via OAPW_APP_BASE_URL


async def test_login_valid_credentials(oapw_page, oapw_factory):
    """Happy path: valid credentials → dashboard visible."""
    creds = oapw_factory.build("credentials")

    await oapw_page.goto(f"{BASE_URL}/login")
    await oapw_page.ai(f"Fill the email input with '{creds.email}'")
    await oapw_page.ai(f"Fill the password input with '{creds.password}'")
    await oapw_page.ai("Click the Sign In button")
    await oapw_page.ai_assert("I am on the dashboard or home page after logging in")


async def test_login_invalid_password(oapw_page, oapw_factory):
    """Negative path: wrong password → error message shown."""
    creds = oapw_factory.build("credentials")

    await oapw_page.goto(f"{BASE_URL}/login")
    await oapw_page.ai(f"Fill the email input with '{creds.email}'")
    await oapw_page.ai("Fill the password input with 'wrong_password_xyz'")
    await oapw_page.ai("Click the Sign In button")
    await oapw_page.ai_assert("An error message is visible indicating invalid credentials")


async def test_login_empty_fields(oapw_page):
    """Edge case: submit with empty fields → validation errors shown."""
    await oapw_page.goto(f"{BASE_URL}/login")
    await oapw_page.ai("Click the Sign In button without filling any fields")
    await oapw_page.ai_assert("Validation errors or required field messages are visible")


async def test_login_accessibility(oapw_page, oapw_accessibility):
    """Accessibility: login page should have no critical WCAG violations."""
    await oapw_page.goto(f"{BASE_URL}/login")
    report = await oapw_accessibility.check(oapw_page.page)
    report.assert_no_critical()


async def test_login_page_performance(oapw_page, oapw_performance):
    """Performance: login page should load within acceptable thresholds."""
    await oapw_page.goto(f"{BASE_URL}/login")
    metrics = await oapw_performance.capture(oapw_page.page)
    metrics.assert_ttfb_under(1000)   # TTFB < 1s
    metrics.assert_fcp_under(2000)    # FCP < 2s


async def test_login_visual_regression(oapw_page, oapw_visual):
    """Visual: login page should not change appearance unexpectedly."""
    await oapw_page.goto(f"{BASE_URL}/login")
    diff = await oapw_visual.compare(oapw_page.page, "login_page")
    diff.assert_within_threshold()  # max 2% pixel change
