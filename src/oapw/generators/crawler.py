"""SmokeTestCrawler — crawl a live URL and generate smoke tests for each page.

Discovers pages by following internal links up to ``max_pages``, extracts
the interactive element context for each page, and generates a smoke test
that verifies the page loads and key elements are visible/interactable.

Usage:
  oapw generate smoke http://localhost:3000 --out tests/generated/

Programmatic:
  crawler = SmokeTestCrawler()
  results = await crawler.crawl_and_generate(
      base_url="http://localhost:3000",
      max_pages=10,
      out_dir=Path("tests/generated"),
  )
  for r in results:
      print(r.test.test_name, "→", r.path)
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.ollama_client import get_ollama_client
from oapw.generators.models import GeneratedTest, GenerationResult

if TYPE_CHECKING:
    from oapw.core.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:python)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


def _url_to_test_name(url: str) -> str:
    """Turn http://localhost:3000/admin/users → test_smoke_admin_users."""
    path = urlparse(url).path.strip("/") or "home"
    safe = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    return f"test_smoke_{safe[:50]}"


def _same_origin(base: str, link: str) -> bool:
    b = urlparse(base)
    l = urlparse(link)
    return b.netloc == l.netloc


class SmokeTestCrawler:
    """Discover pages on a live site and generate smoke tests.

    Parameters
    ----------
    ollama:
        ``OllamaClient`` instance.
    model:
        Ollama model.
    """

    def __init__(
        self,
        ollama: "OllamaClient | None" = None,
        model: str | None = None,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()

    async def crawl_and_generate(
        self,
        base_url: str,
        max_pages: int = 10,
        out_dir: Path | None = None,
    ) -> list[GenerationResult]:
        """Crawl ``base_url``, generate a smoke test per page.

        Parameters
        ----------
        base_url:
            Starting URL.
        max_pages:
            Maximum number of unique pages to visit.
        out_dir:
            If provided, write generated test files here.
        """
        from oapw.core.browser import managed_browser
        from oapw.core.dom import get_dom_context

        visited: set[str] = set()
        to_visit: list[str] = [base_url]
        results: list[GenerationResult] = []

        async with managed_browser() as mgr:
            async with mgr.new_page() as page:
                while to_visit and len(visited) < max_pages:
                    url = to_visit.pop(0)
                    if url in visited:
                        continue
                    visited.add(url)
                    logger.info("SmokeTestCrawler: visiting %s", url)

                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    except Exception as exc:
                        logger.warning("Failed to load %s: %s", url, exc)
                        continue

                    # Extract DOM context for prompt
                    dom_ctx = await get_dom_context(page)

                    # Discover internal links
                    try:
                        hrefs = await page.eval_on_selector_all(
                            "a[href]", "els => els.map(e => e.href)"
                        )
                        for href in hrefs:
                            if _same_origin(base_url, href) and href not in visited:
                                to_visit.append(href)
                    except Exception:
                        pass

                    # Generate smoke test for this page
                    result = await self._generate_for_page(url, dom_ctx, out_dir)
                    results.append(result)

        return results

    async def _generate_for_page(
        self, url: str, dom_context: str, out_dir: Path | None
    ) -> GenerationResult:
        cache_key = hashlib.blake2b(
            f"gen_smoke:{url}:{self._model}".encode(), digest_size=16
        ).hexdigest()

        cached = self._cache.get_llm(cache_key)
        if cached:
            code = cached
        else:
            prompt_text = prompts.render(
                "generate_smoke.j2",
                url=url,
                dom_context=dom_context[:3000],
            )
            raw = await self._ollama.generate(prompt_text, model=self._model)
            code = _strip_fences(raw)
            self._cache.set_llm(cache_key, code)

        test_name = _url_to_test_name(url)
        generated = GeneratedTest(
            test_name=test_name,
            code=code,
            summary=f"Smoke test for {url}",
            source_type="smoke",
            model=self._model,
        )

        if out_dir and code:
            return self._write(generated, out_dir)
        return GenerationResult(test=generated)

    def _write(self, test: GeneratedTest, out_dir: Path) -> GenerationResult:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{test.test_name}.py"
            path.write_text(test.code, encoding="utf-8")
            test.out_path = path
            return GenerationResult(test=test, written=True, path=path)
        except Exception as exc:
            return GenerationResult(test=test, error=str(exc))
