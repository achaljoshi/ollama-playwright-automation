"""Unit tests for the Phase 9/10 pytest plugin fixtures.

We test two things:
  1. The underlying classes (AccessibilityChecker, PerformanceCapture,
     VisualChecker, QaOrchestrator) can be instantiated with the same
     arguments the plugin fixtures use, and expose the expected interface.
  2. The plugin module exports the fixture names (registration smoke-check).

We do NOT call the fixture functions directly — pytest forbids that.
"""

from __future__ import annotations

import inspect
import pathlib
import tempfile


# ── AccessibilityChecker ──────────────────────────────────────────────────────

class TestAccessibilityChecker:
    def _make(self):
        from oapw.verification.accessibility import AccessibilityChecker
        return AccessibilityChecker()

    def test_instantiates(self):
        from oapw.verification.accessibility import AccessibilityChecker
        assert isinstance(self._make(), AccessibilityChecker)

    def test_default_timeout_positive(self):
        checker = self._make()
        assert checker._timeout_ms > 0

    def test_axe_url_is_http(self):
        checker = self._make()
        assert isinstance(checker._axe_url, str)
        assert checker._axe_url.startswith("http")

    def test_two_instances_are_independent(self):
        assert self._make() is not self._make()

    def test_check_is_coroutinefunction(self):
        assert inspect.iscoroutinefunction(self._make().check)


# ── PerformanceCapture ────────────────────────────────────────────────────────

class TestPerformanceCapture:
    def _make(self):
        from oapw.verification.performance import PerformanceCapture
        return PerformanceCapture()

    def test_instantiates(self):
        from oapw.verification.performance import PerformanceCapture
        assert isinstance(self._make(), PerformanceCapture)

    def test_observe_lcp_is_bool(self):
        assert isinstance(self._make()._observe_lcp, bool)

    def test_lcp_wait_ms_positive(self):
        assert self._make()._lcp_wait_ms > 0

    def test_two_instances_are_independent(self):
        assert self._make() is not self._make()

    def test_capture_is_coroutinefunction(self):
        assert inspect.iscoroutinefunction(self._make().capture)


# ── VisualChecker ─────────────────────────────────────────────────────────────

class TestVisualChecker:
    def _tmp(self):
        return pathlib.Path(tempfile.mkdtemp())

    def _make(self, tmp=None):
        from oapw.verification.visual import VisualChecker
        base = (tmp or self._tmp()) / "baselines"
        return VisualChecker(baselines_dir=base)

    def test_instantiates(self):
        from oapw.verification.visual import VisualChecker
        assert isinstance(self._make(), VisualChecker)

    def test_baselines_dir_stored(self):
        tmp = self._tmp()
        from oapw.verification.visual import VisualChecker
        checker = VisualChecker(baselines_dir=tmp / "baselines")
        assert checker._baselines_dir == tmp / "baselines"

    def test_threshold_in_range(self):
        assert 0.0 <= self._make()._threshold <= 1.0

    def test_full_page_is_bool(self):
        assert isinstance(self._make()._full_page, bool)

    def test_two_checkers_have_independent_dirs(self):
        from oapw.verification.visual import VisualChecker
        a = VisualChecker(baselines_dir=self._tmp() / "baselines")
        b = VisualChecker(baselines_dir=self._tmp() / "baselines")
        assert a._baselines_dir != b._baselines_dir

    def test_compare_is_coroutinefunction(self):
        assert inspect.iscoroutinefunction(self._make().compare)

    def test_capture_baseline_is_coroutinefunction(self):
        assert inspect.iscoroutinefunction(self._make().capture_baseline)


# ── QaOrchestrator ────────────────────────────────────────────────────────────

class TestQaOrchestrator:
    def _make(self):
        from oapw.qa_agent.orchestrator import QaOrchestrator
        return QaOrchestrator(print_report=False)

    def test_instantiates(self):
        from oapw.qa_agent.orchestrator import QaOrchestrator
        assert isinstance(self._make(), QaOrchestrator)

    def test_print_report_false(self):
        """Fixture sets print_report=False so tests don't spam stdout."""
        assert self._make()._print_report is False

    def test_run_is_coroutinefunction(self):
        assert inspect.iscoroutinefunction(self._make().run)

    def test_top_k_positive(self):
        assert self._make()._top_k >= 1

    def test_investigate_bugs_is_bool(self):
        assert isinstance(self._make()._investigate_bugs, bool)

    def test_two_instances_are_independent(self):
        assert self._make() is not self._make()


# ── Plugin registration smoke-check ──────────────────────────────────────────

class TestPluginRegistration:
    """Verify the plugin module defines all expected fixture names."""

    def test_plugin_module_importable(self):
        import oapw.plugin as plugin
        assert plugin is not None

    def test_oapw_accessibility_defined(self):
        import oapw.plugin as plugin
        assert hasattr(plugin, "oapw_accessibility")

    def test_oapw_performance_defined(self):
        import oapw.plugin as plugin
        assert hasattr(plugin, "oapw_performance")

    def test_oapw_visual_defined(self):
        import oapw.plugin as plugin
        assert hasattr(plugin, "oapw_visual")

    def test_oapw_qa_agent_defined(self):
        import oapw.plugin as plugin
        assert hasattr(plugin, "oapw_qa_agent")

    def test_legacy_fixtures_still_present(self):
        import oapw.plugin as plugin
        for name in ("oapw_config", "oapw_page", "oapw_api_context",
                     "oapw_hybrid", "oapw_factory", "oapw_pii_masker"):
            assert hasattr(plugin, name), f"Missing fixture: {name}"

    def test_new_fixtures_are_pytest_fixtures(self):
        """Each new fixture must be decorated with @pytest.fixture."""
        import oapw.plugin as plugin

        for name in ("oapw_accessibility", "oapw_performance",
                     "oapw_visual", "oapw_qa_agent"):
            fn = getattr(plugin, name)
            # pytest wraps fixtures; the wrapper exposes _fixture_function_marker
            assert hasattr(fn, "_fixture_function_marker") or hasattr(fn, "_pytestfixturefunction"), (
                f"{name} is not a pytest fixture (missing fixture marker)"
            )

    def test_fixture_callables_exist(self):
        """All new fixture functions must be callable."""
        import oapw.plugin as plugin
        for name in ("oapw_accessibility", "oapw_performance",
                     "oapw_visual", "oapw_qa_agent"):
            fn = getattr(plugin, name)
            assert callable(fn), f"{name} is not callable"
