"""Pydantic models shared across the QA Agent layer."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Goal parsing ──────────────────────────────────────────────────────────────

class TestScope(str, Enum):
    SMOKE = "smoke"
    REGRESSION = "regression"
    FULL = "full"
    CRITICAL = "critical"


class QaGoal(BaseModel):
    """Structured representation of a parsed user goal."""

    raw: str = Field(..., description="Original user-supplied text")
    intent: str = Field(..., description="Rephrased clear intent")
    scope: TestScope = Field(default=TestScope.SMOKE)
    feature_areas: list[str] = Field(default_factory=list, description="Feature areas to test")
    environment: str = Field(default="", description="Target env (qa, staging, prod, …)")
    jira_refs: list[str] = Field(default_factory=list, description="Any Jira keys mentioned")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ── Test selection ────────────────────────────────────────────────────────────

class TestCandidate(BaseModel):
    """A test file or test function selected for execution."""

    test_name: str
    file_path: str = ""
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    jira_ids: list[str] = Field(default_factory=list)
    confluence_ids: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["memory", "kb", "generated"] = "kb"
    tags: list[str] = Field(default_factory=list)


# ── Judgment ──────────────────────────────────────────────────────────────────

class JudgmentClassification(str, Enum):
    PASS = "pass"
    REAL_BUG = "real_bug"
    FLAKY = "flaky"
    ENV_ISSUE = "env_issue"
    DATA_ISSUE = "data_issue"
    UNCLEAR = "unclear"


class SuggestedAction(str, Enum):
    FILE_BUG = "file_bug"
    RETRY = "retry"
    INVESTIGATE = "investigate"
    IGNORE = "ignore"
    ESCALATE = "escalate"


class Judgment(BaseModel):
    """Per-test judgment from the JudgmentEngine.

    Per PLAN.md §7.4 — inputs include expected behavior, DOM diff,
    screenshots, network logs, Confluence pages, Jira history, deploy delta.
    """

    classification: JudgmentClassification
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    hypothesis: str = Field(default="")
    evidence: list[str] = Field(default_factory=list)
    suggested_action: SuggestedAction = SuggestedAction.INVESTIGATE
    confluence_refs: list[str] = Field(default_factory=list, description="Confluence pages consulted")
    jira_refs: list[str] = Field(default_factory=list, description="Jira tickets consulted")

    @property
    def needs_escalation(self) -> bool:
        return self.confidence < 0.6 or self.classification == JudgmentClassification.UNCLEAR


# ── Investigation ─────────────────────────────────────────────────────────────

class Investigation(BaseModel):
    """Result of the Investigator digging into a failure."""

    test_name: str
    related_jira: list[str] = Field(default_factory=list)
    recent_commits: list[str] = Field(default_factory=list)
    related_tests_failing: list[str] = Field(default_factory=list)
    api_reachable: bool | None = None
    notes: list[str] = Field(default_factory=list)
    jira_draft: str = ""
    jira_draft_title: str = ""


# ── QA Memory ────────────────────────────────────────────────────────────────

class KnownIssue(BaseModel):
    """A known / tracked issue from QA Memory."""

    test_name: str
    classification: JudgmentClassification
    first_seen: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_seen: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    occurrence_count: int = 1
    jira_ticket: str = ""
    note: str = ""


# ── Run results ───────────────────────────────────────────────────────────────

class TestRunResult(BaseModel):
    """Result for a single test execution by the SmartExecutor."""

    test_name: str
    passed: bool
    duration_ms: float = 0.0
    error: str | None = None
    screenshot_path: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    judgment: Judgment | None = None
    investigation: Investigation | None = None


class QaRunResult(BaseModel):
    """Top-level result for a full QaOrchestrator run."""

    goal: QaGoal
    tests_run: list[TestRunResult] = Field(default_factory=list)
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str = ""
    duration_ms: float = 0.0
    environment: str = ""

    @property
    def total(self) -> int:
        return len(self.tests_run)

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests_run if t.passed)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests_run if not t.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    @property
    def real_bugs(self) -> list[TestRunResult]:
        return [
            t for t in self.tests_run
            if t.judgment and t.judgment.classification == JudgmentClassification.REAL_BUG
        ]
