"""Tests for TraceabilityStore — SQLite persistence of test ↔ ticket ↔ page links."""

from __future__ import annotations

import pytest
from pathlib import Path

from oapw.enterprise.traceability import TraceabilityStore


@pytest.fixture
def store(tmp_path: Path) -> TraceabilityStore:
    return TraceabilityStore(db_path=tmp_path / "traceability.db")


class TestTraceabilityStore:
    def test_link_and_lookup(self, store: TraceabilityStore):
        store.link_test(
            test_path="tests/test_login.py",
            jira_ids=["PROJ-1", "PROJ-2"],
            confluence_ids=["12345"],
            conf_versions={"12345": 3},
        )
        tests = store.tests_for_ticket("PROJ-1")
        assert "tests/test_login.py" in tests

    def test_multiple_tests_for_same_ticket(self, store: TraceabilityStore):
        store.link_test("tests/a.py", jira_ids=["PROJ-10"], confluence_ids=[])
        store.link_test("tests/b.py", jira_ids=["PROJ-10"], confluence_ids=[])
        tests = store.tests_for_ticket("PROJ-10")
        assert set(tests) == {"tests/a.py", "tests/b.py"}

    def test_unknown_ticket_returns_empty(self, store: TraceabilityStore):
        assert store.tests_for_ticket("PROJ-999") == []

    def test_record_for_test(self, store: TraceabilityStore):
        store.link_test(
            "tests/checkout.py",
            jira_ids=["SHOP-5"],
            confluence_ids=["99"],
            conf_versions={"99": 7},
        )
        rec = store.record_for_test("tests/checkout.py")
        assert rec is not None
        assert rec.jira_ids == ["SHOP-5"]
        assert rec.conf_versions == {"99": 7}

    def test_record_missing_returns_none(self, store: TraceabilityStore):
        assert store.record_for_test("tests/nonexistent.py") is None

    def test_upsert_overwrites_jira_ids(self, store: TraceabilityStore):
        store.link_test("tests/t.py", jira_ids=["OLD-1"], confluence_ids=[])
        store.link_test("tests/t.py", jira_ids=["NEW-1", "NEW-2"], confluence_ids=[])
        rec = store.record_for_test("tests/t.py")
        assert rec is not None
        assert "OLD-1" not in rec.jira_ids
        assert set(rec.jira_ids) == {"NEW-1", "NEW-2"}
        # Old ticket → test index cleaned up
        assert store.tests_for_ticket("OLD-1") == []
        assert store.tests_for_ticket("NEW-1") == ["tests/t.py"]

    def test_coverage_summary(self, store: TraceabilityStore):
        store.link_test("tests/a.py", jira_ids=["A-1", "A-2"], confluence_ids=[])
        store.link_test("tests/b.py", jira_ids=["A-2", "A-3"], confluence_ids=[])
        summary = store.coverage_summary()
        assert summary["total_tests_traced"] == 2
        assert summary["jira_tickets_covered"] == 3
        assert set(summary["jira_keys"]) == {"A-1", "A-2", "A-3"}

    def test_clear(self, store: TraceabilityStore):
        store.link_test("tests/t.py", jira_ids=["X-1"], confluence_ids=[])
        store.clear()
        assert store.all_records() == []
        assert store.tests_for_ticket("X-1") == []

    def test_all_records_ordered_by_date_desc(self, store: TraceabilityStore):
        store.link_test("tests/first.py", jira_ids=[], confluence_ids=[], generated_at="2024-01-01T00:00:00+00:00")
        store.link_test("tests/second.py", jira_ids=[], confluence_ids=[], generated_at="2024-06-01T00:00:00+00:00")
        records = store.all_records()
        assert records[0].test_path == "tests/second.py"
