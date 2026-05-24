"""GoalParser — converts a free-text QA goal into a structured QaGoal.

The parser delegates to the LLM via a Jinja2 prompt template, returning a
:class:`~oapw.qa_agent.models.QaGoal` with extracted intent, scope, feature
areas, and environment hints.

Results are cached by the LLM cache so repeated identical goals are instant.

Usage::

    parser = GoalParser()
    goal = await parser.parse("run login regression on QA")
    print(goal.scope)          # regression
    print(goal.feature_areas)  # ["login"]
    print(goal.environment)    # "qa"
"""

from __future__ import annotations

import oapw.prompts as prompts
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.ollama_client import OllamaClient, get_ollama_client
from oapw.qa_agent.models import QaGoal, TestScope

from pydantic import BaseModel


class _GoalParseResponse(BaseModel):
    intent: str
    scope: TestScope = TestScope.SMOKE
    feature_areas: list[str] = []
    environment: str = ""
    jira_refs: list[str] = []
    confidence: float = 0.5


class GoalParser:
    """Parses a natural-language QA goal into a :class:`QaGoal`.

    Parameters
    ----------
    ollama:
        LLM client to use. Created from config if *None*.
    model:
        Override the default LLM model.
    """

    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()

    async def parse(self, goal: str) -> QaGoal:
        """Parse *goal* into a :class:`QaGoal`.

        Returns a cached result if the same goal was parsed before.
        """
        cache_key = self._ollama.prompt_hash(
            f"goal_parse:{goal}", self._model, 0.1
        )
        cached = self._cache.get_llm(cache_key)
        if cached:
            resp = _GoalParseResponse.model_validate(cached)
        else:
            prompt_text = prompts.render("goal_parse.j2", goal=goal)
            resp = await self._ollama.generate_structured(
                prompt=prompt_text,
                schema=_GoalParseResponse,
                model=self._model,
                temperature=0.1,
            )
            self._cache.set_llm(cache_key, resp.model_dump())

        return QaGoal(
            raw=goal,
            intent=resp.intent,
            scope=resp.scope,
            feature_areas=resp.feature_areas,
            environment=resp.environment,
            jira_refs=resp.jira_refs,
            confidence=resp.confidence,
        )
