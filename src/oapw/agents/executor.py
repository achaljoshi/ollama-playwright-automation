"""Executor agent — runs a list of Steps against a live Playwright page.

Each step action maps to one or more Playwright calls via the LocatorResolver.
Results are collected into StepResult objects for downstream judgment / reporting.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from oapw.agents.locator_resolver import LocatorResolver, LocatorNotFoundError
from oapw.agents.models import AssertionResult, ExtractionResult, Step, StepAction, StepResult
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.dom import get_page_text
from oapw.core.ollama_client import OllamaClient, get_ollama_client
import oapw.prompts as prompts

if TYPE_CHECKING:
    from playwright.async_api import Page


class Executor:
    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
        resolver: LocatorResolver | None = None,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._resolver = resolver or LocatorResolver(ollama=self._ollama, model=self._model)
        self._cache = get_cache()

    async def execute_plan(self, steps: list[Step], page: "Page") -> list[StepResult]:
        results: list[StepResult] = []
        for step in steps:
            result = await self.execute_step(step, page)
            results.append(result)
            if not result.success:
                break  # abort on first failure
        return results

    async def execute_step(self, step: Step, page: "Page") -> StepResult:
        start = time.monotonic()
        try:
            extracted = await self._dispatch(step, page)
            return StepResult(
                step=step,
                success=True,
                extracted_value=extracted,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return StepResult(
                step=step,
                success=False,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _dispatch(self, step: Step, page: "Page") -> Any:
        cfg = get_config()
        timeout = cfg.browser_timeout

        match step.action:
            case StepAction.NAVIGATE:
                await page.goto(step.value or "", timeout=timeout)

            case StepAction.CLICK:
                loc = await self._resolver.resolve(step.target or "", page)
                await loc.click(timeout=timeout)

            case StepAction.FILL:
                loc = await self._resolver.resolve(step.target or "", page)
                await loc.fill(step.value or "", timeout=timeout)

            case StepAction.SELECT:
                loc = await self._resolver.resolve(step.target or "", page)
                await loc.select_option(step.value or "", timeout=timeout)

            case StepAction.HOVER:
                loc = await self._resolver.resolve(step.target or "", page)
                await loc.hover(timeout=timeout)

            case StepAction.PRESS:
                if step.target:
                    loc = await self._resolver.resolve(step.target, page)
                    await loc.press(step.value or "Enter", timeout=timeout)
                else:
                    await page.keyboard.press(step.value or "Enter")

            case StepAction.SCROLL:
                direction = (step.value or "down").lower()
                if direction == "to_bottom":
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                elif direction == "up":
                    await page.evaluate("window.scrollBy(0, -600)")
                else:
                    await page.evaluate("window.scrollBy(0, 600)")

            case StepAction.WAIT:
                if step.value:
                    await page.wait_for_url(step.value, timeout=timeout)
                else:
                    await page.wait_for_load_state("networkidle", timeout=timeout)

            case StepAction.ASSERT:
                result = await self._llm_assert(step.value or step.description, page)
                if not result.passed:
                    raise AssertionError(
                        f"Assertion failed (confidence={result.confidence:.2f}): "
                        f"{result.explanation}"
                    )
                return result

            case StepAction.EXTRACT:
                result = await self._llm_extract(step.value or step.description, page)
                return result.value

        return None

    # ── LLM-powered assert / extract ──────────────────────────────────────────

    async def _llm_assert(self, assertion: str, page: "Page") -> AssertionResult:
        cache_key = self._ollama.prompt_hash(
            f"assert:{assertion}:{page.url}", self._model, 0.0
        )
        cached = self._cache.get_llm(cache_key)
        if cached:
            return AssertionResult.model_validate(cached)

        page_text = await get_page_text(page)
        dom_ctx = await _short_dom(page)
        prompt = prompts.render(
            "assert.j2",
            assertion=assertion,
            page_text=page_text,
            dom_context=dom_ctx,
        )
        result = await self._ollama.generate_structured(
            prompt=prompt,
            schema=AssertionResult,
            model=self._model,
            temperature=0.0,
        )
        self._cache.set_llm(cache_key, result.model_dump())
        return result

    async def _llm_extract(self, query: str, page: "Page") -> ExtractionResult:
        cache_key = self._ollama.prompt_hash(
            f"extract:{query}:{page.url}", self._model, 0.0
        )
        cached = self._cache.get_llm(cache_key)
        if cached:
            return ExtractionResult.model_validate(cached)

        page_text = await get_page_text(page)
        prompt = prompts.render(
            "extract.j2",
            query=query,
            page_text=page_text,
        )
        result = await self._ollama.generate_structured(
            prompt=prompt,
            schema=ExtractionResult,
            model=self._model,
            temperature=0.0,
        )
        self._cache.set_llm(cache_key, result.model_dump())
        return result


async def _short_dom(page: "Page", max_elements: int = 40) -> str:
    from oapw.core.dom import get_dom_context
    return await get_dom_context(page, max_elements=max_elements)
