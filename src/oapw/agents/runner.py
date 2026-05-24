"""AgentRunner — orchestrates Planner + Executor with loop guards and human-in-loop hooks.

This is the top-level entry point for autonomous agent execution.

Flow
────
1. Call ``Planner.plan(goal, page)`` → ``Plan``
2. Fire ``PLAN_READY`` hook (human may abort here)
3. For each step in the plan:
   a. Fire ``STEP_ABOUT_TO_RUN`` hook
   b. Call ``LoopGuard.record(...)`` — raises ``LoopViolation`` if cycling
   c. ``Executor.execute_step(step, page)``
   d. If failed → fire ``STEP_FAILED`` hook:
      - CONTINUE  → skip, proceed to next step
      - ABORT     → stop run, return FAILED status
      - RETRY     → retry up to ``max_retries`` (increments attempt counter)
      - OVERRIDE  → patch step.value, retry once
   e. After all steps → attempt a replan if there are failures (optional)
4. Fire ``RUN_COMPLETE`` hook
5. Return ``RunResult``

Usage::

    from oapw.agents.runner import AgentRunner

    runner = AgentRunner()
    result = await runner.run("Add item to cart and checkout", page)
    if not result.ok:
        print(result.error)
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.agents.executor import Executor
from oapw.agents.hooks import HookContext, HookDecision, HookEvent, HookRegistry
from oapw.agents.loop_guard import LoopGuard, LoopViolation
from oapw.agents.models import (
    Plan,
    RunResult,
    RunStatus,
    Step,
    StepResult,
)
from oapw.agents.planner import Planner
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.dom import get_dom_context
from oapw.core.ollama_client import OllamaClient, get_ollama_client

if TYPE_CHECKING:
    from playwright.async_api import Page


class _ReplannedSteps:
    """Holder for a replanned steps list (mirrors Planner's _PlannerResponse)."""

    steps: list[Step]


class AgentRunner:
    """Orchestrates Planner + Executor with loop guards and human-in-loop hooks.

    Parameters
    ----------
    planner:
        The :class:`~oapw.agents.planner.Planner` to use. Created from config
        if *None*.
    executor:
        The :class:`~oapw.agents.executor.Executor` to use. Created from
        config if *None*.
    ollama:
        Shared :class:`~oapw.core.ollama_client.OllamaClient`. Created from
        config if *None*.
    model:
        Override the default LLM model.
    hooks:
        :class:`~oapw.agents.hooks.HookRegistry` for human-in-loop callbacks.
        A registry with only the silent default handler is created if *None*.
    max_steps:
        Hard cap on total steps. Overrides ``OAPW_AGENT_MAX_STEPS``.
    max_retries:
        How many times to retry a failed step before giving up.
    loop_window:
        Sliding window size for cycle detection.
    enable_replan:
        If *True*, the runner will ask the LLM to replan after a step failure
        before consulting the hook (default: True).
    """

    def __init__(
        self,
        planner: Planner | None = None,
        executor: Executor | None = None,
        ollama: OllamaClient | None = None,
        model: str | None = None,
        hooks: HookRegistry | None = None,
        max_steps: int | None = None,
        max_retries: int | None = None,
        loop_window: int | None = None,
        enable_replan: bool = True,
    ) -> None:
        cfg = get_config()
        self._ollama = ollama or get_ollama_client()
        self._model = model or cfg.ollama_default_model
        self._planner = planner or Planner(ollama=self._ollama, model=self._model)
        self._executor = executor or Executor(ollama=self._ollama, model=self._model)
        self._hooks = hooks or HookRegistry()
        self._max_steps = max_steps if max_steps is not None else cfg.agent_max_steps
        self._max_retries = max_retries if max_retries is not None else cfg.agent_max_step_retries
        self._loop_window = loop_window if loop_window is not None else cfg.agent_loop_window
        self._enable_replan = enable_replan
        self._cache = get_cache()

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, goal: str, page: "Page") -> RunResult:
        """Execute *goal* against *page* and return a :class:`RunResult`.

        This is the main entry point. It orchestrates the full planning +
        execution pipeline with loop guards and hook callbacks.
        """
        wall_start = time.monotonic()

        # 1. Plan
        plan = await self._planner.plan(goal, page)

        # 2. PLAN_READY hook
        plan_ctx = HookContext(event=HookEvent.PLAN_READY, goal=goal, plan=plan)
        plan_resp = await self._hooks.fire(HookEvent.PLAN_READY, plan_ctx)
        if plan_resp.decision == HookDecision.ABORT:
            return RunResult(
                goal=goal,
                status=RunStatus.ABORTED,
                plan=plan,
                error="Aborted at PLAN_READY hook",
                duration_ms=_elapsed_ms(wall_start),
                human_override=plan_resp.note or None,
            )

        # 3. Execute
        guard = LoopGuard(
            max_steps=self._max_steps,
            window=self._loop_window,
            max_repeats=3,
        )
        executed: list[StepResult] = []
        remaining_steps = list(plan.steps)

        while remaining_steps:
            step = remaining_steps.pop(0)
            result = await self._run_step(step, page, guard, goal, plan, executed)

            if result is None:
                # Loop violation already handled — status returned externally
                break

            if not result.success:
                # Consult the hook BEFORE recording the result so that RETRY /
                # OVERRIDE decisions can discard the interim failure and re-run
                # the step.  Only CONTINUE and ABORT record the failure.
                fail_ctx = HookContext(
                    event=HookEvent.STEP_FAILED,
                    goal=goal,
                    plan=plan,
                    current_step=step,
                    step_result=result,
                    error=result.error,
                )
                resp = await self._hooks.fire(HookEvent.STEP_FAILED, fail_ctx)

                if resp.decision == HookDecision.RETRY:
                    # Discard interim failure; step will be re-executed next iteration
                    remaining_steps.insert(0, step)
                    continue

                if resp.decision == HookDecision.OVERRIDE and resp.override_value is not None:
                    # Discard interim failure; patched step will be re-executed
                    overridden = deepcopy(step)
                    overridden.value = resp.override_value
                    remaining_steps.insert(0, overridden)
                    continue

                # ABORT or CONTINUE — record the failure
                executed.append(result)

                if resp.decision == HookDecision.ABORT:
                    return RunResult(
                        goal=goal,
                        status=RunStatus.ABORTED,
                        plan=plan,
                        steps_executed=executed,
                        error=result.error,
                        duration_ms=_elapsed_ms(wall_start),
                        human_override=resp.note or None,
                    )

                # CONTINUE — try LLM replan for remaining steps
                if self._enable_replan and remaining_steps:
                    replanned = await self._replan(
                        goal, page, executed, step, result.error or ""
                    )
                    if replanned:
                        remaining_steps = replanned
                # (if replan fails or disabled, just skip this step and continue)

            else:
                executed.append(result)

        # Determine overall status
        failed = [r for r in executed if not r.success]
        status = RunStatus.COMPLETED if not failed else RunStatus.FAILED
        error: str | None = failed[-1].error if failed else None

        # RUN_COMPLETE hook (fire & forget the response)
        complete_ctx = HookContext(
            event=HookEvent.RUN_COMPLETE,
            goal=goal,
            plan=plan,
            error=error,
            metadata={"steps_executed": len(executed), "failed_count": len(failed)},
        )
        await self._hooks.fire(HookEvent.RUN_COMPLETE, complete_ctx)

        return RunResult(
            goal=goal,
            status=status,
            plan=plan,
            steps_executed=executed,
            error=error,
            duration_ms=_elapsed_ms(wall_start),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _run_step(
        self,
        step: Step,
        page: "Page",
        guard: LoopGuard,
        goal: str,
        plan: Plan,
        executed: list[StepResult],
    ) -> StepResult | None:
        """Execute a single step with retry logic and loop guard.

        Returns ``None`` only when a :class:`LoopViolation` is raised and the
        hook decides to abort (caller should break the loop).
        """
        url = page.url

        # STEP_ABOUT_TO_RUN hook (informational — default is CONTINUE)
        pre_ctx = HookContext(
            event=HookEvent.STEP_ABOUT_TO_RUN,
            goal=goal,
            plan=plan,
            current_step=step,
        )
        pre_resp = await self._hooks.fire(HookEvent.STEP_ABOUT_TO_RUN, pre_ctx)
        if pre_resp.decision == HookDecision.ABORT:
            # Synthesize a failure result
            return StepResult(
                step=step,
                success=False,
                error="Aborted at STEP_ABOUT_TO_RUN hook",
            )

        # Loop guard
        try:
            guard.record(step.action.value, step.target, url)
        except LoopViolation as exc:
            is_budget = "budget" in str(exc)
            event = HookEvent.MAX_STEPS_EXCEEDED if is_budget else HookEvent.LOOP_DETECTED
            loop_ctx = HookContext(
                event=event,
                goal=goal,
                plan=plan,
                current_step=step,
                error=str(exc),
            )
            resp = await self._hooks.fire(event, loop_ctx)
            result = StepResult(
                step=step,
                success=False,
                error=str(exc),
            )
            if resp.decision == HookDecision.ABORT:
                return result  # caller will see failure and break
            # CONTINUE means skip this step
            return result

        # Execute with retries
        last_result: StepResult | None = None
        for attempt in range(1, self._max_retries + 2):  # +2 so attempt 1 = first try
            last_result = await self._executor.execute_step(step, page)
            last_result = last_result.model_copy(update={"attempt": attempt})
            if last_result.success:
                return last_result
            if attempt <= self._max_retries:
                # brief retry — no hook (hook is fired by caller on final failure)
                continue
        return last_result  # type: ignore[return-value]

    async def _replan(
        self,
        goal: str,
        page: "Page",
        completed: list[StepResult],
        failed_step: Step,
        error: str,
    ) -> list[Step] | None:
        """Ask the LLM to generate revised remaining steps after a failure."""
        try:
            from pydantic import BaseModel

            class _Resp(BaseModel):
                steps: list[Step]

            url = page.url
            dom_ctx = await get_dom_context(page)
            prompt_text = prompts.render(
                "replan.j2",
                goal=goal,
                completed_steps=completed,
                failed_step=failed_step,
                error=error,
                url=url,
                dom_context=dom_ctx,
            )
            response = await self._ollama.generate_structured(
                prompt=prompt_text,
                schema=_Resp,
                model=self._model,
                temperature=0.1,
            )
            return response.steps or None
        except Exception:
            return None


# ── Helper ────────────────────────────────────────────────────────────────────

def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000
