"""LoopGuard — detects infinite loops and enforces step-budget limits.

Two complementary detection mechanisms:

1. **Budget** — total number of steps executed may not exceed ``max_steps``.
   Prevents runaway execution against a broken page or an under-specified goal.

2. **Cycle detection** — looks back at the last ``window`` steps. If the
   same (action, target, url) tuple has appeared ``max_repeats`` or more
   times the runner is clearly cycling and we stop it early.

Usage::

    guard = LoopGuard(max_steps=50, window=6, max_repeats=3)
    for step in plan.steps:
        # raises LoopViolation if a limit is hit
        guard.record(step, page.url)
        await executor.execute_step(step, page)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class LoopViolation(Exception):
    """Raised by :meth:`LoopGuard.record` when a limit is exceeded."""

    reason: str

    def __str__(self) -> str:  # pragma: no cover
        return self.reason


@dataclass
class _StepKey:
    action: str
    target: str | None
    url: str

    def __hash__(self) -> int:
        return hash((self.action, self.target, self.url))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _StepKey):
            return NotImplemented
        return (self.action, self.target, self.url) == (other.action, other.target, other.url)


class LoopGuard:
    """Stateful guard — create one per :meth:`AgentRunner.run` call.

    Parameters
    ----------
    max_steps:
        Hard cap on total steps. Raises :class:`LoopViolation` when exceeded.
    window:
        Sliding window size for cycle detection.
    max_repeats:
        How many times the same ``(action, target, url)`` key may appear
        inside the window before it is considered a cycle.
    """

    def __init__(
        self,
        max_steps: int = 50,
        window: int = 6,
        max_repeats: int = 3,
    ) -> None:
        self._max_steps = max_steps
        self._window = window
        self._max_repeats = max_repeats
        self._total: int = 0
        self._history: deque[_StepKey] = deque(maxlen=window)

    # ── Public API ────────────────────────────────────────────────────────────

    def record(self, action: str, target: str | None, url: str) -> None:
        """Record a step and raise :class:`LoopViolation` if any limit is hit.

        Parameters
        ----------
        action:
            The :class:`~oapw.agents.models.StepAction` value (string).
        target:
            The element description (may be ``None``).
        url:
            The current page URL at the time this step is about to execute.
        """
        self._total += 1

        if self._total > self._max_steps:
            raise LoopViolation(
                f"Step budget exceeded: {self._total} > {self._max_steps} max steps"
            )

        key = _StepKey(action=action, target=target, url=url)
        self._history.append(key)

        repeat_count = sum(1 for k in self._history if k == key)
        if repeat_count >= self._max_repeats:
            raise LoopViolation(
                f"Cycle detected: step ({action!r}, target={target!r}) on {url!r} "
                f"repeated {repeat_count}× in the last {self._window} steps"
            )

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def steps_recorded(self) -> int:
        """Total number of steps recorded since construction."""
        return self._total

    @property
    def remaining_budget(self) -> int:
        """Steps remaining before the hard cap is hit."""
        return max(0, self._max_steps - self._total)

    def reset(self) -> None:
        """Reset all counters (useful for replan scenarios)."""
        self._total = 0
        self._history.clear()
