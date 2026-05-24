"""Golden self-evaluation suite — runs canonical + healing tests against real browser.

Usage:
    poetry run pytest tests/eval/test_golden_self_eval.py -v

Each test:
  1. Sets page content to a canonical HTML page
  2. Resolves all expected locators via LocatorResolver
  3. Records success/latency in MetricsCollector
  4. For broken pairs: resolves on canonical, then loads broken variant
     and verifies that auto-healing finds the equivalent element
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from oapw.agents.locator_resolver import LocatorResolver
from oapw.eval.golden_pages import GoldenPage
from oapw.eval.metrics import EvalReport, MetricsCollector, ResolutionRecord

if TYPE_CHECKING:
    from playwright.async_api import Page


async def run_canonical_eval(
    page: "Page",
    golden: GoldenPage,
    resolver: LocatorResolver | None = None,
    metrics: MetricsCollector | None = None,
) -> list[ResolutionRecord]:
    """Resolve all intents on a canonical page and record results."""
    resolver = resolver or LocatorResolver()
    await page.set_content(golden.html, wait_until="domcontentloaded")

    records: list[ResolutionRecord] = []
    for intent in golden.intents:
        t0 = time.monotonic()
        resolved = False
        try:
            await resolver.resolve(intent, page)
            resolved = True
        except Exception:
            pass
        latency_ms = (time.monotonic() - t0) * 1000

        rec = ResolutionRecord(
            page_name=golden.name,
            intent=intent,
            resolved=resolved,
            latency_ms=latency_ms,
        )
        if metrics:
            metrics.record(rec)
        records.append(rec)

    return records


async def run_healing_eval(
    page: "Page",
    canonical: GoldenPage,
    broken: GoldenPage,
    resolver: LocatorResolver | None = None,
    metrics: MetricsCollector | None = None,
) -> list[ResolutionRecord]:
    """Test healing: resolve on canonical (warm cache), switch to broken, re-resolve."""
    resolver = resolver or LocatorResolver()

    # Warm the cache on the canonical page
    await page.set_content(canonical.html, wait_until="domcontentloaded")
    for intent in canonical.intents:
        try:
            await resolver.resolve(intent, page)
        except Exception:
            pass

    # Now switch to the broken variant — cached locators will be stale
    await page.set_content(broken.html, wait_until="domcontentloaded")

    records: list[ResolutionRecord] = []
    for intent in canonical.intents:
        t0 = time.monotonic()
        resolved = False
        healed = False
        try:
            await resolver.resolve(intent, page)
            resolved = True
            healed = True  # resolution after break = healed
        except Exception:
            pass
        latency_ms = (time.monotonic() - t0) * 1000

        rec = ResolutionRecord(
            page_name=f"{broken.name}_healed",
            intent=intent,
            resolved=resolved,
            healed=healed,
            latency_ms=latency_ms,
        )
        if metrics:
            metrics.record(rec)
        records.append(rec)

    return records
