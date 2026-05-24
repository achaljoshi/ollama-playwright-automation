"""DOM serializer — produces compact, LLM-friendly representations of a page's interactive elements.

Strategy: run a small JS snippet directly in the browser so we get rendered state
(visibility, computed labels) rather than raw HTML, which may be minified or SSR-noisy.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

# JS that extracts all interactive elements from the live DOM.
# Returns a JSON array of element descriptors.
_EXTRACT_INTERACTIVE_JS = """
() => {
    const ROLES = {
        'A': 'link', 'BUTTON': 'button', 'INPUT': null, 'SELECT': 'select',
        'TEXTAREA': 'textbox', 'DETAILS': 'group', 'SUMMARY': 'button',
        'H1': 'heading', 'H2': 'heading', 'H3': 'heading',
        'H4': 'heading', 'H5': 'heading', 'H6': 'heading',
    };
    const INPUT_ROLES = {
        'checkbox': 'checkbox', 'radio': 'radio', 'range': 'slider',
        'submit': 'button', 'reset': 'button', 'button': 'button',
        'search': 'searchbox', 'text': 'textbox', 'email': 'textbox',
        'password': 'textbox', 'number': 'spinbutton', 'tel': 'textbox',
        'url': 'textbox', 'date': 'textbox', 'time': 'textbox',
    };

    function isVisible(el) {
        const s = window.getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' &&
               s.opacity !== '0' && el.offsetWidth > 0 && el.offsetHeight > 0;
    }

    function getLabel(el) {
        if (el.labels && el.labels.length > 0) return el.labels[0].textContent.trim();
        const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
        if (aria) {
            const ref = document.getElementById(aria);
            return ref ? ref.textContent.trim() : aria;
        }
        const id = el.id;
        if (id) {
            const lbl = document.querySelector('label[for="' + id + '"]');
            if (lbl) return lbl.textContent.trim();
        }
        return null;
    }

    const results = [];
    const seen = new Set();

    const selectors = [
        'a[href]', 'button', 'input:not([type="hidden"])', 'select', 'textarea',
        '[role="button"]', '[role="link"]', '[role="checkbox"]', '[role="radio"]',
        '[role="textbox"]', '[role="combobox"]', '[role="menuitem"]',
        '[tabindex]:not([tabindex="-1"])'
    ];

    document.querySelectorAll(selectors.join(',')).forEach(el => {
        if (!isVisible(el) || seen.has(el)) return;
        seen.add(el);

        const tag = el.tagName;
        let role = el.getAttribute('role') || ROLES[tag];
        if (tag === 'INPUT') role = INPUT_ROLES[el.type] || 'textbox';

        const desc = {
            role: role || tag.toLowerCase(),
            tag: tag.toLowerCase(),
            id: el.id || null,
            name: el.name || null,
            text: (el.textContent || '').trim().substring(0, 80) || null,
            label: getLabel(el),
            placeholder: el.placeholder || null,
            type: el.type || null,
            value: (tag === 'INPUT' || tag === 'TEXTAREA') ? (el.value || null) : null,
            href: el.href || null,
            disabled: el.disabled || false,
            required: el.required || false,
            testid: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || null,
            'aria-label': el.getAttribute('aria-label') || null,
        };
        // Drop null fields to keep output compact
        Object.keys(desc).forEach(k => desc[k] === null && delete desc[k]);
        results.push(desc);
    });
    return JSON.stringify(results);
}
"""


async def extract_interactive_elements(page: "Page") -> list[dict]:
    """Return a list of interactive element descriptors from the live page."""
    raw = await page.evaluate(_EXTRACT_INTERACTIVE_JS)
    return json.loads(raw)


def serialize_elements(elements: list[dict], max_elements: int = 80) -> str:
    """Convert element descriptors to a compact line-per-element text for LLM prompts."""
    lines: list[str] = []
    for el in elements[:max_elements]:
        role = el.get("role", el.get("tag", "?"))
        parts = [f"[{role}]"]

        label = el.get("label") or el.get("text") or el.get("aria-label")
        if label:
            parts.append(f'"{label}"')

        if el.get("placeholder"):
            parts.append(f'placeholder="{el["placeholder"]}"')
        if el.get("href"):
            parts.append(f'href="{el["href"][:60]}"')
        if el.get("id"):
            parts.append(f'id={el["id"]}')
        if el.get("name"):
            parts.append(f'name={el["name"]}')
        if el.get("testid"):
            parts.append(f'testid={el["testid"]}')
        if el.get("disabled"):
            parts.append("(disabled)")
        if el.get("required"):
            parts.append("(required)")

        lines.append(" ".join(parts))
    return "\n".join(lines)


async def get_dom_context(page: "Page", max_elements: int = 80) -> str:
    """One-shot: extract + serialize interactive elements from a live page."""
    elements = await extract_interactive_elements(page)
    return serialize_elements(elements, max_elements=max_elements)


async def get_page_text(page: "Page", max_chars: int = 4000) -> str:
    """Extract visible text content for extraction / assertion prompts."""
    text = await page.evaluate(
        """() => {
            const clone = document.body.cloneNode(true);
            clone.querySelectorAll('script,style,noscript,svg').forEach(e => e.remove());
            return clone.innerText || clone.textContent || '';
        }"""
    )
    text = " ".join(text.split())
    return text[:max_chars]
