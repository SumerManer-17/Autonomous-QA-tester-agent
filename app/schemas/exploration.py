"""Schemas for browser exploration results."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.test_case import TargetLocator


class DiscoveredPage(BaseModel):
    url: str
    title: str | None = None
    depth: int = 0
    screenshot_path: str | None = None
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    elements: list[TargetLocator] = Field(default_factory=list)


class ExplorationResult(BaseModel):
    target_url: str
    pages: list[DiscoveredPage] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None


def new_page_id() -> str:
    return "page_" + uuid4().hex[:12]
