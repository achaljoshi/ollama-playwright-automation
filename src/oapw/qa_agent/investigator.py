"""Investigator — digs into failures and drafts JIRA bug reports.

When the JudgmentEngine classifies a failure as real_bug (or unclear with
high confidence) the Investigator:

1. Searches Jira for related bugs in the same component
2. Lists recent git commits touching relevant files (best-effort)
3. Checks whether related tests are also failing (from QA Memory)
4. Asks the LLM to draft a JIRA bug title + description

The output is an :class:`~oapw.qa_agent.models.Investigation` record that the
Reporter can format into a Slack message or a JIRA creation payload.

Usage::

    investigator = Investigator()
    investigation = await investigator.investigate(
        test_name="test_forgot_password",
        error="AssertionError: modal not visible",
        judgment=judgment,
    )
    print(investigation.jira_draft_title)
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.ollama_client import OllamaClient, get_ollama_client
from oapw.qa_agent.models import Investigation, Judgment

from pydantic import BaseModel

if TYPE_CHECKING:
    pass


class _DraftResponse(BaseModel):
    title: str
    description: str


class Investigator:
    """Builds an :class:`Investigation` for a failed test.

    Parameters
    ----------
    ollama:
        LLM client. Created from config if *None*.
    model:
        Override the default LLM model.
    atlassian:
        Optional Atlassian client for Jira history lookup.
    memory:
        Optional :class:`~oapw.qa_agent.memory.QaMemory` for cross-test
        failure correlation.
    """

    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
        atlassian: object | None = None,
        memory: object | None = None,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._atlassian = atlassian
        self._memory = memory
        self._cache = get_cache()

    async def investigate(
        self,
        test_name: str,
        error: str,
        judgment: Judgment,
        confluence_context: str = "",
    ) -> Investigation:
        """Build an :class:`Investigation` for *test_name*.

        Collects related Jira, recent commits, correlated failures, then
        asks the LLM to draft a JIRA bug report.
        """
        # 1. Related Jira issues
        related_jira = await self._related_jira(test_name, error)

        # 2. Recent commits (best-effort git log)
        recent_commits = _recent_commits()

        # 3. Other tests failing in the same run (from memory)
        related_failing = self._correlated_failures(test_name)

        # 4. Draft Jira bug
        title, description = await self._draft_bug(
            test_name=test_name,
            error=error,
            judgment=judgment,
            related_jira=related_jira,
            recent_commits=recent_commits,
            confluence_context=confluence_context,
        )

        return Investigation(
            test_name=test_name,
            related_jira=related_jira,
            recent_commits=recent_commits,
            related_tests_failing=related_failing,
            notes=[judgment.hypothesis] if judgment.hypothesis else [],
            jira_draft=description,
            jira_draft_title=title,
        )

    # ── Jira history ─────────────────────────────────────────────────────────

    async def _related_jira(self, test_name: str, error: str) -> list[str]:
        """Search Jira for bugs related to the failing test."""
        if self._atlassian is None:
            return []
        try:
            # Extract feature hint from test_name
            parts = test_name.replace("test_", "").split("_")
            keywords = " ".join(parts[:3])
            issues = await self._atlassian.search_issues(  # type: ignore[union-attr]
                jql=f'text ~ "{keywords}" AND issuetype = Bug ORDER BY created DESC',
                max_results=5,
            )
            return [i.get("key", "") for i in (issues or []) if i.get("key")]
        except Exception:
            return []

    # ── Git commits ───────────────────────────────────────────────────────────

    # ── Correlated failures ───────────────────────────────────────────────────

    def _correlated_failures(self, test_name: str) -> list[str]:
        """Return recently failing tests from memory (excluding *test_name*)."""
        if self._memory is None:
            return []
        try:
            failures = self._memory.recent_failures(n=20)  # type: ignore[union-attr]
            return [
                r.test_name
                for r in failures
                if r.test_name != test_name
            ][:5]
        except Exception:
            return []

    # ── Bug draft ─────────────────────────────────────────────────────────────

    async def _draft_bug(
        self,
        test_name: str,
        error: str,
        judgment: Judgment,
        related_jira: list[str],
        recent_commits: list[str],
        confluence_context: str,
    ) -> tuple[str, str]:
        """Call the LLM to draft a JIRA bug title + description."""
        cache_key = self._ollama.prompt_hash(
            f"investigate:{test_name}:{error}", self._model, 0.0
        )
        cached = self._cache.get_llm(cache_key)
        if cached:
            resp = _DraftResponse.model_validate(cached)
            return resp.title, resp.description

        prompt_text = prompts.render(
            "investigate.j2",
            test_name=test_name,
            error=error,
            classification=judgment.classification.value,
            confidence=judgment.confidence,
            hypothesis=judgment.hypothesis,
            related_jira=related_jira,
            recent_commits=recent_commits,
            confluence_context=confluence_context,
        )
        resp = await self._ollama.generate_structured(
            prompt=prompt_text,
            schema=_DraftResponse,
            model=self._model,
            temperature=0.1,
        )
        self._cache.set_llm(cache_key, resp.model_dump())
        return resp.title, resp.description


# ── Helpers ───────────────────────────────────────────────────────────────────

def _recent_commits(n: int = 5) -> list[str]:
    """Return up to *n* recent git log lines from the current repo (best-effort)."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{n}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    except Exception:
        pass
    return []
