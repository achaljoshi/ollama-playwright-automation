"""Example: QA Agent mode — autonomous regression with natural language goals.

Demonstrates:
  - oapw qa CLI equivalent via QaOrchestrator in tests
  - oapw_qa_agent fixture
  - Checking pass rates and real bugs

Run with::

    poetry run pytest examples/test_qa_agent_example.py -v \
        --OAPW_APP_BASE_URL=http://localhost:3000
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_smoke_regression_via_qa_agent(oapw_qa_agent):
    """Run a smoke regression of the app's main flows using the QA Agent."""
    result = await oapw_qa_agent.run("smoke test the home page and login flow")
    # Check that we have no critical regressions (real bugs)
    assert result.pass_rate >= 0.8, (
        f"QA Agent smoke pass rate too low: {result.pass_rate:.0%}\n"
        f"Failures: {[t.test_name for t in result.tests_run if not t.passed]}"
    )


async def test_no_real_bugs_in_auth(oapw_qa_agent):
    """Run authentication tests and verify no real bugs are detected."""
    result = await oapw_qa_agent.run(
        "regression of authentication — login, logout, and password reset"
    )
    real_bugs = result.real_bugs
    assert len(real_bugs) == 0, (
        f"Real bugs detected in auth flow:\n"
        + "\n".join(
            f"  - {b.test_name}: {b.judgment.hypothesis if b.judgment else 'unknown'}"
            for b in real_bugs
        )
    )
