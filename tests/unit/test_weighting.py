"""Tests for Confluence page weighting — recency, owner/component signals."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from oapw.enterprise.atlassian_client import ConfluencePage
from oapw.enterprise.weighting import weight_pages, _parse_iso, _RECENT_DAYS


def _make_page(
    page_id: str = "1",
    title: str = "Page",
    last_modified: str = "",
    author: str = "",
    labels: list[str] | None = None,
) -> ConfluencePage:
    return ConfluencePage(
        id=page_id,
        title=title,
        space_key="ENG",
        body="content",
        url=f"https://example.atlassian.net/wiki/pages/{page_id}",
        version=1,
        last_modified=last_modified,
        author=author,
        labels=labels or [],
    )


class TestWeightPages:
    def test_empty_returns_empty(self):
        assert weight_pages([]) == []

    def test_recent_page_scores_higher_than_old(self):
        now = datetime.now(tz=timezone.utc)
        recent = _make_page("1", last_modified=(now - timedelta(days=10)).isoformat())
        old = _make_page("2", last_modified=(now - timedelta(days=200)).isoformat())
        weighted = weight_pages([recent, old])
        assert weighted[0].page.id == "1"
        assert weighted[0].score > weighted[1].score

    def test_component_match_on_author(self):
        now = datetime.now(tz=timezone.utc)
        matched = _make_page("1", author="Alice from Auth Team", last_modified=now.isoformat())
        unmatched = _make_page("2", author="Bob", last_modified=now.isoformat())
        weighted = weight_pages([matched, unmatched], component="auth")
        # matched should have higher score due to author containing "auth"
        scores = {w.page.id: w.score for w in weighted}
        assert scores["1"] > scores["2"]

    def test_component_match_on_label(self):
        now = datetime.now(tz=timezone.utc)
        labelled = _make_page("1", labels=["auth-team", "qa"], last_modified=now.isoformat())
        plain = _make_page("2", labels=["general"], last_modified=now.isoformat())
        weighted = weight_pages([labelled, plain], component="auth")
        scores = {w.page.id: w.score for w in weighted}
        assert scores["1"] > scores["2"]

    def test_score_capped_at_one(self):
        now = datetime.now(tz=timezone.utc)
        page = _make_page("1", author="auth engineer", labels=["auth"], last_modified=now.isoformat())
        weighted = weight_pages([page], component="auth")
        assert weighted[0].score <= 1.0

    def test_base_score_without_signals(self):
        # Page with no modification date, no component — gets base score only
        page = _make_page("1")
        weighted = weight_pages([page])
        assert weighted[0].score == pytest.approx(0.25, abs=0.01)

    def test_reasons_populated(self):
        now = datetime.now(tz=timezone.utc)
        page = _make_page(
            "1",
            author="auth team lead",
            last_modified=(now - timedelta(days=5)).isoformat(),
        )
        weighted = weight_pages([page], component="auth")
        reasons = weighted[0].reasons
        assert any("modified" in r for r in reasons)
        assert any("auth" in r.lower() for r in reasons)


class TestParseIso:
    def test_z_suffix(self):
        dt = _parse_iso("2024-06-15T10:30:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_with_milliseconds(self):
        dt = _parse_iso("2024-06-15T10:30:00.123Z")
        assert dt is not None

    def test_with_offset(self):
        dt = _parse_iso("2024-06-15T10:30:00+05:30")
        assert dt is not None

    def test_invalid_returns_none(self):
        assert _parse_iso("not-a-date") is None
