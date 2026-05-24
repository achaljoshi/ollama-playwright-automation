"""Tests for Phase 7 — AgentRunner, LoopGuard, and HookRegistry.

All Playwright and Ollama calls are mocked — no network required.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from oapw.agents.models import (
    Plan, RunResult, RunStatus, Step, StepAction, StepResult,
)
from oapw.agents.loop_guard import LoopGuard, LoopViolation
from oapw.agents.hooks import (
    HookContext, HookDecision, HookEvent, HookRegistry, HookResponse,
    SilentHook,
)
from oapw.agents.runner import AgentRunner


# ── Helpers ───────────────────────────────────────────────────────────────────

def _step(action: StepAction = StepAction.CLICK, target: str = "button", description: str = "click it") -> Step:
    return Step(action=action, target=target, description=description)


def _success_result(step: Step) -> StepResult:
    return StepResult(step=step, success=True)


def _fail_result(step: Step, error: str = "Element not found") -> StepResult:
    return StepResult(step=step, success=False, error=error)


def _make_plan(*steps: Step) -> Plan:
    return Plan(goal="test goal", steps=list(steps))


def _make_page(url: str = "http://localhost:3000") -> MagicMock:
    page = MagicMock()
    page.url = url
    page.goto = AsyncMock()
    return page


def _make_planner(plan: Plan) -> MagicMock:
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    return planner


def _make_executor(results: list[StepResult]) -> MagicMock:
    executor = MagicMock()
    executor.execute_step = AsyncMock(side_effect=results)
    return executor


# ── LoopGuard ────────────────────────────────────────────────────────────────

class TestLoopGuard:
    def test_records_step_without_violation(self):
        guard = LoopGuard(max_steps=10)
        guard.record("click", "button", "http://x")
        assert guard.steps_recorded == 1

    def test_budget_exceeded_raises(self):
        guard = LoopGuard(max_steps=3)
        guard.record("click", "a", "http://x")
        guard.record("click", "b", "http://x")
        guard.record("click", "c", "http://x")
        with pytest.raises(LoopViolation, match="budget"):
            guard.record("click", "d", "http://x")

    def test_cycle_detected_raises(self):
        # max_repeats=3 means: raise when the same key appears 3 times in the window.
        # After 2 inserts, the 3rd insert reaches count==3 and raises.
        guard = LoopGuard(max_steps=100, window=6, max_repeats=3)
        guard.record("click", "submit", "http://x/login")
        guard.record("click", "submit", "http://x/login")
        with pytest.raises(LoopViolation, match="Cycle"):
            guard.record("click", "submit", "http://x/login")

    def test_different_urls_not_a_cycle(self):
        guard = LoopGuard(max_steps=100, window=6, max_repeats=3)
        for i in range(3):
            guard.record("click", "submit", f"http://x/page{i}")
        # No exception: URL differs each time
        guard.record("click", "submit", "http://x/page3")
        assert guard.steps_recorded == 4

    def test_different_actions_not_a_cycle(self):
        guard = LoopGuard(max_steps=100, window=4, max_repeats=3)
        guard.record("click", "btn", "http://x")
        guard.record("fill", "btn", "http://x")
        guard.record("hover", "btn", "http://x")
        # Only one of each — no cycle
        guard.record("click", "btn", "http://x")  # second click, but only 1 in window if 4 steps

    def test_remaining_budget_decrements(self):
        guard = LoopGuard(max_steps=10)
        assert guard.remaining_budget == 10
        guard.record("click", "x", "http://a")
        assert guard.remaining_budget == 9

    def test_reset_clears_state(self):
        guard = LoopGuard(max_steps=3)
        guard.record("click", "a", "http://x")
        guard.record("click", "b", "http://x")
        guard.reset()
        assert guard.steps_recorded == 0
        assert guard.remaining_budget == 3

    def test_loop_violation_str_repr(self):
        exc = LoopViolation("budget exceeded: 51 > 50")
        assert "budget" in str(exc)

    def test_window_slides_old_entries_out(self):
        """Entries older than the window should not count toward cycle detection."""
        guard = LoopGuard(max_steps=100, window=4, max_repeats=3)
        # Insert the "dangerous" step 2 times, then 4 other steps to push them out
        guard.record("click", "submit", "http://x")
        guard.record("click", "submit", "http://x")
        for i in range(4):  # push both dangerous entries out of the window
            guard.record("fill", f"field{i}", "http://x")
        # Now re-insert "dangerous" step — window has no prior matches
        guard.record("click", "submit", "http://x")  # should not raise


# ── HookRegistry ─────────────────────────────────────────────────────────────

class TestHookRegistry:
    @pytest.mark.asyncio
    async def test_default_returns_continue(self):
        registry = HookRegistry()
        ctx = HookContext(
            event=HookEvent.STEP_FAILED,
            goal="g",
            plan=_make_plan(),
        )
        resp = await registry.fire(HookEvent.STEP_FAILED, ctx)
        assert resp.decision == HookDecision.CONTINUE

    @pytest.mark.asyncio
    async def test_registered_handler_called(self):
        registry = HookRegistry()
        called_with: list[HookContext] = []

        async def handler(ctx: HookContext) -> HookResponse:
            called_with.append(ctx)
            return HookResponse(decision=HookDecision.ABORT)

        registry.register(HookEvent.STEP_FAILED, handler)
        ctx = HookContext(event=HookEvent.STEP_FAILED, goal="g", plan=_make_plan())
        resp = await registry.fire(HookEvent.STEP_FAILED, ctx)

        assert resp.decision == HookDecision.ABORT
        assert len(called_with) == 1

    @pytest.mark.asyncio
    async def test_unregister_falls_back_to_default(self):
        registry = HookRegistry()

        async def handler(ctx: HookContext) -> HookResponse:
            return HookResponse(decision=HookDecision.ABORT)

        registry.register(HookEvent.STEP_FAILED, handler)
        registry.unregister(HookEvent.STEP_FAILED)
        ctx = HookContext(event=HookEvent.STEP_FAILED, goal="g", plan=_make_plan())
        resp = await registry.fire(HookEvent.STEP_FAILED, ctx)
        assert resp.decision == HookDecision.CONTINUE

    @pytest.mark.asyncio
    async def test_has_handler_returns_false_before_register(self):
        registry = HookRegistry()
        assert not registry.has_handler(HookEvent.PLAN_READY)

    @pytest.mark.asyncio
    async def test_has_handler_returns_true_after_register(self):
        registry = HookRegistry()
        registry.register(HookEvent.PLAN_READY, SilentHook())
        assert registry.has_handler(HookEvent.PLAN_READY)

    @pytest.mark.asyncio
    async def test_set_default_replaces_silent_default(self):
        registry = HookRegistry()

        async def my_default(ctx: HookContext) -> HookResponse:
            return HookResponse(decision=HookDecision.RETRY)

        registry.set_default(my_default)
        ctx = HookContext(event=HookEvent.RUN_COMPLETE, goal="g", plan=_make_plan())
        resp = await registry.fire(HookEvent.RUN_COMPLETE, ctx)
        assert resp.decision == HookDecision.RETRY


# ── SilentHook ───────────────────────────────────────────────────────────────

class TestSilentHook:
    @pytest.mark.asyncio
    async def test_always_continue(self):
        hook = SilentHook()
        ctx = HookContext(event=HookEvent.STEP_FAILED, goal="g", plan=_make_plan())
        resp = await hook(ctx)
        assert resp.decision == HookDecision.CONTINUE


# ── RunResult ─────────────────────────────────────────────────────────────────

class TestRunResult:
    def test_ok_when_completed(self):
        r = RunResult(goal="g", status=RunStatus.COMPLETED, plan=_make_plan())
        assert r.ok is True

    def test_not_ok_when_failed(self):
        r = RunResult(goal="g", status=RunStatus.FAILED, plan=_make_plan())
        assert r.ok is False

    def test_failed_steps_filters_correctly(self):
        plan = _make_plan(_step(), _step())
        s1 = _step(description="step 1")
        s2 = _step(description="step 2")
        r = RunResult(
            goal="g",
            status=RunStatus.FAILED,
            plan=plan,
            steps_executed=[
                StepResult(step=s1, success=True),
                StepResult(step=s2, success=False, error="boom"),
            ],
        )
        assert len(r.failed_steps) == 1
        assert r.failed_steps[0].error == "boom"

    def test_empty_steps_executed_by_default(self):
        r = RunResult(goal="g", status=RunStatus.COMPLETED, plan=_make_plan())
        assert r.steps_executed == []


# ── AgentRunner ───────────────────────────────────────────────────────────────

class TestAgentRunner:
    def _make_runner(
        self,
        plan: Plan,
        results: list[StepResult],
        hooks: HookRegistry | None = None,
        max_retries: int = 0,
        enable_replan: bool = False,
    ) -> tuple[AgentRunner, MagicMock, MagicMock]:
        planner = _make_planner(plan)
        executor = _make_executor(results)
        runner = AgentRunner(
            planner=planner,
            executor=executor,
            hooks=hooks or HookRegistry(),
            max_steps=50,
            max_retries=max_retries,
            loop_window=6,
            enable_replan=enable_replan,
        )
        return runner, planner, executor

    @pytest.mark.asyncio
    async def test_successful_run_returns_completed(self):
        step = _step()
        plan = _make_plan(step)
        runner, _, _ = self._make_runner(plan, [_success_result(step)])
        result = await runner.run("test goal", _make_page())
        assert result.status == RunStatus.COMPLETED
        assert result.ok

    @pytest.mark.asyncio
    async def test_successful_run_records_all_steps(self):
        steps = [_step(description=f"step {i}") for i in range(3)]
        plan = _make_plan(*steps)
        runner, _, _ = self._make_runner(
            plan, [_success_result(s) for s in steps]
        )
        result = await runner.run("test goal", _make_page())
        assert len(result.steps_executed) == 3

    @pytest.mark.asyncio
    async def test_failed_step_returns_failed_status(self):
        step = _step()
        plan = _make_plan(step)
        runner, _, _ = self._make_runner(plan, [_fail_result(step)])
        result = await runner.run("test goal", _make_page())
        assert result.status == RunStatus.FAILED
        assert not result.ok

    @pytest.mark.asyncio
    async def test_plan_ready_abort_hook_stops_run(self):
        step = _step()
        plan = _make_plan(step)

        async def abort_handler(ctx: HookContext) -> HookResponse:
            return HookResponse(decision=HookDecision.ABORT, note="human said no")

        hooks = HookRegistry()
        hooks.register(HookEvent.PLAN_READY, abort_handler)
        runner, _, executor = self._make_runner(plan, [_success_result(step)], hooks=hooks)
        result = await runner.run("test goal", _make_page())

        assert result.status == RunStatus.ABORTED
        executor.execute_step.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_step_failed_abort_hook_stops_run(self):
        step = _step()
        plan = _make_plan(step)

        async def abort_on_fail(ctx: HookContext) -> HookResponse:
            return HookResponse(decision=HookDecision.ABORT)

        hooks = HookRegistry()
        hooks.register(HookEvent.STEP_FAILED, abort_on_fail)
        runner, _, _ = self._make_runner(plan, [_fail_result(step)], hooks=hooks)
        result = await runner.run("test goal", _make_page())
        assert result.status == RunStatus.ABORTED

    @pytest.mark.asyncio
    async def test_step_failed_continue_hook_proceeds(self):
        """CONTINUE on step failure: run keeps going, status ends FAILED (failure recorded)."""
        step1 = _step(description="step1")
        step2 = _step(description="step2")
        plan = _make_plan(step1, step2)

        async def continue_handler(ctx: HookContext) -> HookResponse:
            return HookResponse(decision=HookDecision.CONTINUE)

        hooks = HookRegistry()
        hooks.register(HookEvent.STEP_FAILED, continue_handler)
        runner, _, _ = self._make_runner(
            plan,
            [_fail_result(step1), _success_result(step2)],
            hooks=hooks,
        )
        result = await runner.run("goal", _make_page())
        assert len(result.steps_executed) == 2
        assert result.status == RunStatus.FAILED  # failure was recorded

    @pytest.mark.asyncio
    async def test_retry_hook_retries_step(self):
        """RETRY decision re-executes the failed step."""
        step = _step()
        plan = _make_plan(step)
        retry_count = {"n": 0}

        async def retry_once(ctx: HookContext) -> HookResponse:
            if retry_count["n"] == 0:
                retry_count["n"] += 1
                return HookResponse(decision=HookDecision.RETRY)
            return HookResponse(decision=HookDecision.CONTINUE)

        hooks = HookRegistry()
        hooks.register(HookEvent.STEP_FAILED, retry_once)

        executor = MagicMock()
        executor.execute_step = AsyncMock(
            side_effect=[_fail_result(step), _success_result(step)]
        )
        planner = _make_planner(plan)
        runner = AgentRunner(
            planner=planner,
            executor=executor,
            hooks=hooks,
            max_steps=50,
            max_retries=0,
            loop_window=6,
            enable_replan=False,
        )
        result = await runner.run("goal", _make_page())
        assert executor.execute_step.await_count == 2
        assert result.ok

    @pytest.mark.asyncio
    async def test_override_hook_patches_step_value(self):
        """OVERRIDE decision patches the step value and retries."""
        step = _step(action=StepAction.FILL, target="email", description="fill email")
        step.value = "wrong@email"
        plan = _make_plan(step)

        override_seen: list[str] = []

        async def override_handler(ctx: HookContext) -> HookResponse:
            return HookResponse(
                decision=HookDecision.OVERRIDE,
                override_value="correct@email.com",
            )

        async def capture_execute(s: Step, page: object) -> StepResult:
            override_seen.append(s.value or "")
            return _success_result(s)

        hooks = HookRegistry()
        hooks.register(HookEvent.STEP_FAILED, override_handler)

        executor = MagicMock()
        executor.execute_step = AsyncMock(
            side_effect=[
                _fail_result(step, "validation error"),
                _success_result(step),
            ]
        )
        planner = _make_planner(plan)
        runner = AgentRunner(
            planner=planner,
            executor=executor,
            hooks=hooks,
            max_steps=50,
            max_retries=0,
            loop_window=6,
            enable_replan=False,
        )
        result = await runner.run("goal", _make_page())
        assert result.ok
        # Second call should have gotten the overridden step
        second_call_step = executor.execute_step.call_args_list[1][0][0]
        assert second_call_step.value == "correct@email.com"

    @pytest.mark.asyncio
    async def test_loop_guard_fires_loop_detected_hook(self):
        """When LoopGuard raises, LOOP_DETECTED hook is fired."""
        step = _step(description="loop step")
        plan = _make_plan(step)
        loop_events: list[HookEvent] = []

        async def loop_handler(ctx: HookContext) -> HookResponse:
            loop_events.append(ctx.event)
            return HookResponse(decision=HookDecision.CONTINUE)

        hooks = HookRegistry()
        hooks.register(HookEvent.LOOP_DETECTED, loop_handler)
        hooks.register(HookEvent.MAX_STEPS_EXCEEDED, loop_handler)

        runner = AgentRunner(
            planner=_make_planner(plan),
            executor=_make_executor([_success_result(step)]),
            hooks=hooks,
            max_steps=0,  # immediately exceeded
            max_retries=0,
            loop_window=6,
            enable_replan=False,
        )
        result = await runner.run("goal", _make_page())
        assert HookEvent.MAX_STEPS_EXCEEDED in loop_events

    @pytest.mark.asyncio
    async def test_run_complete_hook_always_fires(self):
        step = _step()
        plan = _make_plan(step)
        complete_fired = {"n": 0}

        async def complete_handler(ctx: HookContext) -> HookResponse:
            complete_fired["n"] += 1
            return HookResponse()

        hooks = HookRegistry()
        hooks.register(HookEvent.RUN_COMPLETE, complete_handler)
        runner, _, _ = self._make_runner(plan, [_success_result(step)], hooks=hooks)
        await runner.run("goal", _make_page())
        assert complete_fired["n"] == 1

    @pytest.mark.asyncio
    async def test_duration_ms_is_positive(self):
        step = _step()
        plan = _make_plan(step)
        runner, _, _ = self._make_runner(plan, [_success_result(step)])
        result = await runner.run("goal", _make_page())
        assert result.duration_ms >= 0.0

    @pytest.mark.asyncio
    async def test_multi_step_retries_with_max_retries(self):
        """Step fails twice then succeeds on the third attempt (max_retries=2)."""
        step = _step()
        plan = _make_plan(step)
        executor = MagicMock()
        executor.execute_step = AsyncMock(
            side_effect=[
                _fail_result(step, "err1"),
                _fail_result(step, "err2"),
                _success_result(step),
            ]
        )
        runner = AgentRunner(
            planner=_make_planner(plan),
            executor=executor,
            hooks=HookRegistry(),
            max_steps=50,
            max_retries=2,
            loop_window=6,
            enable_replan=False,
        )
        result = await runner.run("goal", _make_page())
        assert result.ok
        assert executor.execute_step.await_count == 3

    @pytest.mark.asyncio
    async def test_plan_goal_preserved_in_result(self):
        step = _step()
        plan = _make_plan(step)
        runner, _, _ = self._make_runner(plan, [_success_result(step)])
        result = await runner.run("my specific goal", _make_page())
        assert result.goal == "my specific goal"

    @pytest.mark.asyncio
    async def test_error_field_populated_on_failure(self):
        step = _step()
        plan = _make_plan(step)
        runner, _, _ = self._make_runner(plan, [_fail_result(step, "something broke")])
        result = await runner.run("goal", _make_page())
        assert result.error == "something broke"
