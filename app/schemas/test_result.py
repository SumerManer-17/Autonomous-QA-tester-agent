"""Schemas for test execution results and failures."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    INCONCLUSIVE = "inconclusive"


class FailureCategory(str, Enum):
    ASSERTION_FAILURE = "application_assertion_failure"
    ELEMENT_NOT_FOUND = "element_not_found"
    ELEMENT_AMBIGUOUS = "element_ambiguous"
    NAVIGATION_FAILURE = "navigation_failure"
    APPLICATION_HTTP_ERROR = "application_http_error"
    JAVASCRIPT_CONSOLE_ERROR = "javascript_console_error"
    FAILED_NETWORK_REQUEST = "failed_network_request"
    TIMEOUT = "timeout"
    TEST_SETUP_FAILURE = "test_setup_failure"
    BROWSER_INFRASTRUCTURE_FAILURE = "browser_infrastructure_failure"
    INCONCLUSIVE = "inconclusive"


class StepResult(BaseModel):
    step_index: int
    action: str
    target: dict[str, Any] | None = None
    status: TestStatus
    error: str | None = None
    duration_ms: int | None = None
    screenshot_path: str | None = None


class TestResult(BaseModel):
    id: str
    test_id: str
    run_id: str
    status: TestStatus
    error_message: str | None = None
    failure_category: FailureCategory | None = None
    confidence: str | None = Field(
        default=None, description="low | medium | high."
    )
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    step_results: list[StepResult] = Field(default_factory=list)
    screenshot_path: str | None = None
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)

    def mark_step(self, step_index: int, action: str, status: TestStatus, **kwargs) -> None:
        self.step_results.append(
            StepResult(
                step_index=step_index,
                action=action,
                status=status,
                **kwargs,
            )
        )


def new_result_id() -> str:
    return "result_" + uuid4().hex[:12]
