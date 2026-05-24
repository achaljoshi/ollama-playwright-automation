"""Recency/owner/access weighting for Confluence pages (PLAN §8.6).

Signals:
  - Recency: pages edited within the last 90 days score higher (linear decay)
  - Owner/team: page authored by or labelled with the relevant component's team
  - Base: every page gets a minimum score so nothing is silently ignored
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oapw.enterprise.atlassian_client import ConfluencePage

_RECENT_DAYS = 90
_RECENT_WEIGHT = 0.40
_OWNER_WEIGHT = 0.35
_BASE_WEIGHT = 0.25


@dataclass
class WeightedPage:
    page: "ConfluencePage"
    score: float
    reasons: list[str] = field(default_factory=list)


def weight_pages(
    pages: list["ConfluencePage"],
    component: str | None = None,
    ref_date: datetime | None = None,
) -> list[WeightedPage]:
    """Score and sort Confluence pages by relevance signals.

    Args:
        pages: List of Confluence pages to score.
        component: Jira component name for team-ownership matching.
        ref_date: Reference date (defaults to now UTC).

    Returns:
        List of WeightedPage objects sorted by score descending.
    """
    if not pages:
        return []

    now = ref_date or datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=_RECENT_DAYS)

    weighted: list[WeightedPage] = []
    for page in pages:
        score = _BASE_WEIGHT
        reasons: list[str] = []

        # ── Recency ──────────────────────────────────────────────────────────
        if page.last_modified:
            modified = _parse_iso(page.last_modified)
            if modified and modified >= cutoff:
                days_old = max(0, (now - modified).days)
                recency = 1.0 - (days_old / _RECENT_DAYS)
                score += _RECENT_WEIGHT * recency
                reasons.append(f"modified {days_old}d ago")

        # ── Owner / component team match ─────────────────────────────────────
        if component:
            comp_lower = component.lower()
            if (
                comp_lower in page.author.lower()
                or any(comp_lower in lbl.lower() for lbl in page.labels)
            ):
                score += _OWNER_WEIGHT
                reasons.append(f"associated with {component} team")

        weighted.append(WeightedPage(
            page=page,
            score=min(1.0, round(score, 4)),
            reasons=reasons,
        ))

    weighted.sort(key=lambda w: w.score, reverse=True)
    return weighted


def _parse_iso(dt_str: str) -> datetime | None:
    """Parse ISO-8601 datetime string tolerantly (handles Z, ms, timezone offset)."""
    try:
        # Normalise: strip milliseconds, replace trailing Z with +00:00
        s = re.sub(r"\.\d+", "", dt_str)
        s = re.sub(r"Z$", "+00:00", s)
        return datetime.fromisoformat(s)
    except Exception:
        return None
