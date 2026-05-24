"""Multi-faceted verification — accessibility, performance, and visual regression.

Phase 9 modules
───────────────
AccessibilityChecker  — axe-core integration; returns AccessibilityReport
                        with violations grouped by impact level
PerformanceCapture    — Web Vitals + navigation timing from the browser
                        Performance API (no external dependencies)
VisualChecker         — pixel-diff screenshot comparison with optional LLM
                        description of visual changes (Pillow + Ollama vision)
"""

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
from oapw.verification.visual import VisualChecker, VisualDiff

__all__ = [
    # Accessibility
    "AccessibilityChecker",
    "AccessibilityReport",
    "AccessibilityViolation",
    # Performance
    "PerformanceCapture",
    "PerformanceMetrics",
    "ResourceSummary",
    # Visual regression
    "VisualChecker",
    "VisualDiff",
]
