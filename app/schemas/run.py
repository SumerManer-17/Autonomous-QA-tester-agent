"""Schemas for test runs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LLMMode(str, Enum):
    DISABLED = "disabled"
    OPENAI = "openai"
    GROQ = "groq"
    OLLAMA = "ollama"


class RunCreate(BaseModel):
    target_url: str = Field(..., description="Target application URL (localhost/allowed hosts).")
    goal: str = Field(..., min_length=5, max_length=2000, description="Natural-language testing goal.")
    llm_mode: LLMMode = Field(default=LLMMode.DISABLED, description="LLM-assisted mode (disabled by default).")

    @model_validator(mode="after")
    def _check_goal_not_empty(self) -> "RunCreate":
        if not self.goal or not self.goal.strip():
            raise ValueError("goal must not be empty")
        return self


class RunResponse(BaseModel):
    id: str
    target_url: str
    goal: str
    status: RunStatus
    llm_mode: LLMMode
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class RunListItem(BaseModel):
    id: str
    target_url: str
    status: RunStatus
    created_at: datetime
    test_count: int = 0
    passed: int = 0
    failed: int = 0

    model_config = {"from_attributes": True}


def new_run_id() -> str:
    return "run_" + uuid4().hex
