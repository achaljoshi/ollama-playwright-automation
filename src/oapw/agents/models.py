"""Shared Pydantic models for the agent layer."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class StepAction(str, Enum):
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    HOVER = "hover"
    NAVIGATE = "navigate"
    WAIT = "wait"
    PRESS = "press"
    SCROLL = "scroll"
    ASSERT = "assert"
    EXTRACT = "extract"


class Step(BaseModel):
    action: StepAction
    target: str | None = Field(None, description="Intent description of the element to interact with")
    value: str | None = Field(None, description="Value to fill / URL to navigate to / key to press")
    description: str = Field(..., description="Human-readable step description")


class Plan(BaseModel):
    goal: str
    steps: list[Step]
    estimated_duration_s: float = Field(default=0.0)


class LocatorStrategy(str, Enum):
    CSS = "css"
    ROLE = "role"
    TEXT = "text"
    LABEL = "label"
    PLACEHOLDER = "placeholder"
    TESTID = "testid"


class LocatorCandidate(BaseModel):
    strategy: LocatorStrategy
    value: str = Field(..., description="CSS selector / text / placeholder / testid string")
    role: str | None = Field(None, description="ARIA role — only for strategy=role")
    name: str | None = Field(None, description="Accessible name — only for strategy=role")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class LocatorProposal(BaseModel):
    locators: list[LocatorCandidate]
    reasoning: str = ""


class ExtractionResult(BaseModel):
    value: Any = None
    type: Literal["string", "number", "boolean", "list"] = "string"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class AssertionResult(BaseModel):
    passed: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    explanation: str = ""


class StepResult(BaseModel):
    step: Step
    success: bool
    error: str | None = None
    extracted_value: Any = None
    locator_used: str | None = None
    duration_ms: float = 0.0
