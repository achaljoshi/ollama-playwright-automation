"""Individual healing strategies, each returning a resolved Locator or None.

Strategies are tried in order by the Healer — cheapest first:
  1. FingerprintStrategy  — O(n) DOM scan, no LLM call
  2. RoleTextStrategy     — deterministic Playwright API attempts
  3. LLMHealStrategy      — full LLM call with DOM context (expensive, cached)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.agents.models import LocatorCandidate, LocatorProposal, LocatorStrategy
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.dom import extract_interactive_elements, get_dom_context
from oapw.core.ollama_client import OllamaClient, get_ollama_client
from oapw.healing.fingerprint import (
    ElementFingerprint,
    fingerprint_from_element,
    find_best_match,
)

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


@dataclass
class HealAttempt:
    strategy: str
    locator: "Locator | None"
    confidence: float
    reasoning: str = ""


async def _try(locator: "Locator") -> "Locator | None":
    try:
        if await locator.count() > 0 and await locator.first.is_visible():
            return locator.first
    except Exception:
        pass
    return None


# ── 1. Fingerprint strategy ───────────────────────────────────────────────────

class FingerprintStrategy:
    name = "fingerprint"

    async def attempt(
        self,
        intent: str,
        target_fp: ElementFingerprint,
        page: "Page",
    ) -> HealAttempt:
        elements = await extract_interactive_elements(page)
        match = find_best_match(target_fp, elements, threshold=0.45)
        if not match:
            return HealAttempt(strategy=self.name, locator=None, confidence=0.0)

        el, score = match
        locator = _element_to_locator(el, page)
        if locator:
            verified = await _try(locator)
            if verified:
                return HealAttempt(
                    strategy=self.name,
                    locator=verified,
                    confidence=score,
                    reasoning=f"Fingerprint match (score={score:.2f})",
                )
        return HealAttempt(strategy=self.name, locator=None, confidence=0.0)


def _element_to_locator(el: dict, page: "Page") -> "Locator | None":
    try:
        role = el.get("role") or el.get("tag", "")
        name = el.get("label") or el.get("text") or el.get("aria-label")
        if role and name:
            return page.get_by_role(role, name=name)  # type: ignore[arg-type]
        if name:
            return page.get_by_text(name, exact=True)
        placeholder = el.get("placeholder")
        if placeholder:
            return page.get_by_placeholder(placeholder)
        testid = el.get("testid")
        if testid:
            return page.get_by_test_id(testid)
        el_id = el.get("id")
        if el_id:
            return page.locator(f"#{el_id}")
    except Exception:
        pass
    return None


# ── 2. Role + text variant strategy ──────────────────────────────────────────

class RoleTextStrategy:
    """Try common text variations: plurals, synonyms, title/lower case, partial."""

    name = "role_text_variant"

    _SYNONYMS: dict[str, list[str]] = {
        "sign in": ["login", "log in", "signin"],
        "login": ["sign in", "log in", "signin"],
        "log in": ["login", "sign in", "signin"],
        "sign up": ["register", "create account", "join", "signup"],
        "register": ["sign up", "create account", "join"],
        "submit": ["send", "save", "confirm", "continue", "next"],
        "search": ["find", "go", "look up"],
        "add to cart": ["add", "buy", "purchase"],
        "delete": ["remove", "discard"],
        "cancel": ["close", "dismiss", "back"],
    }

    async def attempt(
        self,
        intent: str,
        target_fp: ElementFingerprint,
        page: "Page",
    ) -> HealAttempt:
        role = target_fp.role or None
        base_text = target_fp.name or target_fp.text or target_fp.label

        candidates_text = _text_variants(base_text)

        for text in candidates_text:
            locs = []
            if role:
                locs.append(page.get_by_role(role, name=text))  # type: ignore
                locs.append(page.get_by_role(role, name=re.compile(re.escape(text), re.I)))  # type: ignore
            locs.append(page.get_by_text(text, exact=True))
            locs.append(page.get_by_text(text, exact=False))

            for loc in locs:
                verified = await _try(loc)
                if verified:
                    return HealAttempt(
                        strategy=self.name,
                        locator=verified,
                        confidence=0.75,
                        reasoning=f"Text variant match: '{text}'",
                    )
        return HealAttempt(strategy=self.name, locator=None, confidence=0.0)


def _text_variants(text: str) -> list[str]:
    if not text:
        return []
    variants = [text, text.title(), text.lower(), text.upper()]
    lower = text.lower()
    for canonical, syns in RoleTextStrategy._SYNONYMS.items():
        if canonical in lower:
            for s in syns:
                variants.append(text.lower().replace(canonical, s))
                variants.append(s.title())
    return list(dict.fromkeys(v for v in variants if v))


# ── 3. LLM heal strategy ──────────────────────────────────────────────────────

class LLMHealStrategy:
    name = "llm_heal"

    def __init__(self, ollama: OllamaClient | None = None, model: str | None = None) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()

    async def attempt(
        self,
        intent: str,
        original_locator: str,
        target_fp: ElementFingerprint,
        page: "Page",
    ) -> HealAttempt:
        from oapw.core.browser import get_page_signature

        sig = await get_page_signature(page)
        cache_key = self._ollama.prompt_hash(
            f"heal:{intent}:{original_locator}:{sig}", self._model, 0.0
        )
        cached = self._cache.get_llm(cache_key)
        if cached:
            proposal = LocatorProposal.model_validate(cached)
        else:
            dom_ctx = await get_dom_context(page)
            prompt = prompts.render(
                "heal.j2",
                intent=intent,
                original_locator=original_locator,
                fingerprint=target_fp,
                dom_context=dom_ctx,
            )
            proposal = await self._ollama.generate_structured(
                prompt=prompt,
                schema=LocatorProposal,
                model=self._model,
                temperature=0.0,
            )
            self._cache.set_llm(cache_key, proposal.model_dump())

        for candidate in sorted(proposal.locators, key=lambda c: c.confidence, reverse=True):
            loc = _candidate_to_locator(candidate, page)
            if loc:
                verified = await _try(loc)
                if verified:
                    return HealAttempt(
                        strategy=self.name,
                        locator=verified,
                        confidence=candidate.confidence,
                        reasoning=proposal.reasoning,
                    )
        return HealAttempt(strategy=self.name, locator=None, confidence=0.0)


def _candidate_to_locator(candidate: LocatorCandidate, page: "Page") -> "Locator | None":
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
