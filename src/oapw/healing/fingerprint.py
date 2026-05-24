"""Element fingerprinting — produces a stable descriptor that survives UI changes.

A fingerprint captures semantic identity (role, label, text, context) rather than
structural identity (id, class, XPath). This lets the healer match an element
even after IDs change, CSS classes are renamed, or elements move in the tree.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ElementFingerprint:
    role: str = ""
    name: str = ""           # accessible name (aria-label / label / text)
    text: str = ""           # visible text content
    label: str = ""          # associated <label> text
    placeholder: str = ""
    tag: str = ""
    input_type: str = ""     # for <input> elements
    parent_role: str = ""    # immediate parent's role
    parent_text: str = ""    # abbreviated parent text for context
    href: str = ""           # for links — path only, not domain
    testid: str = ""
    # stable class fragments (skip things that look like BEM modifiers / hashes)
    stable_classes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ElementFingerprint":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def hash(self) -> str:
        """Deterministic 32-char hex digest — used as cache sub-key."""
        key = "|".join([
            self.role, self.name, self.text, self.label,
            self.placeholder, self.tag, self.input_type, self.href,
        ])
        return hashlib.blake2b(key.encode(), digest_size=16).hexdigest()


# ── Similarity scoring ────────────────────────────────────────────────────────

_WEIGHTS = {
    "role": 3.0,
    "name": 2.5,
    "text": 2.0,
    "label": 2.0,
    "placeholder": 1.5,
    "input_type": 1.0,
    "parent_role": 0.5,
    "href_path": 0.5,
    "testid": 1.5,
}
def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _text_match(a: str, b: str) -> float:
    """Returns 1.0 for exact match, 0.5 for contains, 0.0 for no match."""
    a, b = _normalise(a), _normalise(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.5
    # Word overlap
    wa, wb = set(a.split()), set(b.split())
    if wa & wb:
        return len(wa & wb) / max(len(wa), len(wb)) * 0.7
    return 0.0


def _href_path(href: str) -> str:
    """Strip scheme + domain, keep path."""
    m = re.sub(r"^https?://[^/]*", "", href)
    return m or href


def fingerprint_similarity(a: ElementFingerprint, b: ElementFingerprint) -> float:
    """Return a score in [0, 1] — only counts fields populated in at least one fingerprint.

    Empty-in-both fields are excluded from both numerator and denominator so a
    partially-populated fingerprint matched against itself always scores 1.0.
    """
    score = 0.0
    applicable = 0.0

    def _add(field: str, val_a: str, val_b: str, match: float) -> None:
        nonlocal score, applicable
        if not val_a and not val_b:
            return  # skip fields that are empty in both — no signal
        w = _WEIGHTS.get(field, 0.0)
        applicable += w
        score += w * match

    _add("role", a.role, b.role, _text_match(a.role, b.role))
    _add("name", a.name, b.name, _text_match(a.name, b.name))
    _add("text", a.text, b.text, _text_match(a.text, b.text))
    _add("label", a.label, b.label, _text_match(a.label, b.label))
    _add("placeholder", a.placeholder, b.placeholder, _text_match(a.placeholder, b.placeholder))
    _add("input_type", a.input_type, b.input_type,
         1.0 if a.input_type == b.input_type else 0.0)
    _add("parent_role", a.parent_role, b.parent_role, _text_match(a.parent_role, b.parent_role))
    _add("href_path", _href_path(a.href), _href_path(b.href),
         _text_match(_href_path(a.href), _href_path(b.href)))
    _add("testid", a.testid, b.testid, _text_match(a.testid, b.testid))

    return round(score / applicable, 4) if applicable else 0.0


# ── Fingerprint from DOM element descriptor ───────────────────────────────────

def fingerprint_from_element(el: dict[str, Any]) -> ElementFingerprint:
    """Build a fingerprint from a DOM element descriptor (output of dom.py)."""
    role = el.get("role") or el.get("tag", "")
    name = (
        el.get("aria-label")
        or el.get("label")
        or el.get("text")
        or ""
    )
    href = el.get("href", "")
    # Strip domain from href
    href_path = re.sub(r"^https?://[^/]*", "", href) if href else ""

    # Stable class fragments: skip BEM modifiers, hashes, numbers
    raw_class = el.get("class", "")
    stable = [
        c for c in raw_class.split()
        if not re.match(r"^[a-f0-9]{5,}$", c)   # skip hashes
        and not re.match(r"^\d", c)               # skip number-starting
        and len(c) > 2
    ] if raw_class else []

    return ElementFingerprint(
        role=role,
        name=name,
        text=el.get("text", "") or "",
        label=el.get("label", "") or "",
        placeholder=el.get("placeholder", "") or "",
        tag=el.get("tag", "") or "",
        input_type=el.get("type", "") or "",
        href=href_path,
        testid=el.get("testid", "") or "",
        stable_classes=stable[:5],
    )


def find_best_match(
    target: ElementFingerprint,
    candidates: list[dict[str, Any]],
    threshold: float = 0.45,
) -> tuple[dict[str, Any], float] | None:
    """Find the candidate element that best matches the target fingerprint.

    Returns (element_dict, score) or None if no candidate exceeds threshold.
    """
    best_el: dict | None = None
    best_score = 0.0

    for el in candidates:
        fp = fingerprint_from_element(el)
        score = fingerprint_similarity(target, fp)
        if score > best_score:
            best_score = score
            best_el = el

    if best_el is not None and best_score >= threshold:
        return best_el, best_score
    return None
