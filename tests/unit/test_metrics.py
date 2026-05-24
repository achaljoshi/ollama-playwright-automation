"""Tests for MetricsCollector and EvalReport."""

import pytest
from oapw.eval.metrics import MetricsCollector, EvalReport, ResolutionRecord


class TestEvalReport:
    def _report(self, resolved, total, healed=0, cache_hits=0, latencies=None):
        return EvalReport(
            run_id="test",
            total=total,
            resolved=resolved,
            healed=healed,
            cache_hits=cache_hits,
            latencies_ms=latencies or [10.0] * total,
        )

    def test_resolution_rate(self):
        r = self._report(resolved=8, total=10)
        assert r.resolution_rate == 0.8

    def test_resolution_rate_zero_total(self):
        r = self._report(resolved=0, total=0)
        assert r.resolution_rate == 0.0

    def test_cache_hit_rate(self):
        r = self._report(resolved=10, total=10, cache_hits=9)
        assert r.cache_hit_rate == 0.9

    def test_p50_latency(self):
        r = self._report(resolved=3, total=3, latencies=[10.0, 20.0, 30.0])
        assert r.p50_ms == 20.0

    def test_p95_latency(self):
        latencies = list(range(1, 101))  # 1–100 ms
        r = self._report(resolved=100, total=100, latencies=latencies)
        assert r.p95_ms >= 95.0

    def test_passed_above_threshold(self):
        r = self._report(resolved=10, total=10)
        assert r.passed(min_resolution=0.95) is True

    def test_passed_below_threshold(self):
        r = self._report(resolved=9, total=10)
        assert r.passed(min_resolution=0.95) is False

    def test_summary_keys(self):
        r = self._report(resolved=5, total=5)
        s = r.summary()
        assert "resolution_rate" in s
        assert "healing_rate" in s
        assert "p50_ms" in s
        assert "p95_ms" in s


class TestMetricsCollector:
    def test_record_and_report(self, tmp_path):
        from oapw.core.config import OapwConfig
        cfg = OapwConfig(data_dir=tmp_path / "oapw")
        cfg.ensure_dirs()
        mc = MetricsCollector(db_path=tmp_path / "metrics.db")
        mc.record(ResolutionRecord(page_name="login", intent="email input", resolved=True, latency_ms=12.5))
        mc.record(ResolutionRecord(page_name="login", intent="password input", resolved=True, latency_ms=8.0))
        mc.record(ResolutionRecord(page_name="login", intent="submit button", resolved=False, latency_ms=50.0))
        report = mc.report()
        assert report.total == 3
        assert report.resolved == 2
        assert report.resolution_rate == pytest.approx(0.667, abs=0.01)

    def test_healed_count(self, tmp_path):
        mc = MetricsCollector(db_path=tmp_path / "metrics.db")
        mc.record(ResolutionRecord("p", "i", resolved=True, healed=True, latency_ms=100.0))
        mc.record(ResolutionRecord("p", "j", resolved=True, healed=False, latency_ms=10.0))
        report = mc.report()
        assert report.healed == 1
        assert report.healing_rate == 0.5
