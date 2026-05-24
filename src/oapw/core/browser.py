"""Async Playwright browser wrapper with context management and tracing support."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from oapw.core.config import get_config


class BrowserManager:
    """Owns the Playwright process and browser instance for the test session."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        cfg = get_config()
        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, cfg.browser_type)
        self._browser = await launcher.launch(
            headless=cfg.browser_headless,
            slow_mo=cfg.browser_slow_mo,
        )

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None

    @property
    def browser(self) -> Browser:
        if not self._browser:
            raise RuntimeError("BrowserManager not started — call await manager.start() first")
        return self._browser

    @asynccontextmanager
    async def new_context(
        self,
        trace: bool = False,
        trace_name: str = "trace",
    ) -> AsyncGenerator[BrowserContext, None]:
        cfg = get_config()
        context = await self.browser.new_context(
            viewport={"width": cfg.browser_viewport_width, "height": cfg.browser_viewport_height},
        )
        if trace:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        try:
            yield context
        finally:
            if trace:
                cfg.ensure_dirs()
                trace_path = cfg.traces_dir / f"{trace_name}.zip"
                await context.tracing.stop(path=str(trace_path))
            await context.close()

    @asynccontextmanager
    async def new_page(
        self,
        trace: bool = False,
        trace_name: str = "trace",
    ) -> AsyncGenerator[Page, None]:
        async with self.new_context(trace=trace, trace_name=trace_name) as context:
            page = await context.new_page()
            yield page


@asynccontextmanager
async def managed_browser() -> AsyncGenerator[BrowserManager, None]:
    """Convenience context manager — starts and stops the browser automatically."""
    manager = BrowserManager()
    await manager.start()
    try:
        yield manager
    finally:
        await manager.stop()


def page_signature(html: str) -> str:
    """Stable hash of the structural skeleton of a page (tags + ids/roles, no text)."""
    import re

    skeleton = re.sub(r">[^<]+<", "><", html)
    skeleton = re.sub(r'\s+', " ", skeleton)
    return hashlib.blake2b(skeleton.encode(), digest_size=16).hexdigest()


async def get_page_signature(page: Page) -> str:
    html = await page.content()
    return page_signature(html)
