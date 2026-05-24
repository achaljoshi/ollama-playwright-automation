"""AOM (Accessibility Object Model) extractor — turns Playwright's accessibility snapshot
into a compact, indented text representation suitable for LLM prompts.

Playwright's page.accessibility.snapshot() returns the browser's computed AX tree,
which is more semantic and role-accurate than raw HTML — ideal for intent matching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

# Roles we care about for interactive/structural context; skip purely cosmetic nodes.
_INTERACTIVE_ROLES = {
    "button", "link", "checkbox", "radio", "textbox", "searchbox",
    "combobox", "listbox", "option", "menuitem", "menuitemcheckbox",
    "menuitemradio", "slider", "spinbutton", "switch", "tab", "treeitem",
    "columnheader", "rowheader", "cell",
}
_STRUCTURAL_ROLES = {"heading", "img", "list", "listitem", "table", "row", "dialog", "alertdialog"}
_SKIP_ROLES = {"generic", "none", "presentation", "group"}


def _node_to_lines(node: dict[str, Any], depth: int = 0, max_depth: int = 8) -> list[str]:
    if depth > max_depth:
        return []
    role = node.get("role", "")
    if role in _SKIP_ROLES and not node.get("children"):
        return []

    indent = "  " * depth
    parts = [role]

    name = node.get("name", "").strip()
    if name:
        parts.append(f'"{name}"')

    # Extra properties
    extras = []
    if node.get("required"):
        extras.append("required")
    if node.get("disabled"):
        extras.append("disabled")
    if node.get("checked") is True:
        extras.append("checked")
    if node.get("checked") is False and role in {"checkbox", "radio"}:
        extras.append("unchecked")
    if node.get("expanded") is not None:
        extras.append("expanded" if node["expanded"] else "collapsed")
    if node.get("level"):
        extras.append(f"level={node['level']}")
    if node.get("value") is not None:
        extras.append(f'value="{node["value"]}"')
    if extras:
        parts.append(f"({', '.join(extras)})")

    line = indent + " ".join(parts)
    lines = [line]

    for child in node.get("children") or []:
        lines.extend(_node_to_lines(child, depth + 1, max_depth))

    return lines


def aom_snapshot_to_text(snapshot: dict[str, Any] | None, max_lines: int = 120) -> str:
    """Serialize a Playwright AX snapshot to compact indented text."""
    if not snapshot:
        return "(no accessibility tree available)"
    lines = _node_to_lines(snapshot)
    return "\n".join(lines[:max_lines])


async def get_aom_context(page: "Page", max_lines: int = 120) -> str:
    """Extract the AOM from a live page and return as compact text."""
    snapshot = await page.accessibility.snapshot()
    return aom_snapshot_to_text(snapshot, max_lines=max_lines)
