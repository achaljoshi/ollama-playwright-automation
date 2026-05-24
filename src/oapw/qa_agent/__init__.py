"""QA Agent Mode — autonomous QA agent driven by natural-language goals.

High-level entry point: ``QaOrchestrator.run(goal_text)``

Components
──────────
GoalParser       — NL goal → QaGoal
TestSelector     — QaGoal → ranked TestCandidate list
SmartExecutor    — TestCandidate → TestRunResult (pytest or AgentRunner)
JudgmentEngine   — failure → Judgment (classification, confidence, evidence)
Investigator     — Judgment → Investigation (Jira draft, git, related tests)
QaMemory         — persistent run history and known-issue tracking
ConsoleReporter  — formats QaRunResult to stdout
QaOrchestrator   — ties everything together
"""

from oapw.qa_agent.models import (
    QaGoal,
    TestScope,
    TestCandidate,
    JudgmentClassification,
    SuggestedAction,
    Judgment,
    Investigation,
    KnownIssue,
    TestRunResult,
    QaRunResult,
)
from oapw.qa_agent.goal_parser import GoalParser
from oapw.qa_agent.memory import QaMemory
from oapw.qa_agent.test_selector import TestSelector
from oapw.qa_agent.judgment import JudgmentEngine
from oapw.qa_agent.investigator import Investigator
from oapw.qa_agent.smart_executor import SmartExecutor
from oapw.qa_agent.reporter.console import ConsoleReporter
from oapw.qa_agent.orchestrator import QaOrchestrator

__all__ = [
    # models
    "QaGoal", "TestScope", "TestCandidate",
    "JudgmentClassification", "SuggestedAction", "Judgment",
    "Investigation", "KnownIssue", "TestRunResult", "QaRunResult",
    # components
    "GoalParser", "QaMemory", "TestSelector", "JudgmentEngine",
    "Investigator", "SmartExecutor", "ConsoleReporter",
    # top-level
    "QaOrchestrator",
]
