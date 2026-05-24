"""oapw pytest plugin — fixtures for browser, API, hybrid, and factory access.

Registered automatically when the package is installed (via the
``pytest11`` entry point in pyproject.toml). You don't need to import
anything — just use the fixture names in your tests.

Available fixtures:
    oapw_config         OapwConfig instance (function scope)
    oapw_page           AiPage in a managed browser context (function scope)
    oapw_api_context    Playwright APIRequestContext (function scope, no browser)
    oapw_factory        FactoryRegistry instance (function scope)

Example:
    async def test_login(oapw_page, oapw_factory):
        user = oapw_factory.build("credentials")
        await oapw_page.goto("http://localhost:3000/login")
        await oapw_page.ai(f"Fill the email input with '{user.email}'")
        await oapw_page.ai(f"Fill the password input with '{user.password}'")
        await oapw_page.ai("Click Sign In")
        await oapw_page.ai_assert("Redirected to the dashboard")
"""

from __future__ import annotations

import pytest


# ── Config ────────────────────────────────────────────────────────────────────

@pytest.fixture
def oapw_config():
    """Provide the OapwConfig singleton.

    Resets after the test so env-var changes in one test don't bleed into others.
    """
    from oapw.core.config import get_config, reset_config
    reset_config()
    cfg = get_config()
    yield cfg
    reset_config()


# ── Browser page ──────────────────────────────────────────────────────────────

@pytest.fixture
async def oapw_page(oapw_config):
    """Provide an AiPage in a freshly created browser context.

    The browser is started and torn down automatically.
    Tracing can be enabled via ``OAPW_BROWSER_TRACE=1`` in the environment.
    """
    import os
    from oapw.core.browser import managed_browser
    from oapw.core.ai_page import AiPage

    trace = os.getenv("OAPW_BROWSER_TRACE", "0") == "1"
    async with managed_browser() as mgr:
        async with mgr.new_page(trace=trace, trace_name="oapw_trace") as page:
            yield AiPage(page)


# ── Standalone API context (no browser) ──────────────────────────────────────

@pytest.fixture
async def oapw_api_context(oapw_config):
    """Provide a Playwright APIRequestContext for API-only tests.

    Does NOT share cookies with a browser (no browser is launched).
    For cookie sharing, use the ``oapw_hybrid`` fixture instead.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.request.new_context(
            base_url=oapw_config.app_api_base_url or oapw_config.app_base_url,
        )
        try:
            yield ctx
        finally:
            await ctx.dispose()


# ── Hybrid API+UI context ─────────────────────────────────────────────────────

@pytest.fixture
async def oapw_hybrid(oapw_config):
    """Provide a HybridContext — AiPage + ApiClient sharing the same cookie jar.

    Ideal for tests that:
      - Log in via API (fast) then test protected UI pages
      - Set up test data via API, verify through the UI
      - Make API assertions after UI actions

    Example::

        async def test_admin_flow(oapw_hybrid):
            await oapw_hybrid.login_via_api("/api/auth/login",
                                            email="admin@example.com",
                                            password="secret")
            await oapw_hybrid.page.goto("/admin")
            await oapw_hybrid.page.ai_assert("Admin dashboard is visible")
            await oapw_hybrid.verify_via_api("/api/health", {"status": "ok"})
    """
    from oapw.core.browser import managed_browser
    from oapw.hybrid.context import HybridContext

    async with managed_browser() as mgr:
        async with mgr.new_context() as ctx:
            page = await ctx.new_page()
            hybrid = await HybridContext.from_context(ctx, page)
            yield hybrid


# ── Test data factories ────────────────────────────────────────────────────────

@pytest.fixture
def oapw_factory():
    """Provide a FactoryRegistry for generating test data.

    Example::

        def test_registration_form(oapw_page, oapw_factory):
            user = oapw_factory.build("user")
            # user.email, user.password, user.first_name, etc.
    """
    from oapw.factories.common import FactoryRegistry
    return FactoryRegistry()


# ── PII masker ────────────────────────────────────────────────────────────────

@pytest.fixture
def oapw_pii_masker():
    """Provide the PiiMasker singleton for security-sensitive tests."""
    from oapw.security.pii import get_pii_masker
    return get_pii_masker()


# ── Phase 9 verification fixtures ────────────────────────────────────────────

@pytest.fixture
def oapw_accessibility():
    """Provide an AccessibilityChecker for WCAG audits.

    Example::

        async def test_login_a11y(oapw_page, oapw_accessibility):
            await oapw_page.goto("/login")
            report = await oapw_accessibility.check(oapw_page.page)
            report.assert_no_critical()
    """
    from oapw.verification.accessibility import AccessibilityChecker
    return AccessibilityChecker()


@pytest.fixture
def oapw_performance():
    """Provide a PerformanceCapture for Web Vitals measurement.

    Example::

        async def test_homepage_perf(oapw_page, oapw_performance):
            await oapw_page.goto("/")
            metrics = await oapw_performance.capture(oapw_page.page)
            metrics.assert_ttfb_under(600)
            metrics.assert_fcp_under(1500)
    """
    from oapw.verification.performance import PerformanceCapture
    return PerformanceCapture()


@pytest.fixture
def oapw_visual(tmp_path):
    """Provide a VisualChecker scoped to the test's tmp_path.

    On first run the baseline is captured automatically.
    On subsequent runs a pixel diff is computed.

    Example::

        async def test_homepage_visual(oapw_page, oapw_visual):
            await oapw_page.goto("/")
            diff = await oapw_visual.compare(oapw_page.page, "homepage")
            diff.assert_within_threshold()
    """
    from oapw.verification.visual import VisualChecker
    return VisualChecker(baselines_dir=tmp_path / "baselines")


# ── QA Agent fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def oapw_qa_agent():
    """Provide a QaOrchestrator for in-test QA agent runs.

    Example::

        async def test_login_regression(oapw_qa_agent):
            result = await oapw_qa_agent.run("smoke test the login flow")
            assert result.pass_rate == 1.0
    """
    from oapw.qa_agent.orchestrator import QaOrchestrator
    return QaOrchestrator(print_report=False)
