"""SmartExecutor — runs test candidates and collects rich artifacts.

Wraps :class:`~oapw.agents.runner.AgentRunner` (for goal-based execution)
or calls ``pytest.main`` (for file-based test execution), captures outcomes,
screenshots, and hands each result to the :class:`JudgmentEngine`.

The SmartExecutor is the bridge between the high-level QA Agent loop and the
low-level Playwright / pytest execution primitives.

For *goal-based* execution (generated or KB-sourced natural-language goals)
it navigates to the app and uses the AgentRunner directly.

For *file-based* execution (pre-written pytest files) it delegates to
``pytest.main`` with JSON reporting and parses the outcome.

Usage::

    executor = SmartExecutor()
    results = await executor.execute_all(candidates, base_url="http://localhost:3000")
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from oapw.core.config import get_config
from oapw.qa_agent.models import TestCandidate, TestRunResult

if TYPE_CHECKING:
    pass


class SmartExecutor:
    """Executes a list of :class:`TestCandidate` and returns :class:`TestRunResult`.

    Parameters
    ----------
    base_url:
        Override the app base URL (falls back to ``OAPW_APP_BASE_URL``).
    """

    def __init__(self, base_url: str | None = None) -> None:
        cfg = get_config()
        self._base_url = base_url or cfg.app_base_url

    async def execute_all(
        self,
        candidates: list[TestCandidate],
        base_url: str | None = None,
    ) -> list[TestRunResult]:
        """Execute all *candidates* and return their results.

        File-based candidates (with ``file_path``) use pytest.
        Goal-based candidates (empty ``file_path``) use the AgentRunner.
        """
        url = base_url or self._base_url
        results: list[TestRunResult] = []
        for candidate in candidates:
            if candidate.file_path:
                result = await self._run_pytest(candidate)
            else:
                result = await self._run_goal_based(candidate, url)
            results.append(result)
        return results

    # ── Pytest execution ──────────────────────────────────────────────────────

    async def _run_pytest(self, candidate: TestCandidate) -> TestRunResult:
        """Run a single pytest file/test and parse the result."""
        start = time.monotonic()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            report_path = Path(tmp.name)

        try:
            proc = subprocess.run(
                [
                    "python", "-m", "pytest",
                    candidate.file_path,
                    "--json-report", f"--json-report-file={report_path}",
                    "-q",
                    "--tb=short",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            passed, error = _parse_pytest_report(report_path, candidate.test_name)
        except subprocess.TimeoutExpired:
            passed = False
            error = "Timeout: test exceeded 300s"
        except Exception as exc:
            passed = False
            error = str(exc)
        finally:
            try:
                report_path.unlink(missing_ok=True)
            except Exception:
                pass

        return TestRunResult(
            test_name=candidate.test_name,
            passed=passed,
            duration_ms=(time.monotonic() - start) * 1000,
            error=error if not passed else None,
        )

    # ── Goal-based execution ──────────────────────────────────────────────────

    async def _run_goal_based(self, candidate: TestCandidate, base_url: str) -> TestRunResult:
        """Use AgentRunner to execute a natural-language test candidate."""
        start = time.monotonic()
        try:
            from oapw.agents.runner import AgentRunner
            from oapw.core.browser import managed_browser

            runner = AgentRunner()
            async with managed_browser() as mgr:
                async with mgr.new_page() as page:
                    await page.goto(base_url)
                    run_result = await runner.run(candidate.test_name, page)

            passed = run_result.ok
            error = run_result.error if not passed else None
        except Exception as exc:
            passed = False
            error = str(exc)

        return TestRunResult(
            test_name=candidate.test_name,
            passed=passed,
            duration_ms=(time.monotonic() - start) * 1000,
            error=error if not passed else None,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_pytest_report(report_path: Path, test_name: str) -> tuple[bool, str]:
    """Parse a pytest-json-report file for a specific test result."""
    try:
        data = json.loads(report_path.read_text())
        tests = data.get("tests", [])
        for test in tests:
            # Match by nodeid containing test_name
            if test_name in test.get("nodeid", ""):
                outcome = test.get("outcome", "failed")
                if outcome == "passed":
                    return True, ""
                # Extract failure message
                call_data = test.get("call", {})
                longrepr = call_data.get("longrepr", "")
                return False, longrepr[:500] if longrepr else "Test failed"
        # If test not found in report, check summary
        summary = data.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        if failed == 0 and passed > 0:
            return True, ""
        return False, "Test not found in report"
    except Exception as exc:
        return False, f"Could not parse report: {exc}"
