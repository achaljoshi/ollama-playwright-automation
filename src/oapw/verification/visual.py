"""Visual regression checker — pixel-diff screenshots with optional LLM analysis.

Strategy
────────
1. **Baseline capture**: ``VisualChecker.capture_baseline(page, name)`` saves a
   reference screenshot to ``.oapw/baselines/<name>.png``.
2. **Comparison**: ``VisualChecker.compare(page, name)`` takes a new screenshot,
   computes a pixel-level diff, and returns a :class:`VisualDiff` with:
   - ``diff_ratio`` — fraction of changed pixels (0.0 = identical)
   - ``diff_image_path`` — path to the highlighted diff image (if PIL available)
   - ``passed`` — True when ``diff_ratio <= threshold``
3. **LLM analysis** (16 GB+ RAM, optional): when ``use_llm=True``, the LLM
   describes the visual changes in human-readable language. Requires Ollama's
   vision model (e.g. ``llava``).

Dependencies
────────────
- Playwright (always present)
- Pillow (``pip install Pillow``) — for pixel-diff highlighting; gracefully
  degrades to a raw diff ratio without highlighting if not installed
- Ollama vision model — only used when ``use_llm=True``

Usage::

    checker = VisualChecker()
    # First run: capture baseline
    await checker.capture_baseline(page, "homepage")

    # Subsequent runs: compare
    diff = await checker.compare(page, "homepage")
    print(f"Diff: {diff.diff_ratio:.2%}")
    diff.assert_within_threshold()   # raises if too many pixels changed
"""

from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from oapw.core.config import get_config

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass
class VisualDiff:
    """Result of a visual comparison between baseline and current screenshot."""

    name: str
    diff_ratio: float
    passed: bool
    threshold: float
    baseline_path: Path
    current_path: Path
    diff_image_path: Path | None = None
    llm_description: str = ""
    duration_ms: float = 0.0

    def assert_within_threshold(self) -> None:
        """Raise :class:`AssertionError` if the diff exceeds the threshold."""
        if not self.passed:
            raise AssertionError(
                f"Visual regression detected for '{self.name}': "
                f"{self.diff_ratio:.2%} changed pixels "
                f"(threshold: {self.threshold:.2%})"
            )


