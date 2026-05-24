"""Accessibility checker — runs axe-core via Playwright and reports violations.

Injects the axe-core JS library into the current page and runs an audit.
Returns a list of :class:`AccessibilityViolation` objects grouped by impact
level (critical, serious, moderate, minor).

No external network calls — axe-core is injected from a bundled CDN-compatible
URL or optionally from a local path.

Usage::

    checker = AccessibilityChecker()
    report = await checker.check(page)
    print(f"Critical violations: {report.critical_count}")
    for v in report.critical:
        print(f"  [{v.id}] {v.description} — {v.help_url}")
    report.assert_no_critical()   # raises AssertionError if critical > 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from playwright.async_api import Page

# CDN URL for axe-core (pinned version for reproducibility)
_AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"

# JS that runs axe and returns violations as JSON
_RUN_AXE_JS = """
async () => {
    const result = await axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'best-practice'] }
    });
    return JSON.stringify(result.violations);
}
"""

ImpactLevel = Literal["critical", "serious", "moderate", "minor"]


@dataclass
class AccessibilityViolation:
    """A single axe-core violation."""

    id: str
    impact: ImpactLevel
    description: str
    help_url: str
    nodes_affected: int
    tags: list[str] = field(default_factory=list)
    target_selectors: list[str] = field(default_factory=list)

    @classmethod
    def from_axe(cls, data: dict[str, Any]) -> "AccessibilityViolation":
        nodes = data.get("nodes", [])
        selectors = []
        for node in nodes[:5]:  # cap at first 5 nodes
            for t in node.get("target", []):
                if isinstance(t, str):
                    selectors.append(t)
        return cls(
            id=data.get("id", ""),
            impact=data.get("impact", "minor"),
            description=data.get("description", ""),
            help_url=data.get("helpUrl", ""),
            nodes_affected=len(nodes),
            tags=data.get("tags", []),
            target_selectors=selectors,
        )


@dataclass
class AccessibilityReport:
    """Aggregated accessibility audit results for a page."""

    url: str
    violations: list[AccessibilityViolation]

    @property
    def critical(self) -> list[AccessibilityViolation]:
        return [v for v in self.violations if v.impact == "critical"]

    @property
    def serious(self) -> list[AccessibilityViolation]:
        return [v for v in self.violations if v.impact == "serious"]

    @property
    def moderate(self) -> list[AccessibilityViolation]:
        return [v for v in self.violations if v.impact == "moderate"]

    @property
    def minor(self) -> list[AccessibilityViolation]:
        return [v for v in self.violations if v.impact == "minor"]

    @property
    def critical_count(self) -> int:
        return len(self.critical)

    @property
    def total_count(self) -> int:
        return len(self.violations)

    def assert_no_critical(self) -> None:
        """Raise :class:`AssertionError` if there are critical violations."""
        if self.critical:
            ids = ", ".join(v.id for v in self.critical)
            raise AssertionError(
                f"{self.critical_count} critical accessibility violation(s) on {self.url}: {ids}"
            )

    def assert_no_serious(self) -> None:
        """Raise :class:`AssertionError` if there are serious+ violations."""
        bad = self.critical + self.serious
        if bad:
            ids = ", ".join(v.id for v in bad)
            raise AssertionError(
                f"{len(bad)} critical/serious accessibility violation(s) on {self.url}: {ids}"
            )

    def summary(self) -> str:
        parts = []
        for level, items in [
            ("critical", self.critical),
            ("serious", self.serious),
            ("moderate", self.moderate),
            ("minor", self.minor),
        ]:
            if items:
                parts.append(f"{len(items)} {level}")
        return f"{self.url}: " + (", ".join(parts) if parts else "no violations")


class AccessibilityChecker:
    """Runs axe-core on a Playwright page and returns an :class:`AccessibilityReport`.

    Parameters
    ----------
    axe_url:
        CDN or local path for the axe-core JS bundle.
    timeout_ms:
        Maximum time to wait for axe-core to run (default: 30s).
    """

    def __init__(
        self,
        axe_url: str = _AXE_CDN,
        timeout_ms: int = 30_000,
    ) -> None:
        self._axe_url = axe_url
        self._timeout_ms = timeout_ms

    async def check(self, page: "Page") -> AccessibilityReport:
        """Run an accessibility audit on *page* and return the results.

        The axe-core script is injected via ``page.add_script_tag``. If the
        page already has axe loaded (e.g. from a previous check on the same
        page instance), the injection is skipped.
        """
        import json

        url = page.url

        # Inject axe-core if not already present
        already_loaded = await page.evaluate("typeof axe !== 'undefined'")
        if not already_loaded:
            await page.add_script_tag(url=self._axe_url)
            await page.wait_for_function("typeof axe !== 'undefined'", timeout=self._timeout_ms)

        # Run audit
        raw_json: str = await page.evaluate(_RUN_AXE_JS, timeout=self._timeout_ms)
        violations_data: list[dict] = json.loads(raw_json)

        violations = [AccessibilityViolation.from_axe(v) for v in violations_data]
        return AccessibilityReport(url=url, violations=violations)
