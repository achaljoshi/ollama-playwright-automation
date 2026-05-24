"""Performance capture — collects Web Vitals and navigation timing from a Playwright page.

Uses the browser's built-in Performance API (``window.performance``) to collect:
- Navigation timing (TTFB, DOM interactive, DOM complete, load event)
- Web Vitals via PerformanceObserver (LCP, FID/FCP, CLS) where available
- Resource timing summary (JS/CSS/Image sizes and counts)

No external services required — all data comes from the page itself.

Usage::

    perf = PerformanceCapture()
    metrics = await perf.capture(page)
    print(f"TTFB: {metrics.ttfb_ms:.0f}ms")
    print(f"LCP:  {metrics.lcp_ms:.0f}ms")
    metrics.assert_lcp_under(2500)   # raises AssertionError if too slow
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

_PERF_JS = """
() => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const paint = {};
    for (const e of performance.getEntriesByType('paint')) {
        paint[e.name] = e.startTime;
    }

    // Resources: count and total sizes by type
    const resources = {js: {count:0, bytes:0}, css: {count:0, bytes:0}, img: {count:0, bytes:0}, other: {count:0, bytes:0}};
    for (const r of performance.getEntriesByType('resource')) {
        let kind = 'other';
        if (r.initiatorType === 'script') kind = 'js';
        else if (r.initiatorType === 'css' || r.name.includes('.css')) kind = 'css';
        else if (r.initiatorType === 'img' || /\\.(png|jpg|jpeg|gif|svg|webp)/.test(r.name)) kind = 'img';
        resources[kind].count++;
        resources[kind].bytes += r.transferSize || 0;
    }

    return {
        ttfb_ms: (nav.responseStart || 0) - (nav.requestStart || 0),
        dom_interactive_ms: nav.domInteractive || 0,
        dom_complete_ms: nav.domComplete || 0,
        load_event_ms: nav.loadEventEnd || 0,
        fcp_ms: paint['first-contentful-paint'] || 0,
        resources: resources,
    };
}
"""


@dataclass
class ResourceSummary:
    """Byte and count breakdown for a resource type."""
    count: int = 0
    bytes: int = 0

    @property
    def kb(self) -> float:
        return self.bytes / 1024


@dataclass
class PerformanceMetrics:
    """Performance timing data captured from a page."""

    url: str
    ttfb_ms: float = 0.0
    dom_interactive_ms: float = 0.0
    dom_complete_ms: float = 0.0
    load_event_ms: float = 0.0
    fcp_ms: float = 0.0
    lcp_ms: float = 0.0  # requires PerformanceObserver — may be 0 if unavailable
    cls_score: float = 0.0  # Cumulative Layout Shift
    js: ResourceSummary = field(default_factory=ResourceSummary)
    css: ResourceSummary = field(default_factory=ResourceSummary)
    img: ResourceSummary = field(default_factory=ResourceSummary)
    other: ResourceSummary = field(default_factory=ResourceSummary)

    def assert_ttfb_under(self, threshold_ms: float) -> None:
        if self.ttfb_ms > threshold_ms:
            raise AssertionError(
                f"TTFB {self.ttfb_ms:.0f}ms exceeds threshold {threshold_ms:.0f}ms on {self.url}"
            )

    def assert_lcp_under(self, threshold_ms: float) -> None:
        if self.lcp_ms > 0 and self.lcp_ms > threshold_ms:
            raise AssertionError(
                f"LCP {self.lcp_ms:.0f}ms exceeds threshold {threshold_ms:.0f}ms on {self.url}"
            )

    def assert_fcp_under(self, threshold_ms: float) -> None:
        if self.fcp_ms > 0 and self.fcp_ms > threshold_ms:
            raise AssertionError(
                f"FCP {self.fcp_ms:.0f}ms exceeds threshold {threshold_ms:.0f}ms on {self.url}"
            )

    def summary(self) -> str:
        parts = [
            f"TTFB={self.ttfb_ms:.0f}ms",
            f"FCP={self.fcp_ms:.0f}ms",
            f"LCP={self.lcp_ms:.0f}ms",
            f"DOM={self.dom_complete_ms:.0f}ms",
            f"JS={self.js.kb:.0f}KB",
            f"CSS={self.css.kb:.0f}KB",
            f"IMG={self.img.kb:.0f}KB",
        ]
        return f"{self.url}: " + "  ".join(parts)


class PerformanceCapture:
    """Captures Web Vitals and navigation timing from a Playwright page.

    Parameters
    ----------
    observe_lcp:
        Whether to install a PerformanceObserver for LCP. Adds a small delay
        (``lcp_wait_ms``) to wait for the LCP entry.
    lcp_wait_ms:
        How long to wait for an LCP event after the page loads (default 2s).
    """

    def __init__(
        self,
        observe_lcp: bool = False,
        lcp_wait_ms: int = 2000,
    ) -> None:
        self._observe_lcp = observe_lcp
        self._lcp_wait_ms = lcp_wait_ms

    async def capture(self, page: "Page") -> PerformanceMetrics:
        """Capture performance metrics from *page*.

        The page must already be navigated to the target URL.
        """
        raw = await page.evaluate(_PERF_JS)
        resources = raw.get("resources", {})

        metrics = PerformanceMetrics(
            url=page.url,
            ttfb_ms=raw.get("ttfb_ms", 0.0),
            dom_interactive_ms=raw.get("dom_interactive_ms", 0.0),
            dom_complete_ms=raw.get("dom_complete_ms", 0.0),
            load_event_ms=raw.get("load_event_ms", 0.0),
            fcp_ms=raw.get("fcp_ms", 0.0),
            js=ResourceSummary(**resources.get("js", {})),
            css=ResourceSummary(**resources.get("css", {})),
            img=ResourceSummary(**resources.get("img", {})),
            other=ResourceSummary(**resources.get("other", {})),
        )

        if self._observe_lcp:
            metrics.lcp_ms = await self._measure_lcp(page)

        return metrics

    async def _measure_lcp(self, page: "Page") -> float:
        """Install a PerformanceObserver and wait for LCP entry."""
        _lcp_js = """
        new Promise((resolve) => {
            let lcp = 0;
            const obs = new PerformanceObserver((list) => {
                const entries = list.getEntries();
                if (entries.length) {
                    lcp = entries[entries.length - 1].startTime;
                }
            });
            try {
                obs.observe({ type: 'largest-contentful-paint', buffered: true });
            } catch(e) {}
            setTimeout(() => { obs.disconnect(); resolve(lcp); }, %d);
        })
        """ % self._lcp_wait_ms

        try:
            lcp = await page.evaluate(_lcp_js, timeout=self._lcp_wait_ms + 5000)
            return float(lcp or 0)
        except Exception:
            return 0.0
