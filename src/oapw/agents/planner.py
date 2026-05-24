"""Planner agent — converts a natural language goal into an ordered list of Steps.

Cache key: hash(goal + page_signature + model) so re-runs on the same page
are instant. TTL matches the plan cache (1 day by default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.agents.models import Plan, Step
from oapw.cache.manager import get_cache
from oapw.core.browser import get_page_signature
from oapw.core.config import get_config
from oapw.core.dom import get_dom_context
from oapw.core.ollama_client import OllamaClient, get_ollama_client

if TYPE_CHECKING:
    from playwright.async_api import Page

from pydantic import BaseModel


class _PlannerResponse(BaseModel):
    steps: list[Step]


class Planner:
    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()

    async def plan(self, goal: str, page: "Page") -> Plan:
        """Convert a natural language goal into a Plan (ordered Step list)."""
        sig = await get_page_signature(page)
        cache_key = self._ollama.prompt_hash(
            f"plan:{goal}:{sig}", self._model, 0.0
        )

        cached = self._cache.get_plan(cache_key)
        if cached:
            return Plan.model_validate(cached)

        url = page.url
        dom_ctx = await get_dom_context(page)
        prompt = prompts.render(
            "planner.j2",
            goal=goal,
            url=url,
            dom_context=dom_ctx,
        )

        response = await self._ollama.generate_structured(
            prompt=prompt,
            schema=_PlannerResponse,
            model=self._model,
            temperature=0.1,
        )

        plan = Plan(goal=goal, steps=response.steps)
        self._cache.set_plan(cache_key, plan.model_dump())
        return plan
