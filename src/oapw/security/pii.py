"""PiiMasker — detect and redact Personally Identifiable Information.

Applied automatically when:
  - DOM context is serialised for LLM prompts (via dom.py)
  - Jira ticket descriptions are embedded into the knowledge base
  - API request/response bodies are logged

Patterns covered:
  - Email addresses
  - Phone numbers (US and international)
  - Credit / debit card numbers (15–16 digits with separators)
  - US Social Security Numbers (NNN-NN-NNNN)
  - UK National Insurance numbers
  - AWS access key IDs (AKIA...)
  - JWT tokens (eyJ...)
  - Bearer tokens in Authorization headers
  - Passwords / secrets in JSON key-value pairs

Usage:
    masker = PiiMasker()
    clean = masker.mask("Contact alice@example.com or call +1 555-123-4567")
    # → "Contact [EMAIL] or call [PHONE]"

    clean_dict = masker.mask_dict({"email": "alice@example.com", "notes": "call +1 555-123-4567"})
    # → {"email": "[EMAIL]", "notes": "call [PHONE]"}

    findings = masker.detect("Card 4111 1111 1111 1111")
    # → [PiiMatch(type="CARD", value="4111 1111 1111 1111", start=5, end=24)]
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class PiiMatch:
    """A single PII finding in a text string."""
    type: str          # "EMAIL", "PHONE", "CARD", "SSN", "AWS_KEY", "JWT", "PASSWORD"
    value: str         # The matched text
    start: int         # Start index in the original text
    end: int           # End index in the original text


# ── Regex patterns ────────────────────────────────────────────────────────────

# Each entry: (compiled_regex, replacement_string_or_None)
# When replacement is None the pattern uses capture groups for surgical masking.

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # JWT tokens (eyJhbGciO... pattern) — must come BEFORE generic bearer
    (
        re.compile(r'\beyJ[A-Za-z0-9+/=_-]{10,}\.[A-Za-z0-9+/=_-]{10,}\.[A-Za-z0-9+/=_-]{10,}\b'),
        "[JWT]",
    ),
    # Bearer token in Authorization header
    (
        re.compile(r'(Bearer\s+)[A-Za-z0-9+/=_.-]{20,}', re.IGNORECASE),
        r"\1[TOKEN]",
    ),
    # AWS Access Key ID
    (
        re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
        "[AWS_KEY]",
    ),
    # AWS Secret Access Key (40 chars of base64ish)
    (
        re.compile(r'\b[A-Za-z0-9/+]{40}\b'),
        "[AWS_SECRET]",
    ),
    # Email addresses
    (
        re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'),
        "[EMAIL]",
    ),
    # Phone — international (+XX ...) and US formats
    (
        re.compile(
            r'(?<!\d)'                              # not preceded by digit
            r'(\+\d{1,3}[\s.-]?)?'                 # optional country code
            r'\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}'
            r'(?!\d)',                              # not followed by digit
        ),
        "[PHONE]",
    ),
    # Credit / debit card numbers (Visa, MC, Amex, Discover)
    # Accepts spaces, hyphens, or plain digits; 13–16 digit groups
    (
        re.compile(
            r'\b(?:4[0-9]{12}(?:[0-9]{3})?'        # Visa
            r'|(?:5[1-5][0-9]{2}|222[1-9]|22[3-9][0-9]|2[3-6][0-9]{2}|27[01][0-9]|2720)[0-9]{12}'  # MC
            r'|3[47][0-9]{13}'                      # Amex
            r'|3(?:0[0-5]|[68][0-9])[0-9]{11}'     # Diners
            r'|6(?:011|5[0-9]{2})[0-9]{12}'        # Discover
            r'|(?:\d{4}[-\s]){3}\d{4})\b'          # Generic 4-4-4-4
        ),
        "[CARD]",
    ),
    # US Social Security Number
    (
        re.compile(r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b'),
        "[SSN]",
    ),
    # UK National Insurance Number
    (
        re.compile(r'\b[A-Z]{2}\s*\d{2}\s*\d{2}\s*\d{2}\s*[A-D]\b'),
        "[NI]",
    ),
    # Password / secret / token values in JSON or URL-encoded payloads
    # Matches: "password": "...", 'secret': '...'
    (
        re.compile(
            r'(["\']?(?:password|passwd|pwd|secret|api_?key|auth_?token|access_?token|private_?key)["\']?'
            r'\s*[:=]\s*["\']?)([^"\'&\s,}{]{4,})(["\']?)',
            re.IGNORECASE,
        ),
        r"\1[REDACTED]\3",
    ),
]

# Canonical label for detect() output — maps regex index to type name
_PATTERN_TYPES = [
    "JWT", "BEARER_TOKEN", "AWS_KEY", "AWS_SECRET",
    "EMAIL", "PHONE", "CARD", "SSN", "NI", "PASSWORD",
]


class PiiMasker:
    """Applies all PII patterns to strings and dicts.

    Thread-safe (stateless — all patterns compiled at import time).
    """

    def mask(self, text: str) -> str:
        """Replace all PII in ``text`` with placeholder tokens."""
        if not text:
            return text
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def mask_dict(self, data: Any, _depth: int = 0) -> Any:
        """Recursively mask PII in a dict, list, or scalar value.

        Handles nested structures up to depth 20.
        """
        if _depth > 20:
            return data
        if isinstance(data, dict):
            return {k: self.mask_dict(v, _depth + 1) for k, v in data.items()}
        if isinstance(data, list):
            return [self.mask_dict(item, _depth + 1) for item in data]
        if isinstance(data, str):
            return self.mask(data)
        return data

    def mask_json(self, json_text: str) -> str:
        """Parse ``json_text``, mask all PII, and re-serialise."""
        try:
            data = json.loads(json_text)
            masked = self.mask_dict(data)
            return json.dumps(masked)
        except (json.JSONDecodeError, TypeError):
            return self.mask(json_text)

    def detect(self, text: str) -> list[PiiMatch]:
        """Return a list of PII findings without modifying the text."""
        findings: list[PiiMatch] = []
        for i, (pattern, _) in enumerate(
            zip([p for p, _ in _PATTERNS], _PATTERN_TYPES)
        ):
            ptype = _PATTERN_TYPES[i]
            for m in pattern.finditer(text):
                findings.append(PiiMatch(
                    type=ptype,
                    value=m.group(0),
                    start=m.start(),
                    end=m.end(),
                ))
        # Sort by position
        findings.sort(key=lambda f: f.start)
        return findings

    def has_pii(self, text: str) -> bool:
        """Return True if any PII is detected in ``text``."""
        return bool(self.detect(text))


# ── Module-level singleton ────────────────────────────────────────────────────

_masker: PiiMasker | None = None


def get_pii_masker() -> PiiMasker:
    """Return the module-level PiiMasker singleton."""
    global _masker
    if _masker is None:
        _masker = PiiMasker()
    return _masker
