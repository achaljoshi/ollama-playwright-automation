"""Human-in-loop hook system for the AgentRunner.

Architecture
────────────
HookEvent        — what just happened (enum)
HookContext      — everything the handler needs to make a decision
HookDecision     — what the handler wants the runner to do next
HookResponse     — decision + optional override value + free-text note
HookHandler      — async callable protocol
HookRegistry     — maps events to handlers; fires them; returns response

Built-in hooks
──────────────
SilentHook      — always returns CONTINUE (default in non-interactive mode)
ConsoleHook     — prints context to stdout, reads decision from stdin
               (used when --interactive flag is set in the CLI)

Usage::

    registry = HookRegistry()
    # Register your own handler for failed steps:
    registry.register(HookEvent.STEP_FAILED, my_slack_handler)

    runner = AgentRunner(hooks=registry)
    result = await runner.run("Log in as admin", page)
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

# Direct import (no TYPE_CHECKING guard) so Pydantic can resolve forward refs.
from oapw.agents.models import Plan, Step, StepResult  # noqa: F401


# ── Events ────────────────────────────────────────────────────────────────────

class HookEvent(str, Enum):
    """Lifecycle events that the AgentRunner can fire."""

    PLAN_READY = "plan_ready"
    """A Plan has just been generated; steps not yet executed."""

    STEP_ABOUT_TO_RUN = "step_about_to_run"
    """A step is about to be dispatched to the Executor."""

    STEP_FAILED = "step_failed"
    """A step failed (exception raised or success=False)."""

    ASSERTION_FAILED = "assertion_failed"
    """An ASSERT step returned passed=False with high confidence."""

    LOOP_DETECTED = "loop_detected"
    """LoopGuard raised LoopViolation."""

    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    """LoopGuard's budget was exhausted."""

    RUN_COMPLETE = "run_complete"
    """The run finished (success or failure)."""


# ── Decisions ─────────────────────────────────────────────────────────────────

class HookDecision(str, Enum):
    """What the runner should do after receiving a HookResponse."""

    CONTINUE = "continue"
    """Proceed as planned (skip failed step / carry on)."""

    ABORT = "abort"
    """Stop the run immediately; surface the error to the caller."""

    RETRY = "retry"
    """Retry the current step from scratch (up to ``max_retries`` times)."""

    OVERRIDE = "override"
    """Use ``HookResponse.override_value`` as the new ``step.value`` and retry."""


# ── Context & Response ────────────────────────────────────────────────────────

class HookContext(BaseModel):
    """Data passed into every hook handler."""

    event: HookEvent
    goal: str
    plan: Plan
    current_step: Step | None = None
    step_result: StepResult | None = None
    error: str | None = None
    metadata: dict = Field(default_factory=dict)


class HookResponse(BaseModel):
    """What the handler wants the runner to do."""

    decision: HookDecision = HookDecision.CONTINUE
    override_value: str | None = None
    """New value for the current step (only used when decision=OVERRIDE)."""
    note: str = ""


# ── Handler protocol ──────────────────────────────────────────────────────────

HookHandler = Callable[[HookContext], Awaitable[HookResponse]]
"""Type alias for hook handlers — any async callable matching this signature."""


# ── Registry ──────────────────────────────────────────────────────────────────

class HookRegistry:
    """Holds per-event handlers and fires them when the runner raises events.

    Only one handler per event is supported (last ``register()`` wins).
    Use a composite handler if you need fan-out.
    """

    def __init__(self) -> None:
        self._handlers: dict[HookEvent, HookHandler] = {}
        self._default: HookHandler = _silent_handler

    def register(self, event: HookEvent, handler: HookHandler) -> None:
        """Register *handler* for *event*, replacing any existing handler."""
        self._handlers[event] = handler

    def unregister(self, event: HookEvent) -> None:
        """Remove the handler for *event* (falls back to the silent default)."""
        self._handlers.pop(event, None)

    def set_default(self, handler: HookHandler) -> None:
        """Set a catch-all handler used when no specific handler is registered."""
        self._default = handler

    async def fire(self, event: HookEvent, ctx: HookContext) -> HookResponse:
        """Fire the handler for *event* (or the default) and return its response."""
        handler = self._handlers.get(event, self._default)
        return await handler(ctx)

    def has_handler(self, event: HookEvent) -> bool:
        """Return True if a specific (non-default) handler is registered."""
        return event in self._handlers


# ── Built-in hooks ────────────────────────────────────────────────────────────

async def _silent_handler(ctx: HookContext) -> HookResponse:
    """Default handler — always continues without user interaction."""
    return HookResponse(decision=HookDecision.CONTINUE)


class SilentHook:
    """Always CONTINUE — use in non-interactive (CI) mode."""

    async def __call__(self, ctx: HookContext) -> HookResponse:
        return HookResponse(decision=HookDecision.CONTINUE)


class ConsoleHook:
    """Interactive hook that prints context to stdout and reads stdin.

    Useful for local development and the ``oapw run --interactive`` flag.
    Falls back to ABORT on non-interactive stdin (e.g. piped input).
    """

    _DECISION_MAP = {
        "c": HookDecision.CONTINUE,
        "continue": HookDecision.CONTINUE,
        "a": HookDecision.ABORT,
        "abort": HookDecision.ABORT,
        "r": HookDecision.RETRY,
        "retry": HookDecision.RETRY,
        "o": HookDecision.OVERRIDE,
        "override": HookDecision.OVERRIDE,
    }

    async def __call__(self, ctx: HookContext) -> HookResponse:  # pragma: no cover
        import sys

        print(f"\n[OAPW hook] Event: {ctx.event.value}")
        print(f"  Goal     : {ctx.goal}")
        if ctx.current_step:
            print(f"  Step     : {ctx.current_step.description}")
        if ctx.error:
            print(f"  Error    : {ctx.error}")

        if not sys.stdin.isatty():
            print("  (non-interactive stdin — aborting)")
            return HookResponse(decision=HookDecision.ABORT)

        choice = input("  Decision [C]ontinue / [A]bort / [R]etry / [O]verride: ").strip().lower()
        decision = self._DECISION_MAP.get(choice, HookDecision.ABORT)

        override_value: str | None = None
        if decision == HookDecision.OVERRIDE:
            override_value = input("  Override value: ").strip() or None

        note = input("  Note (optional): ").strip()
        return HookResponse(decision=decision, override_value=override_value, note=note)
