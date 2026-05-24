"""Tests for Phase 9 — Multi-Faceted Verification.

All Playwright page objects and external calls are mocked.
Pillow is NOT required — tests pass with or without it.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from oapw.verification.accessibility import (
    AccessibilityChecker,
    AccessibilityReport,
    AccessibilityViolation,
)
from oapw.verification.performance import (
    PerformanceCapture,
    PerformanceMetrics,
    ResourceSummary,
)
from oapw.verification.visual import VisualChecker, VisualDiff, _compute_diff


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_page(url: str = "http://localhost:3000") -> MagicMock:
    page = MagicMock()
    page.url = url
    page.evaluate = AsyncMock()
    page.add_script_tag = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.screenshot = AsyncMock()
    return page


def _axe_violation(
    id: str = "color-contrast",
    impact: str = "serious",
    nodes: int = 2,
) -> dict:
    return {
        "id": id,
        "impact": impact,
        "description": f"Test: {id}",
        "helpUrl": f"https://dequeuniversity.com/rules/axe/4.9/{id}",
        "tags": ["wcag2aa"],
        "nodes": [{"target": [f".{id}-{i}"]} for i in range(nodes)],
    }


def _perf_raw(
    ttfb: float = 150.0,
    fcp: float = 800.0,
    dom_complete: float = 1200.0,
) -> dict:
    return {
        "ttfb_ms": ttfb,
        "dom_interactive_ms": dom_complete * 0.8,
        "dom_complete_ms": dom_complete,
        "load_event_ms": dom_complete + 50,
        "fcp_ms": fcp,
        "resources": {
            "js": {"count": 5, "bytes": 250_000},
            "css": {"count": 2, "bytes": 40_000},
            "img": {"count": 8, "bytes": 800_000},
            "other": {"count": 1, "bytes": 5_000},
        },
    }


# ── AccessibilityViolation ────────────────────────────────────────────────────

class TestAccessibilityViolation:
    def test_from_axe_parses_id(self):
        v = AccessibilityViolation.from_axe(_axe_violation("color-contrast", "serious", 3))
        assert v.id == "color-contrast"

    def test_from_axe_parses_impact(self):
        v = AccessibilityViolation.from_axe(_axe_violation(impact="critical"))
        assert v.impact == "critical"

    def test_from_axe_counts_nodes(self):
        v = AccessibilityViolation.from_axe(_axe_violation(nodes=5))
        assert v.nodes_affected == 5

    def test_from_axe_extracts_selectors(self):
        v = AccessibilityViolation.from_axe(_axe_violation("btn", nodes=2))
        assert len(v.target_selectors) == 2

    def test_from_axe_caps_selectors_at_5(self):
        v = AccessibilityViolation.from_axe(_axe_violation(nodes=10))
        assert len(v.target_selectors) <= 5


# ── AccessibilityReport ───────────────────────────────────────────────────────

class TestAccessibilityReport:
    def _make_report(self) -> AccessibilityReport:
        violations = [
            AccessibilityViolation.from_axe(_axe_violation("v1", "critical")),
            AccessibilityViolation.from_axe(_axe_violation("v2", "serious")),
            AccessibilityViolation.from_axe(_axe_violation("v3", "moderate")),
            AccessibilityViolation.from_axe(_axe_violation("v4", "minor")),
        ]
        return AccessibilityReport(url="http://x", violations=violations)

    def test_critical_count(self):
        r = self._make_report()
        assert r.critical_count == 1

    def test_total_count(self):
        r = self._make_report()
        assert r.total_count == 4

    def test_critical_filters(self):
        r = self._make_report()
        assert len(r.critical) == 1
        assert r.critical[0].id == "v1"

    def test_serious_filters(self):
        r = self._make_report()
        assert len(r.serious) == 1

    def test_assert_no_critical_raises_when_critical(self):
        r = self._make_report()
        with pytest.raises(AssertionError, match="critical"):
            r.assert_no_critical()

    def test_assert_no_critical_passes_when_none(self):
        r = AccessibilityReport(url="http://x", violations=[
            AccessibilityViolation.from_axe(_axe_violation("v", "minor"))
        ])
        r.assert_no_critical()  # should not raise

    def test_assert_no_serious_raises_when_serious(self):
        r = self._make_report()
        with pytest.raises(AssertionError):
            r.assert_no_serious()

    def test_summary_contains_url(self):
        r = self._make_report()
        assert "http://x" in r.summary()

    def test_summary_no_violations(self):
        r = AccessibilityReport(url="http://clean", violations=[])
        assert "no violations" in r.summary()


# ── AccessibilityChecker ──────────────────────────────────────────────────────

class TestAccessibilityChecker:
    @pytest.mark.asyncio
    async def test_check_injects_axe_when_not_loaded(self):
        page = _make_page()
        page.evaluate = AsyncMock(side_effect=[False, json.dumps([])])
        checker = AccessibilityChecker()
        report = await checker.check(page)
        page.add_script_tag.assert_awaited_once()
        assert isinstance(report, AccessibilityReport)

    @pytest.mark.asyncio
    async def test_check_skips_injection_when_loaded(self):
        page = _make_page()
        page.evaluate = AsyncMock(side_effect=[True, json.dumps([])])
        checker = AccessibilityChecker()
        await checker.check(page)
        page.add_script_tag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_returns_violations(self):
        violations_json = json.dumps([_axe_violation("color-contrast", "serious")])
        page = _make_page()
        page.evaluate = AsyncMock(side_effect=[True, violations_json])
        checker = AccessibilityChecker()
        report = await checker.check(page)
        assert report.total_count == 1
        assert report.violations[0].id == "color-contrast"

    @pytest.mark.asyncio
    async def test_check_sets_url(self):
        page = _make_page("http://myapp/login")
        page.evaluate = AsyncMock(side_effect=[True, json.dumps([])])
        checker = AccessibilityChecker()
        report = await checker.check(page)
        assert report.url == "http://myapp/login"

    @pytest.mark.asyncio
    async def test_check_empty_violations(self):
        page = _make_page()
        page.evaluate = AsyncMock(side_effect=[True, json.dumps([])])
        checker = AccessibilityChecker()
        report = await checker.check(page)
        assert report.total_count == 0
        report.assert_no_critical()  # should not raise


# ── ResourceSummary ───────────────────────────────────────────────────────────

class TestResourceSummary:
    def test_kb_property(self):
        rs = ResourceSummary(count=3, bytes=2048)
        assert rs.kb == pytest.approx(2.0)

    def test_zero_bytes(self):
        rs = ResourceSummary(count=0, bytes=0)
        assert rs.kb == 0.0


# ── PerformanceMetrics ────────────────────────────────────────────────────────

class TestPerformanceMetrics:
    def _make_metrics(self, ttfb: float = 150.0, fcp: float = 800.0, lcp: float = 0.0) -> PerformanceMetrics:
        return PerformanceMetrics(
            url="http://x",
            ttfb_ms=ttfb,
            fcp_ms=fcp,
            lcp_ms=lcp,
            js=ResourceSummary(count=3, bytes=250_000),
        )

    def test_assert_ttfb_under_passes(self):
        m = self._make_metrics(ttfb=150.0)
        m.assert_ttfb_under(200.0)  # should not raise

    def test_assert_ttfb_under_raises(self):
        m = self._make_metrics(ttfb=300.0)
        with pytest.raises(AssertionError, match="TTFB"):
            m.assert_ttfb_under(200.0)

    def test_assert_fcp_under_passes(self):
        m = self._make_metrics(fcp=800.0)
        m.assert_fcp_under(1000.0)

    def test_assert_fcp_under_raises(self):
        m = self._make_metrics(fcp=1500.0)
        with pytest.raises(AssertionError, match="FCP"):
            m.assert_fcp_under(1000.0)

    def test_assert_lcp_skips_when_zero(self):
        m = self._make_metrics(lcp=0.0)
        m.assert_lcp_under(100.0)  # zero lcp = not measured, should not raise

    def test_assert_lcp_raises_when_over(self):
        m = self._make_metrics(lcp=3000.0)
        with pytest.raises(AssertionError, match="LCP"):
            m.assert_lcp_under(2500.0)

    def test_summary_contains_url(self):
        m = self._make_metrics()
        assert "http://x" in m.summary()


# ── PerformanceCapture ────────────────────────────────────────────────────────

class TestPerformanceCapture:
    @pytest.mark.asyncio
    async def test_capture_returns_metrics(self):
        page = _make_page()
        page.evaluate = AsyncMock(return_value=_perf_raw())
        capture = PerformanceCapture()
        metrics = await capture.capture(page)
        assert isinstance(metrics, PerformanceMetrics)

    @pytest.mark.asyncio
    async def test_capture_sets_url(self):
        page = _make_page("http://app/checkout")
        page.evaluate = AsyncMock(return_value=_perf_raw())
        capture = PerformanceCapture()
        metrics = await capture.capture(page)
        assert metrics.url == "http://app/checkout"

    @pytest.mark.asyncio
    async def test_capture_ttfb(self):
        page = _make_page()
        page.evaluate = AsyncMock(return_value=_perf_raw(ttfb=120.0))
        capture = PerformanceCapture()
        metrics = await capture.capture(page)
        assert metrics.ttfb_ms == pytest.approx(120.0)

    @pytest.mark.asyncio
    async def test_capture_fcp(self):
        page = _make_page()
        page.evaluate = AsyncMock(return_value=_perf_raw(fcp=750.0))
        capture = PerformanceCapture()
        metrics = await capture.capture(page)
        assert metrics.fcp_ms == pytest.approx(750.0)

    @pytest.mark.asyncio
    async def test_capture_resource_counts(self):
        page = _make_page()
        page.evaluate = AsyncMock(return_value=_perf_raw())
        capture = PerformanceCapture()
        metrics = await capture.capture(page)
        assert metrics.js.count == 5
        assert metrics.css.count == 2

    @pytest.mark.asyncio
    async def test_capture_without_lcp_observe(self):
        """LCP is 0.0 when observe_lcp=False (default)."""
        page = _make_page()
        page.evaluate = AsyncMock(return_value=_perf_raw())
        capture = PerformanceCapture(observe_lcp=False)
        metrics = await capture.capture(page)
        assert metrics.lcp_ms == 0.0


# ── VisualDiff ────────────────────────────────────────────────────────────────

class TestVisualDiff:
    def _make_diff(self, ratio: float = 0.01, threshold: float = 0.02) -> VisualDiff:
        return VisualDiff(
            name="homepage",
            diff_ratio=ratio,
            passed=ratio <= threshold,
            threshold=threshold,
            baseline_path=Path("/tmp/baseline.png"),
            current_path=Path("/tmp/current.png"),
        )

    def test_passed_when_under_threshold(self):
        d = self._make_diff(ratio=0.01, threshold=0.02)
        assert d.passed is True

    def test_failed_when_over_threshold(self):
        d = self._make_diff(ratio=0.05, threshold=0.02)
        assert d.passed is False

    def test_assert_within_threshold_passes(self):
        d = self._make_diff(ratio=0.01, threshold=0.02)
        d.assert_within_threshold()  # should not raise

    def test_assert_within_threshold_raises(self):
        d = self._make_diff(ratio=0.05, threshold=0.02)
        with pytest.raises(AssertionError, match="regression"):
            d.assert_within_threshold()

    def test_llm_description_defaults_empty(self):
        d = self._make_diff()
        assert d.llm_description == ""


# ── VisualChecker ─────────────────────────────────────────────────────────────

class TestVisualChecker:
    def _make_checker(self, threshold: float = 0.02) -> tuple[VisualChecker, Path]:
        tmpdir = Path(tempfile.mkdtemp())
        checker = VisualChecker(baselines_dir=tmpdir, threshold=threshold, use_llm=False)
        return checker, tmpdir

    @pytest.mark.asyncio
    async def test_first_run_captures_baseline(self):
        checker, tmpdir = self._make_checker()
        page = _make_page()

        async def fake_screenshot(**kwargs):
            # Create a dummy PNG file at the path
            path = kwargs.get("path")
            if path:
                Path(path).write_bytes(b"PNG_STUB_DATA")

        page.screenshot = AsyncMock(side_effect=fake_screenshot)
        diff = await checker.compare(page, "homepage")
        assert diff.passed is True
        assert diff.diff_ratio == 0.0
        assert (tmpdir / "homepage.png").exists()

    @pytest.mark.asyncio
    async def test_compare_identical_screenshots_passes(self):
        checker, tmpdir = self._make_checker()
        page = _make_page()
        # Write same dummy data for baseline and current
        dummy = b"PNG_IDENTICAL"

        call_count = {"n": 0}
        async def fake_screenshot(**kwargs):
            path = kwargs.get("path")
            if path:
                Path(path).write_bytes(dummy)
            call_count["n"] += 1

        page.screenshot = AsyncMock(side_effect=fake_screenshot)

        # First call: creates baseline
        await checker.compare(page, "login")
        # Second call: compares
        diff = await checker.compare(page, "login")
        # Identical bytes → diff_ratio 0.0 → passed
        assert diff.passed is True

    @pytest.mark.asyncio
    async def test_capture_baseline_saves_file(self):
        checker, tmpdir = self._make_checker()
        page = _make_page()

        async def fake_screenshot(**kwargs):
            path = kwargs.get("path")
            if path:
                Path(path).write_bytes(b"PNG_STUB")

        page.screenshot = AsyncMock(side_effect=fake_screenshot)
        path = await checker.capture_baseline(page, "my_test")
        assert path.exists()

    def test_update_baseline_replaces_file(self):
        checker, tmpdir = self._make_checker()
        current = tmpdir / "current.png"
        current.write_bytes(b"NEW_BASELINE")
        checker.update_baseline("my_page", current)
        assert (tmpdir / "my_page.png").read_bytes() == b"NEW_BASELINE"


# ── _compute_diff ─────────────────────────────────────────────────────────────

class TestComputeDiff:
    def test_identical_files_zero_diff(self, tmp_path):
        img_data = b"IDENTICAL_BYTES"
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        a.write_bytes(img_data)
        b.write_bytes(img_data)
        ratio, path = _compute_diff(a, b, "test", tmp_path)
        assert ratio == 0.0
        assert path is None  # no Pillow, raw path

    def test_different_files_nonzero_diff(self, tmp_path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        a.write_bytes(b"A" * 100)
        b.write_bytes(b"B" * 200)
        ratio, _ = _compute_diff(a, b, "test", tmp_path)
        assert ratio > 0.0
