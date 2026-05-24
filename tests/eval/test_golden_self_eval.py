"""Golden self-eval suite — runs against a real Chromium browser (no live website).

Pages are loaded via page.set_content() so no network is needed.
Each test verifies the LocatorResolver can find expected elements deterministically.

Run with:
    poetry run pytest tests/eval/ -v
"""

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright, Browser, Page

from oapw.agents.locator_resolver import LocatorResolver
from oapw.eval.golden_pages import (
    LOGIN_PAGE, LOGIN_BROKEN_PAGE,
    SEARCH_PAGE, SEARCH_BROKEN_PAGE,
    REGISTRATION_PAGE, PRODUCT_PAGE,
    CANONICAL_PAGES,
)
from oapw.eval.golden_suite import run_canonical_eval
from oapw.eval.metrics import MetricsCollector


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def browser():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        yield b
        await b.close()


@pytest_asyncio.fixture
async def page(browser: Browser):
    context = await browser.new_context()
    p = await context.new_page()
    yield p
    await context.close()


# ── Canonical resolution tests ────────────────────────────────────────────────

@pytest.mark.parametrize("golden", CANONICAL_PAGES, ids=[p.name for p in CANONICAL_PAGES])
async def test_canonical_resolution(page: Page, golden):
    """All intents on canonical pages must resolve successfully."""
    resolver = LocatorResolver()
    records = await run_canonical_eval(page, golden, resolver=resolver)
    failures = [r for r in records if not r.resolved]
    assert not failures, (
        f"{golden.name}: failed to resolve: {[r.intent for r in failures]}"
    )


# ── Login form — element-by-element ──────────────────────────────────────────

async def test_login_email_input(page: Page):
    await page.set_content(LOGIN_PAGE.html, wait_until="domcontentloaded")
    loc = await LocatorResolver().resolve("Email address input", page)
    assert await loc.is_visible()
    assert await loc.evaluate("el => el.tagName.toLowerCase()") == "input"


async def test_login_password_input(page: Page):
    await page.set_content(LOGIN_PAGE.html, wait_until="domcontentloaded")
    loc = await LocatorResolver().resolve("Password input", page)
    assert await loc.get_attribute("type") == "password"


async def test_login_submit_button(page: Page):
    await page.set_content(LOGIN_PAGE.html, wait_until="domcontentloaded")
    loc = await LocatorResolver().resolve("Sign in button", page)
    assert await loc.is_visible()
    assert await loc.evaluate("el => el.tagName.toLowerCase()") == "button"


async def test_login_forgot_link(page: Page):
    await page.set_content(LOGIN_PAGE.html, wait_until="domcontentloaded")
    loc = await LocatorResolver().resolve("Forgot password link", page)
    assert await loc.is_visible()
    assert await loc.evaluate("el => el.tagName.toLowerCase()") == "a"


# ── Search form ───────────────────────────────────────────────────────────────

async def test_search_input(page: Page):
    await page.set_content(SEARCH_PAGE.html, wait_until="domcontentloaded")
    loc = await LocatorResolver().resolve("Search input", page)
    assert await loc.is_visible()


async def test_search_button(page: Page):
    await page.set_content(SEARCH_PAGE.html, wait_until="domcontentloaded")
    loc = await LocatorResolver().resolve("Search button", page)
    assert await loc.is_visible()


# ── Healing tests (fingerprint + role/text variant — no LLM) ─────────────────

async def test_login_heals_email_after_id_change(page: Page):
    """After IDs/labels change, email input must still be found via fingerprint."""
    resolver = LocatorResolver()
    await page.set_content(LOGIN_PAGE.html, wait_until="domcontentloaded")
    await resolver.resolve("Email address input", page)

    await page.set_content(LOGIN_BROKEN_PAGE.html, wait_until="domcontentloaded")
    loc = await resolver.resolve("Email address input", page)
    assert await loc.is_visible()
    assert await loc.evaluate("el => el.tagName.toLowerCase()") == "input"


async def test_login_button_heals_after_text_rename(page: Page):
    """Sign in → Login rename: healed via role+text-variant strategy."""
    resolver = LocatorResolver()
    await page.set_content(LOGIN_PAGE.html, wait_until="domcontentloaded")
    await resolver.resolve("Sign in button", page)

    await page.set_content(LOGIN_BROKEN_PAGE.html, wait_until="domcontentloaded")
    loc = await resolver.resolve("Sign in button", page)
    assert await loc.is_visible()


async def test_search_heals_after_button_rename(page: Page):
    """Search → Find rename: healed via role-only fallback."""
    resolver = LocatorResolver()
    await page.set_content(SEARCH_PAGE.html, wait_until="domcontentloaded")
    await resolver.resolve("Search button", page)

    await page.set_content(SEARCH_BROKEN_PAGE.html, wait_until="domcontentloaded")
    loc = await resolver.resolve("Search button", page)
    assert await loc.is_visible()


# ── Eval-suite metrics gate ───────────────────────────────────────────────────

async def test_eval_suite_passes_resolution_gate(page: Page, tmp_path):
    """Full golden eval must hit ≥ 95% resolution rate — the CI gate."""
    metrics = MetricsCollector(db_path=tmp_path / "eval.db")
    resolver = LocatorResolver()
    for golden in CANONICAL_PAGES:
        await run_canonical_eval(page, golden, resolver=resolver, metrics=metrics)
    report = metrics.report()
    assert report.passed(min_resolution=0.95), (
        f"Resolution rate {report.resolution_rate:.1%} below 95% gate.\n"
        f"Details: {report.summary()}"
    )
