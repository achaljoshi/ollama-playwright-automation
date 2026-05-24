"""QaMemory — persists test run history and known issues between sessions.

Backed by SQLite (via the L2 cache bucket "qa_memory") so results survive
process restarts. Provides:

- ``record_result(result)``: store a test result after each run
- ``get_known_issue(test_name)``: retrieve a previously seen failure pattern
- ``update_known_issue(test_name, judgment)``: upsert a known issue entry
- ``get_flaky_tests()``: list tests that have been flagged as flaky
- ``recent_failures(n)``: last *n* failures across all tests

Usage::

    memory = QaMemory()
    await memory.record_result(test_run_result)
    issue = memory.get_known_issue("test_login_sso")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from oapw.cache.manager import CacheManager, get_cache
from oapw.core.config import get_config
from oapw.qa_agent.models import (
    JudgmentClassification,
    KnownIssue,
    TestRunResult,
)


class QaMemory:
    """Persistent QA run memory backed by the cache layer.

    Parameters
    ----------
    cache:
        :class:`~oapw.cache.manager.CacheManager` to use. The singleton
        instance is used if *None*.
    """

    _BUCKET = "qa_memory"
    _KNOWN_ISSUES_KEY = "known_issues"
    _RUN_HISTORY_KEY = "run_history"

    def __init__(self, cache: CacheManager | None = None) -> None:
        self._cache = cache or get_cache()

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_result(self, result: TestRunResult) -> None:
        """Persist *result* to run history and update known-issues table."""
        history = self._load_history()
        history.append(result.model_dump())
        # Keep last 500 results
        if len(history) > 500:
            history = history[-500:]
        self._save_history(history)

        # Update known issues on failures
        if not result.passed and result.judgment:
            self.update_known_issue(result.test_name, result.judgment.classification)

    # ── Known issues ──────────────────────────────────────────────────────────

    def get_known_issue(self, test_name: str) -> KnownIssue | None:
        """Return the :class:`KnownIssue` for *test_name*, or *None*."""
        issues = self._load_issues()
        data = issues.get(test_name)
        if data is None:
            return None
        return KnownIssue.model_validate(data)

    def update_known_issue(
        self,
        test_name: str,
        classification: JudgmentClassification,
        jira_ticket: str = "",
        note: str = "",
    ) -> KnownIssue:
        """Upsert a known issue entry for *test_name*."""
        issues = self._load_issues()
        now = datetime.now(timezone.utc).isoformat()
        existing = issues.get(test_name)

        if existing:
            issue = KnownIssue.model_validate(existing)
            issue.classification = classification
            issue.last_seen = now
            issue.occurrence_count += 1
            if jira_ticket:
                issue.jira_ticket = jira_ticket
            if note:
                issue.note = note
        else:
            issue = KnownIssue(
                test_name=test_name,
                classification=classification,
                first_seen=now,
                last_seen=now,
                jira_ticket=jira_ticket,
                note=note,
            )

        issues[test_name] = issue.model_dump()
        self._save_issues(issues)
        return issue

    def clear_known_issue(self, test_name: str) -> bool:
        """Remove *test_name* from the known-issues table. Returns True if removed."""
        issues = self._load_issues()
        if test_name in issues:
            del issues[test_name]
            self._save_issues(issues)
            return True
        return False

    def get_flaky_tests(self) -> list[KnownIssue]:
        """Return all tests currently classified as flaky."""
        issues = self._load_issues()
        return [
            KnownIssue.model_validate(v)
            for v in issues.values()
            if v.get("classification") == JudgmentClassification.FLAKY
        ]

    # ── History queries ───────────────────────────────────────────────────────

    def recent_failures(self, n: int = 10) -> list[TestRunResult]:
        """Return the last *n* test failures from history (most recent first)."""
        history = self._load_history()
        failures = [
            TestRunResult.model_validate(r) for r in history if not r.get("passed", True)
        ]
        return failures[-n:][::-1]

    def stats(self) -> dict:
        """Return summary statistics from run history."""
        history = self._load_history()
        total = len(history)
        passed = sum(1 for r in history if r.get("passed", True))
        return {
            "total_runs": total,
            "passed": passed,
            "failed": total - passed,
            "known_issues": len(self._load_issues()),
        }

    # ── Internal storage ──────────────────────────────────────────────────────

    def _load_history(self) -> list[dict]:
        raw = self._cache.get(self._BUCKET, self._RUN_HISTORY_KEY)
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return []

    def _save_history(self, history: list[dict]) -> None:
        self._cache.set(self._BUCKET, self._RUN_HISTORY_KEY, history, ttl=None)

    def _load_issues(self) -> dict[str, dict]:
        raw = self._cache.get(self._BUCKET, self._KNOWN_ISSUES_KEY)
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save_issues(self, issues: dict[str, dict]) -> None:
        self._cache.set(self._BUCKET, self._KNOWN_ISSUES_KEY, issues, ttl=None)
