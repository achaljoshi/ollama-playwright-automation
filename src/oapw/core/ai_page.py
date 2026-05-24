"""AiPage — wraps a Playwright Page with natural language action methods.

Usage:
    async with managed_browser() as mgr:
        async with mgr.new_page() as page:
            ai = AiPage(page)
            await ai.ai("Click the 'Sign in with Google' button")
            await ai.ai("Fill the email input with 'user@example.com'")
            price = await ai.ai_extract("Price of the first product as a number")
            await ai.ai_assert("Cart shows 1 item at ₹49,999")

AiPage delegates all standard Playwright methods to the underlying page
via __getattr__, so existing page.goto(), page.locator() etc. still work.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from oapw.agents.executor import Executor
from oapw.agents.locator_resolver import LocatorResolver
from oapw.agents.models import Step, StepAction, ExtractionResult
from oapw.agents.planner import Planner
from oapw.core.config import get_config
from oapw.core.ollama_client import get_ollama_client

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator


class AiPage:
    """Playwright Page wrapper with natural language action methods."""

    def __init__(
        self,
        page: "Page",
        model: str | None = None,
    ) -> None:
        self._page = page
        model = model or get_config().ollama_default_model
        ollama = get_ollama_client()
        self._resolver = LocatorResolver(ollama=ollama, model=model)
        self._executor = Executor(ollama=ollama, model=model, resolver=self._resolver)
        self._planner = Planner(ollama=ollama, model=model)

    # ── Natural language actions ───────────────────────────────────────────────

    async def ai(self, intent: str) -> None:
        """Execute a single natural language browser action.

        Examples:
            await page.ai("Click the 'Sign in with Google' button")
            await page.ai("Fill the email field with 'user@example.com'")
            await page.ai("Select 'India' from the country dropdown")
        """
        step = _intent_to_step(intent)
        result = await self._executor.execute_step(step, self._page)
        if not result.success:
            raise AiActionError(f"ai({intent!r}) failed: {result.error}")

    async def ai_extract(self, query: str) -> Any:
        """Extract structured data from the page using natural language.

        Examples:
            price = await page.ai_extract("Price of first product as a number")
            items = await page.ai_extract("List of all product names")
        """
        step = Step(
            action=StepAction.EXTRACT,
            target=None,
            value=query,
            description=f"Extract: {query}",
        )
        result = await self._executor.execute_step(step, self._page)
        if not result.success:
            raise AiActionError(f"ai_extract({query!r}) failed: {result.error}")
        return result.extracted_value

    async def ai_assert(self, assertion: str) -> None:
        """Assert something about the page state in natural language.

        Raises AssertionError if the assertion fails.

        Examples:
            await page.ai_assert("Cart shows 1 laptop at ₹49,999")
            await page.ai_assert("Login error message is visible")
        """
        step = Step(
            action=StepAction.ASSERT,
            target=None,
            value=assertion,
            description=f"Assert: {assertion}",
        )
        result = await self._executor.execute_step(step, self._page)
        if not result.success:
            raise AssertionError(result.error or f"Assertion failed: {assertion!r}")

    async def ai_do(self, goal: str) -> list:
        """Execute a multi-step natural language goal using the Planner.

        The Planner breaks the goal into steps; the Executor runs them.
        Returns a list of StepResult objects.

        Example:
            await page.ai_do("Log in with email 'user@example.com' and password 'secret'")
        """
        plan = await self._planner.plan(goal, self._page)
        return await self._executor.execute_plan(plan.steps, self._page)

    # ── Direct locator resolution ─────────────────────────────────────────────

    async def ai_locator(self, intent: str) -> "Locator":
        """Resolve a natural language description to a Playwright Locator.

        Example:
            btn = await page.ai_locator("the submit button")
            await btn.click()
        """
        return await self._resolver.resolve(intent, self._page)

    # ── Delegate all standard Playwright Page API ─────────────────────────────

    def __getattr__(self, name: str) -> Any:
        return getattr(self._page, name)

    @property
    def page(self) -> "Page":
        return self._page


class AiActionError(RuntimeError):
    pass


# ── Intent → Step heuristic ──────────────────────────────────────────────────

import re as _re

_ACTION_MAP = {
    _re.compile(r"^(click|press|tap)\b", _re.I): StepAction.CLICK,
    _re.compile(r"^(fill|type|enter|input)\b", _re.I): StepAction.FILL,
    _re.compile(r"^(select|choose|pick)\b", _re.I): StepAction.SELECT,
    _re.compile(r"^(hover|mouse over)\b", _re.I): StepAction.HOVER,
    _re.compile(r"^(navigate|go to|open|visit)\b", _re.I): StepAction.NAVIGATE,
    _re.compile(r"^(wait|wait for)\b", _re.I): StepAction.WAIT,
    _re.compile(r"^(scroll)\b", _re.I): StepAction.SCROLL,
    _re.compile(r"^(press key|hit)\b", _re.I): StepAction.PRESS,
}

_FILL_VALUE_RE = _re.compile(r"\bwith\s+['\"](.+?)['\"]", _re.I)
_NAV_URL_RE = _re.compile(r"https?://\S+", _re.I)


def _intent_to_step(intent: str) -> Step:
    """Best-effort: map a single natural language string to a Step."""
    for pattern, action in _ACTION_MAP.items():
        if pattern.match(intent):
            value: str | None = None
            target = intent

            if action == StepAction.FILL:
                m = _FILL_VALUE_RE.search(intent)
                value = m.group(1) if m else None
                target = _FILL_VALUE_RE.sub("", intent).strip()

            elif action == StepAction.NAVIGATE:
                m = _NAV_URL_RE.search(intent)
                value = m.group(0) if m else intent
                target = None

            return Step(action=action, target=target, value=value, description=intent)

    # Default: treat as a click
    return Step(action=StepAction.CLICK, target=intent, value=None, description=intent)
