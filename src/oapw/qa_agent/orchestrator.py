"""QaOrchestrator — the top-level QA Agent entry point.

Ties together the entire QA Agent Mode pipeline:

    GoalParser → TestSelector → SmartExecutor → JudgmentEngine
        → Investigator → QaMemory → ConsoleReporter

Invoked via ``oapw qa "..."`` CLI or programmatically.

Flow (per PLAN.md §7.3)
────────────────────────
1. Parse the user goal → :class:`QaGoal`
2. Select relevant tests → ``list[TestCandidate]``
3. Execute each test → ``list[TestRunResult]``
4. For each failure: judge, then investigate if confidence warrants it
5. Persist results to :class:`QaMemory`
6. Report to :class:`ConsoleReporter` (and optionally to Slack)

Usage::

    orchestrator = QaOrchestrator()
    result = await orchestrator.run("regression of the login flow on QA")
    print(result.pass_rate)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from oapw.core.config import get_config
from oapw.core.ollama_client import OllamaClient, get_ollama_client
from oapw.qa_agent.goal_parser import GoalParser
from oapw.qa_agent.investigator import Investigator
from oapw.qa_agent.judgment import JudgmentEngine
from oapw.qa_agent.memory import QaMemory
from oapw.qa_agent.models import (
    JudgmentClassification,
    QaRunResult,
    SuggestedAction,
    TestRunResult,
)
from oapw.qa_agent.reporter.console import ConsoleReporter
from oapw.qa_agent.smart_executor import SmartExecutor
from oapw.qa_agent.test_selector import TestSelector

if TYPE_CHECKING:
    pass

# Classifications that warrant investigation
_INVESTIGATE_WHEN = {
    JudgmentClassification.REAL_BUG,
    JudgmentClassification.UNCLEAR,
}


class QaOrchestrator:
    """Autonomous QA agent that runs from a natural-language goal.

    Parameters
    ----------
    ollama:
        LLM client. Created from config if *None*.
    model:
        Override the default LLM model.
    kb:
        Optional knowledge base for richer test selection and judgment.
    atlassian:
        Optional Atlassian client for Jira history lookups.
    memory:
        :class:`QaMemory` instance. Created fresh if *None*.
    reporter:
        Reporter instance. Defaults to :class:`ConsoleReporter`.
    top_k:
        Max number of tests to select per run.
    investigate_bugs:
        Whether to run the Investigator on real_bug / unclear judgments.
    print_report:
        Whether to print the console report after the run.
    """

    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
        kb: object | None = None,
        atlassian: object | None = None,
        memory: QaMemory | None = None,
        reporter: object | None = None,
        top_k: int = 20,
        investigate_bugs: bool = True,
        print_report: bool = True,
    ) -> None:
        cfg = get_config()
        self._ollama = ollama or get_ollama_client()
        self._model = model or cfg.ollama_default_model
        self._kb = kb
        self._memory = memory or QaMemory()
        self._reporter = reporter or ConsoleReporter()
        self._top_k = top_k
        self._investigate_bugs = investigate_bugs
        self._print_report = print_report

        self._goal_parser = GoalParser(ollama=self._ollama, model=self._model)
        self._test_selector = TestSelector(memory=self._memory, kb=kb)
        self._executor = SmartExecutor(base_url=cfg.app_base_url)
        self._judgment_engine = JudgmentEngine(
            ollama=self._ollama, model=self._model, kb=kb, use_kb=(kb is not None)
        )
        self._investigator = Investigator(
            ollama=self._ollama,
            model=self._model,
            atlassian=atlassian,
            memory=self._memory,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, goal_text: str) -> QaRunResult:
        """Execute the full QA Agent pipeline for *goal_text*.

        Returns a :class:`QaRunResult` with per-test judgments and
        optionally investigations for real bugs.
        """
        wall_start = time.monotonic()

        # 1. Parse goal
        goal = await self._goal_parser.parse(goal_text)

        # 2. Select tests
        candidates = await self._test_selector.select(goal, top_k=self._top_k)

        # 3. Execute
        raw_results = await self._executor.execute_all(candidates)

        # 4. Judge + Investigate failures
        enriched_results: list[TestRunResult] = []
        for result in raw_results:
            enriched = await self._enrich(result)
            self._memory.record_result(enriched)
            enriched_results.append(enriched)

        # 5. Assemble run result
        finished_at = datetime.now(timezone.utc).isoformat()
        qa_result = QaRunResult(
            goal=goal,
            tests_run=enriched_results,
            finished_at=finished_at,
            duration_ms=(time.monotonic() - wall_start) * 1000,
            environment=goal.environment,
        )

        # 6. Report
        if self._print_report:
            self._reporter.report(qa_result)  # type: ignore[union-attr]

        return qa_result

    # ── Enrichment ────────────────────────────────────────────────────────────

    async def _enrich(self, result: TestRunResult) -> TestRunResult:
        """Add judgment (and optionally investigation) to *result*."""
        if result.passed:
            # For passing tests, set a trivial pass judgment without LLM call
            from oapw.qa_agent.models import Judgment, JudgmentClassification, SuggestedAction
            judgment = Judgment(
                classification=JudgmentClassification.PASS,
                confidence=1.0,
                hypothesis="",
                evidence=[],
                suggested_action=SuggestedAction.IGNORE,
            )
            return result.model_copy(update={"judgment": judgment})

        # Failing test — judge it
        judgment = await self._judgment_engine.judge(
            test_name=result.test_name,
            expected_behavior=f"Test {result.test_name} should pass",
            observed_error=result.error or "Test failed with no error message",
        )
        enriched = result.model_copy(update={"judgment": judgment})

        # Escalate — investigate if warranted
        if (
            self._investigate_bugs
            and judgment.classification in _INVESTIGATE_WHEN
            and judgment.confidence >= 0.5
        ):
            investigation = await self._investigator.investigate(
                test_name=result.test_name,
                error=result.error or "",
                judgment=judgment,
            )
            enriched = enriched.model_copy(update={"investigation": investigation})

        return enriched
