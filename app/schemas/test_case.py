"""Schemas for generated test cases and their execution steps."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT_OPTION = "select_option"
    CHECK = "check"
    UNCHECK = "uncheck"
    ASSERT_VISIBLE = "assert_visible"
    ASSERT_TEXT = "assert_text"
    ASSERT_URL = "assert_url"
    ASSERT_ENABLED = "assert_enabled"
    ASSERT_DISABLED = "assert_disabled"
    ASSERT_COUNT = "assert_count"
    ASSERT_ATTRIBUTE = "assert_attribute"

    @classmethod
    def supported(cls) -> set[str]:
        return {item.value for item in cls}


class TargetLocator(BaseModel):
    """Description of a UI element target, resolved by the executor at runtime."""

    role: str | None = Field(
        default=None,
        description="ARIA role (e.g. textbox, button, link, combobox).",
    )
    name: str | None = Field(default=None, description="Accessible name of the element.")
    label: str | None = Field(default=None, description="Associated form label text.")
    placeholder: str | None = Field(
        default=None, description="Input placeholder text."
    )
    test_id: str | None = Field(default=None, description="data-testid value.")
    text: str | None = Field(default=None, description="Visible text match.")
    index: int | None = Field(
        default=None, description="When several elements match, use this 0-based index deterministically."
    )

    def has_any(self) -> bool:
        return any(
            getattr(self, field) is not None
            for field in ("role", "name", "label", "placeholder", "test_id", "text")
        )

    @model_validator(mode="after")
    def _require_something(self) -> "TargetLocator":
        if not self.has_any():
            raise ValueError("TargetLocator must specify at least one attribute")
        return self

    def describe(self) -> str:
        parts = [
            f"{k}={v!r}"
            for k, v in {
                "role": self.role,
                "name": self.name,
                "label": self.label,
                "placeholder": self.placeholder,
                "testId": self.test_id,
                "text": self.text,
                "index": self.index,
            }.items()
            if v is not None
        ]
        return ", ".join(parts) or "unspecified"


class Step(BaseModel):
    """A single executable step within a test case."""

    action: ActionType
    target: TargetLocator | None = Field(
        default=None, description="Target element (omitted for navigate/assert_url)."
    )
    value: str | None = Field(default=None, description="Value for fill/select/check steps.")
    assertion_value: str | None = Field(
        default=None, description="Expected value for assertion steps."
    )
    attribute: str | None = Field(
        default=None, description="Attribute name for assert_attribute steps."
    )
    description: str = Field(default="", description="Human-readable step description.")

    @model_validator(mode="after")
    def _validate_step_shape(self) -> "Step":
        if self.action == ActionType.NAVIGATE:
            if not self.value:
                raise ValueError("navigate step requires a value (URL).")
        if self.action in {
            ActionType.CLICK,
            ActionType.FILL,
            ActionType.SELECT_OPTION,
            ActionType.CHECK,
            ActionType.UNCHECK,
            ActionType.ASSERT_VISIBLE,
            ActionType.ASSERT_TEXT,
            ActionType.ASSERT_ENABLED,
            ActionType.ASSERT_DISABLED,
            ActionType.ASSERT_ATTRIBUTE,
        } and not self.target:
            raise ValueError(f"{self.action} step requires a target.")
        if self.action == ActionType.ASSERT_COUNT and not self.target:
            raise ValueError("assert_count step requires a target.")
        if self.action == ActionType.ASSERT_TEXT and self.assertion_value is None:
            raise ValueError("assert_text step requires assertion_value.")
        if self.action == ActionType.FILL and self.value is None:
            raise ValueError("fill step requires a value.")
        if self.action in {ActionType.SELECT_OPTION, ActionType.CHECK, ActionType.UNCHECK}:
            if self.value is None:
                raise ValueError(f"{self.action} step requires a value.")
        return self


class TestPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TestRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TestCase(BaseModel):
    id: str
    run_id: str
    title: str
    objective: str
    generation_mode: str = Field(
        default="deterministic",
        description="deterministic | llm_assisted.",
    )
    preconditions: list[str] = Field(default_factory=list)
    steps: list[Step]
    target_elements: list[TargetLocator] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str
    priority: TestPriority = TestPriority.MEDIUM
    risk_level: TestRisk = TestRisk.LOW
    required_assertions: list[str] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _validate_steps(self) -> "TestCase":
        if not self.steps:
            raise ValueError("test case must contain at least one step")
        for step in self.steps:
            if step.action not in ActionType.supported():
                raise ValueError(f"Unsupported action type: {step.action}")
        return self

    def step_descriptions(self) -> list[str]:
        return [
            s.description or f"{s.action} {s.target.describe() if s.target else ''}"
            for s in self.steps
        ]


def new_test_id() -> str:
    return "test_" + uuid4().hex[:12]
