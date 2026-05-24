"""LocatorResolver — cache-first, deterministic-first locator resolution pipeline.

Resolution priority (per PLAN §5.1):
  1. L1/L2 cache hit → validate is_visible() → return
  2. Deterministic Playwright strategies (role, label, placeholder, text, testid)
  3. LLM proposal → validate → cache winner

Each strategy is tried in order and the first visible match wins.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from oapw.agents.models import LocatorCandidate, LocatorProposal, LocatorStrategy
from oapw.cache.manager import get_cache
from oapw.core.aom import get_aom_context
from oapw.core.browser import get_page_signature
from oapw.core.config import get_config
from oapw.core.dom import get_dom_context
from oapw.core.ollama_client import OllamaClient, get_ollama_client
import oapw.prompts as prompts

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

# Simple heuristic maps for deterministic strategy
_ROLE_KEYWORDS = {
    "button": "button", "btn": "button", "submit": "button", "link": "link",
    "checkbox": "checkbox", "check": "checkbox", "radio": "radio",
    "textbox": "textbox", "input": "textbox", "field": "textbox",
    "select": "combobox", "dropdown": "combobox", "combobox": "combobox",
    "heading": "heading", "search": "searchbox", "slider": "slider",
    "tab": "tab", "menuitem": "menuitem",
}


def _extract_quoted_text(intent: str) -> str | None:
    m = re.search(r"['\"](.+?)['\"]", intent)
    return m.group(1) if m else None


def _guess_role(intent: str) -> str | None:
    lower = intent.lower()
    for kw, role in _ROLE_KEYWORDS.items():
        if kw in lower:
            return role
    return None


def _extract_meaningful_text(intent: str) -> str:
    """Strip action words to get the element label."""
    stop = re.compile(
        r"^(click|press|tap|fill|type|enter|select|choose|check|uncheck|toggle|"
        r"hover|the|a|an|on|into|in|inside|from|at)\s+",
        re.IGNORECASE,
    )
    text = intent.strip()
    prev = None
    while prev != text:
        prev = text
        text = stop.sub("", text).strip()
    return text


async def _try_locator(locator: "Locator") -> "Locator | None":
    try:
        if await locator.count() > 0 and await locator.first.is_visible():
            return locator.first
    except Exception:
        pass
    return None


class LocatorResolver:
    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()

    # ── Public API ────────────────────────────────────────────────────────────

    async def resolve(self, intent: str, page: "Page") -> "Locator":
        """Resolve a natural language element description to a Playwright Locator."""
        sig = await get_page_signature(page)
        cache_key = f"{intent}|{sig}"

        # 1. Cache hit
        cached = self._cache.get_locator(cache_key)
        if cached:
            locator = self._locator_from_cached(cached, page)
            if locator and await _try_locator(locator):
                return locator

        # 2. Deterministic strategies
        winner = await self._try_deterministic(intent, page)
        if winner:
            self._cache.set_locator(cache_key, self._serialize_locator(winner, intent))
            return winner

        # 3. LLM fallback
        winner = await self._try_llm(intent, page, sig)
        if winner:
            self._cache.set_locator(cache_key, self._serialize_locator(winner, intent))
            return winner

        raise LocatorNotFoundError(f"Could not resolve locator for: {intent!r}")

    # ── Deterministic strategies ──────────────────────────────────────────────

    async def _try_deterministic(self, intent: str, page: "Page") -> "Locator | None":
        quoted = _extract_quoted_text(intent)
        role = _guess_role(intent)
        text = quoted or _extract_meaningful_text(intent)

        strategies: list["Locator"] = []

        # role + name (most reliable)
        if role and text:
            strategies.append(page.get_by_role(role, name=text))  # type: ignore[arg-type]
        elif role:
            strategies.append(page.get_by_role(role))  # type: ignore[arg-type]

        # label (for form inputs)
        if text:
            strategies.append(page.get_by_label(text))
            strategies.append(page.get_by_placeholder(text))

        # exact text (for buttons / links)
        if text:
            strategies.append(page.get_by_text(text, exact=True))
            strategies.append(page.get_by_text(text, exact=False))

        # testid if mentioned
        if "testid" in intent.lower() or "test-id" in intent.lower():
            for match in re.finditer(r"['\"]([^'\"]+)['\"]", intent):
                strategies.append(page.get_by_test_id(match.group(1)))

        for loc in strategies:
            result = await _try_locator(loc)
            if result:
                return result
        return None

    # ── LLM fallback ─────────────────────────────────────────────────────────

    async def _try_llm(self, intent: str, page: "Page", sig: str) -> "Locator | None":
        llm_cache_key = self._ollama.prompt_hash(
            f"locator:{intent}:{sig}", self._model, 0.0
        )
        cached_proposal = self._cache.get_llm(llm_cache_key)
        if cached_proposal:
            proposal = LocatorProposal.model_validate(cached_proposal)
        else:
            dom_ctx = await get_dom_context(page)
            aom_ctx = await get_aom_context(page)
            prompt = prompts.render(
                "locator_resolve.j2",
                intent=intent,
                dom_context=dom_ctx,
                aom_context=aom_ctx,
            )
            proposal = await self._ollama.generate_structured(
                prompt=prompt,
                schema=LocatorProposal,
                model=self._model,
                temperature=0.0,
            )
            self._cache.set_llm(llm_cache_key, proposal.model_dump())

        for candidate in sorted(proposal.locators, key=lambda c: c.confidence, reverse=True):
            loc = self._candidate_to_locator(candidate, page)
            if loc:
                result = await _try_locator(loc)
                if result:
                    return result
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _candidate_to_locator(
        self, candidate: LocatorCandidate, page: "Page"
    ) -> "Locator | None":
        try:
            if candidate.strategy == LocatorStrategy.CSS:
                return page.locator(candidate.value)
            elif candidate.strategy == LocatorStrategy.ROLE:
                kwargs: dict = {}
                if candidate.name:
                    kwargs["name"] = candidate.name
                return page.get_by_role(candidate.role or "button", **kwargs)  # type: ignore
            elif candidate.strategy == LocatorStrategy.TEXT:
                return page.get_by_text(candidate.value)
            elif candidate.strategy == LocatorStrategy.LABEL:
                return page.get_by_label(candidate.value)
            elif candidate.strategy == LocatorStrategy.PLACEHOLDER:
                return page.get_by_placeholder(candidate.value)
            elif candidate.strategy == LocatorStrategy.TESTID:
                return page.get_by_test_id(candidate.value)
        except Exception:
            pass
        return None

    def _locator_from_cached(self, cached: dict, page: "Page") -> "Locator | None":
        try:
            candidate = LocatorCandidate.model_validate(cached)
            return self._candidate_to_locator(candidate, page)
        except Exception:
            return None

    def _serialize_locator(self, locator: "Locator", intent: str) -> dict:
        # Store as a CSS candidate so we can reconstruct it
        # Best effort: use the locator's string representation
        selector = str(locator)
        return LocatorCandidate(
            strategy=LocatorStrategy.CSS,
            value=selector,
            confidence=1.0,
        ).model_dump()


class LocatorNotFoundError(RuntimeError):
    pass
