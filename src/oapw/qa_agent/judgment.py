"""JudgmentEngine — classifies a test failure using LLM + KB context.

Given a failed test, its error, and optional Confluence/Jira context, the
engine returns a :class:`~oapw.qa_agent.models.Judgment` with:

- classification (real_bug / flaky / env_issue / data_issue / unclear)
- confidence (0–1)
- hypothesis (one sentence)
- evidence list
- suggested_action

If ``use_kb=True`` the engine fetches relevant Confluence pages and Jira
history before calling the LLM, making the classification far more accurate.

Usage::

    engine = JudgmentEngine()
    judgment = await engine.judge(
        test_name="test_forgot_password",
        expected_behavior="Modal should appear (Confluence §3.2)",
        observed_error="AssertionError: no modal visible after 5s",
    )
    print(judgment.classification)   # real_bug
    print(judgment.confidence)       # 0.87
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.ollama_client import OllamaClient, get_ollama_client
from oapw.qa_agent.models import (
    Judgment,
    JudgmentClassification,
    SuggestedAction,
)
from pydantic import BaseModel

if TYPE_CHECKING:
    pass


class _JudgmentResponse(BaseModel):
    classification: JudgmentClassification
    confidence: float = 0.5
    hypothesis: str = ""
    evidence: list[str] = []
    suggested_action: SuggestedAction = SuggestedAction.INVESTIGATE


class JudgmentEngine:
    """Classifies a test failure with LLM assistance.

    Parameters
    ----------
    ollama:
        LLM client. Created from config if *None*.
    model:
        Override the default LLM model.
    kb:
        Optional knowledge base for fetching Confluence / Jira context.
    use_kb:
        Whether to fetch KB context before judging (default: True).
    """

    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
        kb: object | None = None,
        use_kb: bool = True,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._kb = kb
        self._use_kb = use_kb
        self._cache = get_cache()

    async def judge(
        self,
        test_name: str,
        expected_behavior: str,
        observed_error: str,
        dom_diff: str = "",
        extra_context: str = "",
        jira_refs: list[str] | None = None,
    ) -> Judgment:
        """Classify *observed_error* for *test_name*.

        Returns a :class:`Judgment` with classification + confidence + evidence.
        Results are cached so the same failure classification is instant on
        subsequent runs.
        """
        cache_key = self._ollama.prompt_hash(
            f"judgment:{test_name}:{observed_error}:{self._model}", self._model, 0.0
        )
        cached = self._cache.get_llm(cache_key)
        if cached:
            resp = _JudgmentResponse.model_validate(cached)
            return self._to_judgment(resp)

        confluence_context = ""
        jira_context = ""

        if self._use_kb and self._kb is not None:
            confluence_context, jira_context = await self._fetch_kb_context(
                test_name, expected_behavior, jira_refs or []
            )

        prompt_text = prompts.render(
            "judgment.j2",
            test_name=test_name,
            expected_behavior=expected_behavior,
            observed_error=observed_error,
            dom_diff=dom_diff,
            confluence_context=confluence_context or extra_context,
            jira_context=jira_context,
        )

        resp = await self._ollama.generate_structured(
            prompt=prompt_text,
            schema=_JudgmentResponse,
            model=self._model,
            temperature=0.0,
        )
        self._cache.set_llm(cache_key, resp.model_dump())
        return self._to_judgment(resp)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _fetch_kb_context(
        self, test_name: str, query: str, jira_refs: list[str]
    ) -> tuple[str, str]:
        """Fetch Confluence and Jira context from the KB."""
        if self._kb is None:
            return "", ""
        try:
            results = await self._kb.search(  # type: ignore[union-attr]
                query=query,
                top_k=3,
                linked_jira=jira_refs or None,
            )
            snippets = [r.get("text", "") for r in results if r.get("text")]
            return "\n\n".join(snippets[:3]), ""
        except Exception:
            return "", ""

    @staticmethod
    def _to_judgment(resp: _JudgmentResponse) -> Judgment:
        return Judgment(
            classification=resp.classification,
            confidence=resp.confidence,
            hypothesis=resp.hypothesis,
            evidence=resp.evidence,
            suggested_action=resp.suggested_action,
        )
