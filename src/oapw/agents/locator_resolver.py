"""LocatorResolver — cache-first, deterministic-first, self-healing locator pipeline.

Resolution priority (per PLAN §5.1):
  1. L1/L2 cache hit → validate is_visible() → return
  2. Cache hit but stale → Healer (fingerprint → role+text variant → LLM)
  3. Deterministic Playwright strategies (role, label, placeholder, text, testid)
  4. LLM proposal → validate → cache winner

Fingerprints are stored alongside every cached locator so the Healer can
search the new DOM for the same semantic element after UI changes.
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
from oapw.healing.fingerprint import ElementFingerprint, fingerprint_from_element
import oapw.prompts as prompts

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

# Heuristic role keyword map for deterministic strategy
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
    """Strip leading action words AND trailing role nouns to get the element label.

    "Click the Sign in button"  → "Sign in"
    "Email address input"       → "Email address"
    "Forgot password link"      → "Forgot password"
    """
    leading = re.compile(
        r"^(click|press|tap|fill|type|enter|select|choose|check|uncheck|toggle|"
        r"hover|the|a|an|on|into|in|inside|from|at)\s+",
        re.IGNORECASE,
    )
    trailing = re.compile(
        r"\s+(button|btn|link|input|field|textbox|checkbox|radio|select|"
        r"dropdown|combobox|heading|tab|slider|search|searchbox|form|"
        r"element|widget|control)$",
        re.IGNORECASE,
    )
    text = intent.strip()
    prev = None
    while prev != text:
        prev = text
        text = leading.sub("", text).strip()
        text = trailing.sub("", text).strip()
    return text


def _text_candidates(intent: str) -> list[str]:
    """Return all text variants worth trying: quoted, full intent, stripped."""
    variants: list[str] = []
    quoted = _extract_quoted_text(intent)
    if quoted:
        variants.append(quoted)
    stripped = _extract_meaningful_text(intent)
    if stripped and stripped != intent:
        variants.append(stripped)
    variants.append(intent)
    return list(dict.fromkeys(v for v in variants if v))


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
        healer: "Healer | None" = None,  # type: ignore[name-defined]
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()
        self._healer = healer  # injected lazily to avoid circular import

    def _get_healer(self) -> "Healer":
        if self._healer is None:
            from oapw.healing.healer import Healer
            self._healer = Healer(ollama=self._ollama, model=self._model)
        return self._healer

    # ── Public API ────────────────────────────────────────────────────────────

    async def resolve(self, intent: str, page: "Page") -> "Locator":
        """Resolve a natural language element description to a verified Playwright Locator."""
        sig = await get_page_signature(page)
        cache_key = f"{intent}|{sig}"

        # 1. Cache hit — validate-on-use
        cached = self._cache.get_locator(cache_key)
        if cached:
            locator = self._locator_from_cached(cached, page)
            if locator and await _try_locator(locator):
                return locator

            # 1b. Cache entry exists but element is gone/moved → heal
            fp = ElementFingerprint.from_dict(cached.get("fingerprint", {}))
            original_str = cached.get("locator_str", "")
            healed = await self._get_healer().heal(intent, original_str, fp, page)
            if healed:
                heal_candidate = LocatorCandidate(
                    strategy=LocatorStrategy.ROLE,
                    role=fp.role or "button",
                    name=fp.name or fp.text or fp.label or "",
                    value=fp.name or fp.text or fp.label or "",
                    confidence=0.9,
                )
                self._cache.set_locator(cache_key, self._build_cache_entry(heal_candidate, fp))
                return healed

        # 2. Deterministic strategies
        det_result = await self._try_deterministic(intent, page)
        if det_result:
            winner, winner_candidate = det_result
            fp = await self._extract_fp(winner)
            self._cache.set_locator(cache_key, self._build_cache_entry(winner_candidate, fp))
            return winner

        # 3. LLM fallback
        llm_result = await self._try_llm(intent, page, sig)
        if llm_result:
            winner, winner_candidate = llm_result
            fp = await self._extract_fp(winner)
            self._cache.set_locator(cache_key, self._build_cache_entry(winner_candidate, fp))
            return winner

        raise LocatorNotFoundError(f"Could not resolve locator for: {intent!r}")

    # ── Deterministic strategies ──────────────────────────────────────────────

    async def _try_deterministic(
        self, intent: str, page: "Page"
    ) -> "tuple[Locator, LocatorCandidate] | None":
        role = _guess_role(intent)
        candidates = _text_candidates(intent)

        strategies: list[tuple["Locator", LocatorCandidate]] = []

        for text in candidates:
            if role:
                strategies.append((
                    page.get_by_role(role, name=text),  # type: ignore[arg-type]
                    LocatorCandidate(strategy=LocatorStrategy.ROLE, role=role, name=text, value=text, confidence=1.0),
                ))
                strategies.append((
                    page.get_by_role(role, name=re.compile(re.escape(text), re.I)),  # type: ignore
                    LocatorCandidate(strategy=LocatorStrategy.ROLE, role=role, name=text, value=text, confidence=0.95),
                ))
            strategies.append((
                page.get_by_label(text),
                LocatorCandidate(strategy=LocatorStrategy.LABEL, value=text, confidence=1.0),
            ))
            strategies.append((
                page.get_by_placeholder(text),
                LocatorCandidate(strategy=LocatorStrategy.PLACEHOLDER, value=text, confidence=1.0),
            ))
            strategies.append((
                page.get_by_text(text, exact=True),
                LocatorCandidate(strategy=LocatorStrategy.TEXT, value=text, confidence=0.9),
            ))

        # role-only (no name) as final deterministic attempt
        if role:
            strategies.append((
                page.get_by_role(role),  # type: ignore[arg-type]
                LocatorCandidate(strategy=LocatorStrategy.ROLE, role=role, value="", confidence=0.5),
            ))

        # partial-text as last deterministic attempt (can be noisy, use sparingly)
        for text in candidates[:1]:
            strategies.append((
                page.get_by_text(text, exact=False),
                LocatorCandidate(strategy=LocatorStrategy.TEXT, value=text, confidence=0.5),
            ))

        if "testid" in intent.lower() or "test-id" in intent.lower():
            for m in re.finditer(r"['\"]([^'\"]+)['\"]", intent):
                strategies.append((
                    page.get_by_test_id(m.group(1)),
                    LocatorCandidate(strategy=LocatorStrategy.TESTID, value=m.group(1), confidence=1.0),
                ))

        for loc, candidate in strategies:
            result = await _try_locator(loc)
            if result:
                return result, candidate
        return None

    # ── LLM fallback ─────────────────────────────────────────────────────────

    async def _try_llm(
        self, intent: str, page: "Page", sig: str
    ) -> "tuple[Locator, LocatorCandidate] | None":
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
                    return result, candidate
        return None

    # ── Fingerprint extraction ────────────────────────────────────────────────

    async def _extract_fp(self, locator: "Locator") -> ElementFingerprint:
        """Extract a fingerprint by evaluating the resolved element directly."""
        try:
            el_data = await locator.evaluate("""el => {
                const INPUT_ROLES = {
                    checkbox:'checkbox', radio:'radio', range:'slider',
                    submit:'button', reset:'button', button:'button',
                    search:'searchbox', text:'textbox', email:'textbox',
                    password:'textbox', number:'spinbutton', tel:'textbox',
                    url:'textbox', date:'textbox', time:'textbox',
                };
                const TAG_ROLES = {A:'link', BUTTON:'button', TEXTAREA:'textbox'};
                const tag = el.tagName;
                let role = el.getAttribute('role') || TAG_ROLES[tag];
                if (tag === 'INPUT') role = INPUT_ROLES[el.type] || 'textbox';
                role = role || tag.toLowerCase();

                const label = (el.labels && el.labels[0])
                    ? el.labels[0].textContent.trim()
                    : (el.getAttribute('aria-label') || null);
                return {
                    role: role,
                    tag: tag.toLowerCase(),
                    text: (el.textContent || '').trim().substring(0, 80),
                    label: label,
                    placeholder: el.placeholder || null,
                    type: el.type || null,
                    href: el.href || null,
                    testid: el.getAttribute('data-testid') || null,
                    class: el.className || null,
                };
            }""")
            return fingerprint_from_element(el_data)
        except Exception:
            return ElementFingerprint()

    # ── Cache serialization ───────────────────────────────────────────────────

    def _build_cache_entry(self, candidate: LocatorCandidate, fp: ElementFingerprint) -> dict:
        return {
            "locator_str": candidate.value or "",
            "strategy": candidate.strategy.value,
            "value": candidate.value or "",
            "role": candidate.role,
            "name": candidate.name,
            "confidence": candidate.confidence,
            "fingerprint": fp.to_dict(),
        }

    def _locator_from_cached(self, cached: dict, page: "Page") -> "Locator | None":
        try:
            value = cached.get("value") or cached.get("locator_str", "")
            strategy = LocatorStrategy(cached.get("strategy", LocatorStrategy.CSS.value))
            candidate = LocatorCandidate(
                strategy=strategy,
                value=value,
                role=cached.get("role"),
                name=cached.get("name"),
                confidence=cached.get("confidence", 1.0),
            )
            return self._candidate_to_locator(candidate, page)
        except Exception:
            return None

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


class LocatorNotFoundError(RuntimeError):
    pass
