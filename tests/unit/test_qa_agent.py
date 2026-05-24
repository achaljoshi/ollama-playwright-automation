"""Tests for Phase 8 — QA Agent Mode.

All LLM and external service calls are mocked — no network required.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oapw.cache.manager import CacheManager
from oapw.qa_agent.models import (
    Investigation,
    Judgment,
    JudgmentClassification,
    KnownIssue,
    QaGoal,
    QaRunResult,
    SuggestedAction,
    TestCandidate,
    TestRunResult,
    TestScope,
)
from oapw.qa_agent.goal_parser import GoalParser
from oapw.qa_agent.memory import QaMemory
from oapw.qa_agent.test_selector import TestSelector
from oapw.qa_agent.judgment import JudgmentEngine
from oapw.qa_agent.investigator import Investigator
from oapw.qa_agent.reporter.console import ConsoleReporter
from oapw.qa_agent.orchestrator import QaOrchestrator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_cache() -> CacheManager:
    tmp = Path(tempfile.mkdtemp())
    return CacheManager(data_dir=tmp)


def _make_ollama(return_value: dict | None = None) -> MagicMock:
    import json
    ollama = MagicMock()
    ollama.prompt_hash = MagicMock(return_value="test_hash")
    ollama.generate_structured = AsyncMock(return_value=MagicMock(**return_value or {}))
    return ollama


def _goal(
    raw: str = "run login regression",
    scope: TestScope = TestScope.REGRESSION,
    feature_areas: list[str] | None = None,
) -> QaGoal:
    return QaGoal(
        raw=raw,
        intent="Run regression of the login flow",
        scope=scope,
        feature_areas=["login"] if feature_areas is None else feature_areas,
        environment="qa",
    )


def _judgment(
    classification: JudgmentClassification = JudgmentClassification.REAL_BUG,
    confidence: float = 0.85,
) -> Judgment:
    return Judgment(
        classification=classification,
        confidence=confidence,
        hypothesis="Modal trigger broken",
        evidence=["No network call observed"],
        suggested_action=SuggestedAction.FILE_BUG,
    )


def _pass_result(name: str = "test_login") -> TestRunResult:
    return TestRunResult(test_name=name, passed=True, duration_ms=100.0)


def _fail_result(name: str = "test_login", error: str = "Element not found") -> TestRunResult:
    return TestRunResult(test_name=name, passed=False, duration_ms=200.0, error=error)


# ── QaGoal model ─────────────────────────────────────────────────────────────

class TestQaGoalModel:
    def test_defaults(self):
        g = QaGoal(raw="test", intent="test", scope=TestScope.SMOKE)
        assert g.feature_areas == []
        assert g.jira_refs == []
        assert g.confidence == 0.0

    def test_scope_values(self):
        assert TestScope.SMOKE == "smoke"
        assert TestScope.REGRESSION == "regression"
        assert TestScope.CRITICAL == "critical"
        assert TestScope.FULL == "full"


# ── Judgment model ────────────────────────────────────────────────────────────

class TestJudgmentModel:
    def test_needs_escalation_low_confidence(self):
        j = _judgment(confidence=0.4)
        assert j.needs_escalation is True

    def test_needs_escalation_unclear(self):
        j = _judgment(classification=JudgmentClassification.UNCLEAR, confidence=0.9)
        assert j.needs_escalation is True

    def test_no_escalation_high_confidence_real_bug(self):
        j = _judgment(classification=JudgmentClassification.REAL_BUG, confidence=0.9)
        assert j.needs_escalation is False

    def test_classification_values(self):
        assert JudgmentClassification.REAL_BUG == "real_bug"
        assert JudgmentClassification.FLAKY == "flaky"
        assert JudgmentClassification.ENV_ISSUE == "env_issue"


# ── QaRunResult model ─────────────────────────────────────────────────────────

class TestQaRunResult:
    def test_total_counts(self):
        r = QaRunResult(
            goal=_goal(),
            tests_run=[_pass_result("t1"), _fail_result("t2"), _pass_result("t3")],
        )
        assert r.total == 3
        assert r.passed == 2
        assert r.failed == 1

    def test_pass_rate(self):
        r = QaRunResult(goal=_goal(), tests_run=[_pass_result(), _pass_result()])
        assert r.pass_rate == 1.0

    def test_pass_rate_empty(self):
        r = QaRunResult(goal=_goal())
        assert r.pass_rate == 0.0

    def test_real_bugs_filter(self):
        t1 = _fail_result("t1")
        t1 = t1.model_copy(update={"judgment": _judgment(JudgmentClassification.REAL_BUG)})
        t2 = _fail_result("t2")
        t2 = t2.model_copy(update={"judgment": _judgment(JudgmentClassification.FLAKY)})
        r = QaRunResult(goal=_goal(), tests_run=[t1, t2])
        assert len(r.real_bugs) == 1
        assert r.real_bugs[0].test_name == "t1"


# ── QaMemory ──────────────────────────────────────────────────────────────────

class TestQaMemory:
    def _make_memory(self) -> QaMemory:
        return QaMemory(cache=_make_cache())

    def test_record_and_retrieve_pass(self):
        memory = self._make_memory()
        memory.record_result(_pass_result("test_login"))
        history = memory._load_history()
        assert len(history) == 1
        assert history[0]["test_name"] == "test_login"

    def test_record_failure_creates_known_issue(self):
        memory = self._make_memory()
        result = _fail_result("test_login")
        result = result.model_copy(update={"judgment": _judgment(JudgmentClassification.FLAKY)})
        memory.record_result(result)
        issue = memory.get_known_issue("test_login")
        assert issue is not None
        assert issue.classification == JudgmentClassification.FLAKY

    def test_update_known_issue_increments_count(self):
        memory = self._make_memory()
        memory.update_known_issue("test_x", JudgmentClassification.FLAKY)
        memory.update_known_issue("test_x", JudgmentClassification.FLAKY)
        issue = memory.get_known_issue("test_x")
        assert issue is not None
        assert issue.occurrence_count == 2

    def test_clear_known_issue(self):
        memory = self._make_memory()
        memory.update_known_issue("test_x", JudgmentClassification.REAL_BUG)
        removed = memory.clear_known_issue("test_x")
        assert removed is True
        assert memory.get_known_issue("test_x") is None

    def test_clear_nonexistent_issue_returns_false(self):
        memory = self._make_memory()
        assert memory.clear_known_issue("nonexistent") is False

    def test_get_flaky_tests_returns_only_flaky(self):
        memory = self._make_memory()
        memory.update_known_issue("t1", JudgmentClassification.FLAKY)
        memory.update_known_issue("t2", JudgmentClassification.REAL_BUG)
        flaky = memory.get_flaky_tests()
        assert len(flaky) == 1
        assert flaky[0].test_name == "t1"

    def test_recent_failures_most_recent_first(self):
        memory = self._make_memory()
        for i in range(5):
            memory.record_result(_fail_result(f"test_{i}"))
        failures = memory.recent_failures(3)
        assert len(failures) == 3

    def test_stats_returns_counts(self):
        memory = self._make_memory()
        memory.record_result(_pass_result())
        memory.record_result(_fail_result())
        s = memory.stats()
        assert s["total_runs"] == 2
        assert s["passed"] == 1
        assert s["failed"] == 1

    def test_history_capped_at_500(self):
        memory = self._make_memory()
        for i in range(510):
            memory.record_result(_pass_result(f"test_{i}"))
        history = memory._load_history()
        assert len(history) <= 500

    def test_get_known_issue_returns_none_for_unknown(self):
        memory = self._make_memory()
        assert memory.get_known_issue("unknown_test") is None


# ── TestSelector ─────────────────────────────────────────────────────────────

class TestTestSelector:
    def _make_selector(self, history: list[dict] | None = None) -> TestSelector:
        cache = _make_cache()
        memory = QaMemory(cache=cache)
        if history:
            memory._save_history(history)
        return TestSelector(memory=memory)

    @pytest.mark.asyncio
    async def test_selects_from_memory_by_feature(self):
        history = [
            {"test_name": "test_login_valid", "passed": True},
            {"test_name": "test_checkout_flow", "passed": True},
        ]
        selector = self._make_selector(history)
        goal = _goal(feature_areas=["login"])
        candidates = await selector.select(goal, top_k=10)
        names = [c.test_name for c in candidates]
        assert "test_login_valid" in names
        assert "test_checkout_flow" not in names

    @pytest.mark.asyncio
    async def test_returns_at_most_top_k(self):
        history = [{"test_name": f"test_login_{i}", "passed": True} for i in range(20)]
        selector = self._make_selector(history)
        goal = _goal(feature_areas=["login"])
        candidates = await selector.select(goal, top_k=5)
        assert len(candidates) <= 5

    @pytest.mark.asyncio
    async def test_empty_feature_areas_includes_all(self):
        history = [
            {"test_name": "test_login", "passed": True},
            {"test_name": "test_checkout", "passed": True},
        ]
        selector = self._make_selector(history)
        goal = _goal(feature_areas=[])
        candidates = await selector.select(goal, top_k=10)
        assert len(candidates) == 2

    def test_feature_relevance_exact_match(self):
        score = TestSelector._feature_relevance("test_login_flow", ["login"])
        assert score == 1.0

    def test_feature_relevance_no_match(self):
        score = TestSelector._feature_relevance("test_checkout", ["login"])
        assert score == 0.0

    def test_feature_relevance_partial_match(self):
        score = TestSelector._feature_relevance("test_login_checkout", ["login", "checkout"])
        assert score == 1.0


# ── GoalParser ────────────────────────────────────────────────────────────────

class TestGoalParser:
    def _make_parser(self, scope: str = "regression", features: list[str] | None = None) -> GoalParser:
        from oapw.qa_agent.goal_parser import _GoalParseResponse

        resp = _GoalParseResponse(
            intent="Run login regression",
            scope=TestScope(scope),
            feature_areas=["login"] if features is None else features,
            environment="qa",
            jira_refs=[],
            confidence=0.9,
        )
        ollama = MagicMock()
        ollama.prompt_hash = MagicMock(return_value="hash_123")
        ollama.generate_structured = AsyncMock(return_value=resp)
        parser = GoalParser(ollama=ollama)
        parser._cache = _make_cache()
        return parser

    @pytest.mark.asyncio
    async def test_parse_returns_qa_goal(self):
        parser = self._make_parser()
        goal = await parser.parse("run login regression on QA")
        assert isinstance(goal, QaGoal)
        assert goal.raw == "run login regression on QA"

    @pytest.mark.asyncio
    async def test_parse_scope_regression(self):
        parser = self._make_parser(scope="regression")
        goal = await parser.parse("regression test login")
        assert goal.scope == TestScope.REGRESSION

    @pytest.mark.asyncio
    async def test_parse_feature_areas(self):
        parser = self._make_parser(features=["login", "sso"])
        goal = await parser.parse("test login and SSO")
        assert "login" in goal.feature_areas

    @pytest.mark.asyncio
    async def test_parse_caches_result(self):
        parser = self._make_parser()
        await parser.parse("same goal")
        await parser.parse("same goal")
        # Second call should use cache, not call ollama again
        assert parser._ollama.generate_structured.await_count == 1


# ── JudgmentEngine ────────────────────────────────────────────────────────────

class TestJudgmentEngine:
    def _make_engine(
        self,
        classification: str = "real_bug",
        confidence: float = 0.85,
    ) -> JudgmentEngine:
        from oapw.qa_agent.judgment import _JudgmentResponse

        resp = _JudgmentResponse(
            classification=JudgmentClassification(classification),
            confidence=confidence,
            hypothesis="Modal trigger broken",
            evidence=["No network call"],
            suggested_action=SuggestedAction.FILE_BUG,
        )
        ollama = MagicMock()
        ollama.prompt_hash = MagicMock(return_value="judge_hash")
        ollama.generate_structured = AsyncMock(return_value=resp)
        engine = JudgmentEngine(ollama=ollama, use_kb=False)
        engine._cache = _make_cache()
        return engine

    @pytest.mark.asyncio
    async def test_judge_returns_judgment(self):
        engine = self._make_engine()
        j = await engine.judge(
            test_name="test_forgot_password",
            expected_behavior="Modal should appear",
            observed_error="AssertionError: modal not visible",
        )
        assert isinstance(j, Judgment)
        assert j.classification == JudgmentClassification.REAL_BUG

    @pytest.mark.asyncio
    async def test_judge_caches_result(self):
        engine = self._make_engine()
        await engine.judge("t", "e", "err")
        await engine.judge("t", "e", "err")
        assert engine._ollama.generate_structured.await_count == 1

    @pytest.mark.asyncio
    async def test_judge_flaky_classification(self):
        engine = self._make_engine(classification="flaky", confidence=0.7)
        j = await engine.judge("t", "e", "err")
        assert j.classification == JudgmentClassification.FLAKY

    @pytest.mark.asyncio
    async def test_judge_confidence_preserved(self):
        engine = self._make_engine(confidence=0.92)
        j = await engine.judge("t", "e", "err")
        assert j.confidence == pytest.approx(0.92)


# ── Investigator ──────────────────────────────────────────────────────────────

class TestInvestigator:
    def _make_investigator(self, draft_title: str = "Bug: modal broken") -> Investigator:
        from pydantic import BaseModel

        class _Resp(BaseModel):
            title: str = draft_title
            description: str = "Steps: ...\nExpected: ...\nActual: ..."

        ollama = MagicMock()
        ollama.prompt_hash = MagicMock(return_value="inv_hash")
        ollama.generate_structured = AsyncMock(return_value=_Resp())
        inv = Investigator(ollama=ollama)
        inv._cache = _make_cache()
        return inv

    @pytest.mark.asyncio
    async def test_investigate_returns_investigation(self):
        inv = self._make_investigator()
        j = _judgment()
        result = await inv.investigate("test_forgot_password", "modal not visible", j)
        assert isinstance(result, Investigation)

    @pytest.mark.asyncio
    async def test_investigate_includes_draft_title(self):
        inv = self._make_investigator(draft_title="Fix: forgot password modal")
        result = await inv.investigate("test_forgot_password", "err", _judgment())
        assert result.jira_draft_title == "Fix: forgot password modal"

    @pytest.mark.asyncio
    async def test_investigate_caches_draft(self):
        inv = self._make_investigator()
        j = _judgment()
        await inv.investigate("test_x", "error", j)
        await inv.investigate("test_x", "error", j)
        assert inv._ollama.generate_structured.await_count == 1

    @pytest.mark.asyncio
    async def test_no_atlassian_returns_empty_related_jira(self):
        inv = self._make_investigator()
        result = await inv.investigate("test_x", "err", _judgment())
        assert result.related_jira == []


# ── ConsoleReporter ───────────────────────────────────────────────────────────

class TestConsoleReporter:
    def _make_result(self) -> QaRunResult:
        t1 = _pass_result("test_login_valid")
        t1 = t1.model_copy(update={"judgment": _judgment(JudgmentClassification.PASS, 1.0)})
        t2 = _fail_result("test_forgot_password")
        t2 = t2.model_copy(update={"judgment": _judgment(JudgmentClassification.REAL_BUG)})
        return QaRunResult(
            goal=_goal(),
            tests_run=[t1, t2],
            duration_ms=3200.0,
            environment="qa",
        )

    def test_report_runs_without_exception(self, capsys):
        reporter = ConsoleReporter()
        result = self._make_result()
        # Should not raise even when Rich is available
        reporter.report(result)

    def test_plain_report_contains_test_names(self, capsys):
        reporter = ConsoleReporter()
        result = self._make_result()
        # Force plain text path
        reporter._plain_report(result)
        captured = capsys.readouterr()
        assert "test_login_valid" in captured.out
        assert "test_forgot_password" in captured.out

    def test_plain_report_shows_pass_fail(self, capsys):
        reporter = ConsoleReporter()
        result = self._make_result()
        reporter._plain_report(result)
        captured = capsys.readouterr()
        assert "PASS" in captured.out
        assert "FAIL" in captured.out


# ── QaOrchestrator ────────────────────────────────────────────────────────────

class TestQaOrchestrator:
    def _make_orchestrator(
        self,
        test_results: list[TestRunResult] | None = None,
        judgment: Judgment | None = None,
    ) -> QaOrchestrator:
        cache = _make_cache()
        memory = QaMemory(cache=cache)

        # Mock goal parser
        goal_parser = MagicMock()
        goal_parser.parse = AsyncMock(return_value=_goal())

        # Mock test selector (no candidates from memory initially)
        test_selector = MagicMock()
        test_selector.select = AsyncMock(return_value=[])

        # Mock executor
        executor = MagicMock()
        executor.execute_all = AsyncMock(return_value=test_results or [])

        # Mock judgment engine
        j_engine = MagicMock()
        j_engine.judge = AsyncMock(return_value=judgment or _judgment())

        # Mock investigator
        investigator = MagicMock()
        investigator.investigate = AsyncMock(
            return_value=Investigation(test_name="t", jira_draft_title="Bug: x")
        )

        orch = QaOrchestrator(print_report=False, investigate_bugs=True)
        orch._goal_parser = goal_parser
        orch._test_selector = test_selector
        orch._executor = executor
        orch._judgment_engine = j_engine
        orch._investigator = investigator
        orch._memory = memory

        return orch

    @pytest.mark.asyncio
    async def test_run_returns_qa_run_result(self):
        orch = self._make_orchestrator()
        result = await orch.run("regression of login")
        assert isinstance(result, QaRunResult)

    @pytest.mark.asyncio
    async def test_run_passes_goal_to_result(self):
        orch = self._make_orchestrator()
        result = await orch.run("regression of login")
        assert result.goal.raw == "run login regression"  # from mock

    @pytest.mark.asyncio
    async def test_run_with_passed_tests(self):
        orch = self._make_orchestrator(test_results=[_pass_result("t1"), _pass_result("t2")])
        result = await orch.run("smoke test")
        assert result.passed == 2
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_run_with_failed_tests_judges_them(self):
        orch = self._make_orchestrator(
            test_results=[_fail_result("test_login")],
            judgment=_judgment(JudgmentClassification.REAL_BUG),
        )
        result = await orch.run("regression")
        failing = result.tests_run[0]
        assert failing.judgment is not None
        assert failing.judgment.classification == JudgmentClassification.REAL_BUG

    @pytest.mark.asyncio
    async def test_run_investigates_real_bugs(self):
        orch = self._make_orchestrator(
            test_results=[_fail_result("test_login")],
            judgment=_judgment(JudgmentClassification.REAL_BUG, confidence=0.8),
        )
        result = await orch.run("regression")
        failing = result.tests_run[0]
        assert failing.investigation is not None

    @pytest.mark.asyncio
    async def test_run_duration_positive(self):
        orch = self._make_orchestrator()
        result = await orch.run("goal")
        assert result.duration_ms >= 0.0

    @pytest.mark.asyncio
    async def test_run_records_results_in_memory(self):
        orch = self._make_orchestrator(test_results=[_pass_result("t1")])
        await orch.run("goal")
        history = orch._memory._load_history()
        assert any(r["test_name"] == "t1" for r in history)

    @pytest.mark.asyncio
    async def test_run_no_investigate_skips_investigator(self):
        orch = self._make_orchestrator(
            test_results=[_fail_result("test_x")],
            judgment=_judgment(JudgmentClassification.REAL_BUG),
        )
        orch._investigate_bugs = False
        result = await orch.run("goal")
        # investigator.investigate should NOT have been called
        orch._investigator.investigate.assert_not_awaited()
