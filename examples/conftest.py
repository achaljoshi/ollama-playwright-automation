"""Example conftest.py — project-level fixtures for integration tests.

Copy this to your project root and customise for your app.
"""

from __future__ import annotations

import os

import pytest


# ── Base URL ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL of the application under test.

    Can be overridden via the OAPW_APP_BASE_URL environment variable.
    """
    return os.getenv("OAPW_APP_BASE_URL", "http://localhost:3000")


# ── Authenticated page ────────────────────────────────────────────────────────

@pytest.fixture
async def auth_page(oapw_hybrid, base_url):
    """A HybridContext pre-authenticated via the API.

    Logs in with the default test credentials before yielding.
    Override OAPW_TEST_EMAIL / OAPW_TEST_PASSWORD to customise.
    """
    email = os.getenv("OAPW_TEST_EMAIL", "test@example.com")
    password = os.getenv("OAPW_TEST_PASSWORD", "test123")

    await oapw_hybrid.login_via_api(
        "/api/auth/login",
        email=email,
        password=password,
    )
    await oapw_hybrid.page.page.goto(f"{base_url}/dashboard")
    yield oapw_hybrid
