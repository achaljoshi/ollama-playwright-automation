"""TestSelector — picks which tests to run given a parsed QaGoal.

Uses two sources ranked by relevance:
1. **QA Memory** — previously run tests that matched this feature area
2. **Knowledge Base** — tests linked to Jira tickets / Confluence pages that
   match the goal's feature areas and scope

The two lists are merged, de-duplicated, and sorted by a weighted relevance
score before being returned as a ranked list of :class:`TestCandidate`.

Usage::

    selector = TestSelector()
    candidates = await selector.select(goal, top_k=10)
"""

from __future__ import annotations

from oapw.qa_agent.memory import QaMemory
from oapw.qa_agent.models import QaGoal, TestCandidate, TestScope


_SCOPE_PRIORITY_MAP: dict[TestScope, list[str]] = {
    TestScope.CRITICAL: ["critical", "high"],
    TestScope.SMOKE: ["smoke", "critical", "high"],
    TestScope.REGRESSION: ["critical", "high", "medium"],
    TestScope.FULL: ["critical", "high", "medium", "low"],
}


class TestSelector:
    """Selects and ranks test candidates for a given :class:`QaGoal`.

    Parameters
    ----------
    memory:
        :class:`QaMemory` instance. Created fresh if *None*.
    kb:
        Knowledge base to search for test references. When *None*,
        only the memory source is used (no KB lookups needed).
    """

    def __init__(
        self,
        memory: QaMemory | None = None,
        kb: object | None = None,  # KnowledgeBase — avoid hard import
    ) -> None:
        self._memory = memory or QaMemory()
        self._kb = kb

    async def select(self, goal: QaGoal, top_k: int = 20) -> list[TestCandidate]:
        """Return up to *top_k* ranked :class:`TestCandidate` for *goal*.

        Candidates are sorted by a composite score that weighs:
        - Priority tier (critical > high > medium > low)
        - Relevance to the goal's feature areas
        - Memory presence (known tests for this feature)
        - Scope filter (smoke only includes smoke/critical/high)
        """
        candidates: dict[str, TestCandidate] = {}

        # 1. Memory — tests seen before in this feature area
        memory_candidates = self._from_memory(goal)
        for c in memory_candidates:
            candidates[c.test_name] = c

        # 2. KB — tests linked to matching Jira/Confluence docs
        if self._kb is not None:
            kb_candidates = await self._from_kb(goal)
            for c in kb_candidates:
                if c.test_name not in candidates:
                    candidates[c.test_name] = c
                else:
                    # Boost relevance if found in both sources
                    existing = candidates[c.test_name]
                    boosted = existing.model_copy(
                        update={"relevance_score": min(1.0, existing.relevance_score + 0.2)}
                    )
                    candidates[c.test_name] = boosted

        # 3. Filter by scope
        allowed_priorities = _SCOPE_PRIORITY_MAP.get(goal.scope, ["critical", "high", "medium", "low"])
        filtered = [c for c in candidates.values() if c.priority in allowed_priorities]

        # 4. Sort: relevance descending, then priority tier
        _priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_candidates = sorted(
            filtered,
            key=lambda c: (-c.relevance_score, _priority_order.get(c.priority, 99)),
        )

        return sorted_candidates[:top_k]

    # ── Memory source ─────────────────────────────────────────────────────────

    def _from_memory(self, goal: QaGoal) -> list[TestCandidate]:
        """Find tests in QA Memory that match the goal's feature areas."""
        history = self._memory._load_history()
        seen: dict[str, float] = {}

        for entry in history:
            test_name = entry.get("test_name", "")
            if not test_name:
                continue
            score = self._feature_relevance(test_name, goal.feature_areas)
            if score > 0.0:
                seen[test_name] = max(seen.get(test_name, 0.0), score)

        return [
            TestCandidate(
                test_name=name,
                priority="medium",
                relevance_score=score,
                source="memory",
            )
            for name, score in seen.items()
        ]

    # ── KB source ─────────────────────────────────────────────────────────────

    async def _from_kb(self, goal: QaGoal) -> list[TestCandidate]:
        """Search the Knowledge Base for tests linked to goal feature areas."""
        if self._kb is None:
            return []

        candidates: list[TestCandidate] = []
        query = " ".join(goal.feature_areas) or goal.intent

        try:
            results = await self._kb.search(  # type: ignore[union-attr]
                query=query,
                top_k=30,
                collection="test_registry",
            )
        except Exception:
            return []

        for hit in results:
            metadata = hit.get("metadata", {})
            test_name = metadata.get("test_name", "")
            if not test_name:
                continue
            candidates.append(
                TestCandidate(
                    test_name=test_name,
                    file_path=metadata.get("file_path", ""),
                    priority=metadata.get("priority", "medium"),
                    jira_ids=metadata.get("jira_ids", []),
                    confluence_ids=metadata.get("confluence_ids", []),
                    relevance_score=hit.get("score", 0.5),
                    source="kb",
                    tags=metadata.get("tags", []),
                )
            )

        return candidates

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _feature_relevance(test_name: str, feature_areas: list[str]) -> float:
        """Score 0.0–1.0 based on how many feature keywords appear in test_name."""
        if not feature_areas:
            return 0.3  # include everything when no filter
        lower = test_name.lower()
        hits = sum(1 for f in feature_areas if f.lower() in lower)
        return min(1.0, hits / len(feature_areas))