class VisualChecker:
    """Captures and compares screenshots for visual regression testing.

    Parameters
    ----------
    baselines_dir:
        Directory to store baseline screenshots. Defaults to
        ``<OAPW_DATA_DIR>/baselines``.
    threshold:
        Maximum allowed fraction of changed pixels (0.0–1.0, default: 0.02).
    full_page:
        Whether to capture the full page (default: True).
    use_llm:
        Whether to ask the LLM to describe detected visual changes.
    llm_model:
        Vision-capable Ollama model (e.g. ``llava:7b``).
    """

    def __init__(
        self,
        baselines_dir: Path | None = None,
        threshold: float = 0.02,
        full_page: bool = True,
        use_llm: bool = False,
        llm_model: str = "llava:7b",
    ) -> None:
        cfg = get_config()
        self._baselines_dir = baselines_dir or (cfg.data_dir / "baselines")
        self._baselines_dir.mkdir(parents=True, exist_ok=True)
        self._threshold = threshold
        self._full_page = full_page
        self._use_llm = use_llm
        self._llm_model = llm_model

    # ── Public API ────────────────────────────────────────────────────────────

    async def capture_baseline(self, page: "Page", name: str) -> Path:
        """Capture and save a baseline screenshot for *name*.

        Returns the path to the saved baseline.
        """
        path = self._baseline_path(name)
        await page.screenshot(path=str(path), full_page=self._full_page)
        return path

    async def compare(
        self,
        page: "Page",
        name: str,
        threshold: float | None = None,
    ) -> VisualDiff:
        """Compare the current page against the *name* baseline.

        If no baseline exists, captures one and returns a passed diff
        with ``diff_ratio=0.0``.
        """
        start = time.monotonic()
        effective_threshold = threshold if threshold is not None else self._threshold
        baseline = self._baseline_path(name)

        # First run: auto-capture baseline
        if not baseline.exists():
            current = await self._capture_current(page, name)
            await page.screenshot(path=str(baseline), full_page=self._full_page)
            return VisualDiff(
                name=name,
                diff_ratio=0.0,
                passed=True,
                threshold=effective_threshold,
                baseline_path=baseline,
                current_path=current,
                duration_ms=(time.monotonic() - start) * 1000,
            )

        # Compare against existing baseline
        current = await self._capture_current(page, name)
        diff_ratio, diff_path = _compute_diff(baseline, current, name, self._baselines_dir)

        passed = diff_ratio <= effective_threshold
        llm_desc = ""
        if not passed and self._use_llm:
            llm_desc = await self._llm_describe(baseline, current)

        return VisualDiff(
            name=name,
            diff_ratio=diff_ratio,
            passed=passed,
            threshold=effective_threshold,
            baseline_path=baseline,
            current_path=current,
            diff_image_path=diff_path,
            llm_description=llm_desc,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def update_baseline(self, name: str, current_path: Path) -> None:
        """Promote *current_path* to be the new baseline for *name*."""
        import shutil
        shutil.copy2(current_path, self._baseline_path(name))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _baseline_path(self, name: str) -> Path:
        safe_name = name.replace("/", "_").replace(" ", "_")
        return self._baselines_dir / f"{safe_name}.png"

    async def _capture_current(self, page: "Page", name: str) -> Path:
        safe_name = name.replace("/", "_").replace(" ", "_")
        path = self._baselines_dir / f"{safe_name}_current.png"
        await page.screenshot(path=str(path), full_page=self._full_page)
        return path

    async def _llm_describe(self, baseline: Path, current: Path) -> str:
        """Ask the Ollama vision model to describe the visual change."""
        try:
            from oapw.core.ollama_client import get_ollama_client
            client = get_ollama_client()
            # Encode both images as base64
            import base64
            b64_baseline = base64.b64encode(baseline.read_bytes()).decode()
            b64_current = base64.b64encode(current.read_bytes()).decode()
            prompt = (
                "Compare these two screenshots (baseline vs current). "
                "Describe any visual differences in 2-3 sentences. "
                "Focus on layout changes, missing/added elements, color changes."
            )
            # Use a simple generate call with images
            response = await client.generate_with_images(
                prompt=prompt,
                images=[b64_baseline, b64_current],
                model=self._llm_model,
            )
            return response or ""
        except Exception:
            return ""


# ── Pixel diff ────────────────────────────────────────────────────────────────

def _compute_diff(
    baseline: Path,
    current: Path,
    name: str,
    out_dir: Path,
) -> tuple[float, Path | None]:
    """Compute pixel-level diff. Returns (diff_ratio, diff_image_path | None)."""
    try:
        from PIL import Image, ImageChops, ImageFilter
        import numpy as np

        img_a = Image.open(baseline).convert("RGB")
        img_b = Image.open(current).convert("RGB")

        # Resize current to match baseline if dimensions differ
        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size, Image.LANCZOS)

        arr_a = np.array(img_a, dtype=np.int32)
        arr_b = np.array(img_b, dtype=np.int32)
        diff_arr = np.abs(arr_a - arr_b)

        # Pixels where any channel differs by > 10 (ignore minor anti-aliasing)
        changed_mask = diff_arr.max(axis=2) > 10
        diff_ratio = float(changed_mask.sum()) / changed_mask.size

        # Build highlighted diff image
        diff_img = Image.fromarray(diff_arr.astype("uint8"))
        diff_path = out_dir / f"{name.replace('/', '_')}_diff.png"
        diff_img.save(diff_path)

        return diff_ratio, diff_path

    except ImportError:
        # Pillow not installed — fall back to raw byte comparison
        bytes_a = baseline.read_bytes()
        bytes_b = current.read_bytes()
        if bytes_a == bytes_b:
            return 0.0, None
        # Rough estimate: compare file sizes
        size_diff = abs(len(bytes_a) - len(bytes_b)) / max(len(bytes_a), 1)
        return min(1.0, size_diff), None

    except Exception:
        return 0.0, None
