"""Tests for agent Pydantic models and the intent→Step heuristic."""

import pytest
from oapw.agents.models import (
    Step, StepAction, Plan, LocatorCandidate, LocatorStrategy,
    ExtractionResult, AssertionResult, StepResult,
)
from oapw.core.ai_page import _intent_to_step


# ── Step model ────────────────────────────────────────────────────────────────

class TestStep:
    def test_valid_step(self):
        s = Step(action=StepAction.CLICK, target="submit button", description="Click submit")
        assert s.action == StepAction.CLICK
        assert s.value is None

    def test_fill_step(self):
        s = Step(action=StepAction.FILL, target="email input", value="a@b.com", description="Fill email")
        assert s.value == "a@b.com"

    def test_action_enum_values(self):
        assert StepAction.CLICK.value == "click"
        assert StepAction.NAVIGATE.value == "navigate"
        assert StepAction.EXTRACT.value == "extract"


# ── Plan model ────────────────────────────────────────────────────────────────

class TestPlan:
    def test_plan_roundtrip(self):
        steps = [
            Step(action=StepAction.NAVIGATE, value="https://example.com", description="Go"),
            Step(action=StepAction.CLICK, target="login button", description="Click login"),
        ]
        plan = Plan(goal="Log in", steps=steps)
        dumped = plan.model_dump()
        restored = Plan.model_validate(dumped)
        assert len(restored.steps) == 2
        assert restored.steps[0].action == StepAction.NAVIGATE


# ── LocatorCandidate ──────────────────────────────────────────────────────────

class TestLocatorCandidate:
    def test_css_candidate(self):
        c = LocatorCandidate(strategy=LocatorStrategy.CSS, value="button#submit", confidence=0.9)
        assert c.strategy == LocatorStrategy.CSS
        assert c.role is None

    def test_role_candidate(self):
        c = LocatorCandidate(strategy=LocatorStrategy.ROLE, value="", role="button", name="Sign in", confidence=0.95)
        assert c.role == "button"
        assert c.name == "Sign in"

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            LocatorCandidate(strategy=LocatorStrategy.CSS, value="x", confidence=1.5)


# ── ExtractionResult ─────────────────────────────────────────────────────────

class TestExtractionResult:
    def test_number_result(self):
        r = ExtractionResult(value=49999, type="number", confidence=0.98)
        assert r.value == 49999
        assert r.type == "number"

    def test_null_result(self):
        r = ExtractionResult(value=None, confidence=0.0)
        assert r.value is None


# ── AssertionResult ───────────────────────────────────────────────────────────

class TestAssertionResult:
    def test_pass(self):
        r = AssertionResult(passed=True, confidence=0.95, explanation="Cart shows 1 item")
        assert r.passed is True

    def test_fail(self):
        r = AssertionResult(passed=False, confidence=0.9, explanation="No items in cart")
        assert r.passed is False


# ── Intent → Step heuristic ──────────────────────────────────────────────────

class TestIntentToStep:
    def test_click_intent(self):
        s = _intent_to_step("Click the Sign in button")
        assert s.action == StepAction.CLICK
        assert "Sign in" in (s.target or "")

    def test_fill_with_value(self):
        s = _intent_to_step("Fill the email input with 'user@example.com'")
        assert s.action == StepAction.FILL
        assert s.value == "user@example.com"

    def test_navigate_with_url(self):
        s = _intent_to_step("Navigate to https://example.com/login")
        assert s.action == StepAction.NAVIGATE
        assert s.value == "https://example.com/login"
        assert s.target is None

    def test_select_intent(self):
        s = _intent_to_step("Select 'India' from the country dropdown")
        assert s.action == StepAction.SELECT

    def test_hover_intent(self):
        s = _intent_to_step("Hover over the menu item")
        assert s.action == StepAction.HOVER

    def test_unknown_defaults_to_click(self):
        s = _intent_to_step("the submit button")
        assert s.action == StepAction.CLICK

    def test_description_preserved(self):
        intent = "Click the logout button"
        s = _intent_to_step(intent)
        assert s.description == intent
