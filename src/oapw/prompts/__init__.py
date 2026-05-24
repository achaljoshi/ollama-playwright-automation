"""Prompt template loader — Jinja2 templates stored alongside this package."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, **kwargs: object) -> str:
    """Render a prompt template by filename (e.g. 'locator_resolve.j2')."""
    tmpl = _env.get_template(template_name)
    return tmpl.render(**kwargs).strip()
