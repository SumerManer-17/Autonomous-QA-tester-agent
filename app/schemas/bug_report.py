"""Schemas for reproducible bug reports."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IMMEDIATE = "immediate"


class BugReport(BaseModel):
    id: str
    run_id: str
    test_id: str
    title: str
    severity: Severity = Severity.MEDIUM
    priority: Priority = Priority.MEDIUM
    environment: str
    browser: str
    browser_version: str
    target_url: str
    reproduction_steps: list[str]
    preconditions: list[str] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)
    expected_result: str
    actual_result: str
    failure_category: str
    timestamp: datetime
    screenshot_path: str | None = None
    console_errors: list[str] = Field(default_factory=list)
    network_requests: list[str] = Field(default_factory=list)
    execution_logs: list[str] = Field(default_factory=list)
    probable_cause: str | None = None
    confidence: str | None = None
    limitations: str | None = None
    dedup_key: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


def new_bug_id() -> str:
    return "bug_" + uuid4().hex[:12]
