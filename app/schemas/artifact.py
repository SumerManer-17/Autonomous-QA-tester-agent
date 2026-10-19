"""Schemas for generated artifacts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class ArtifactType(str, Enum):
    SCREENSHOT = "screenshot"
    LOG = "log"
    TRACE = "trace"
    CONSOLE = "console"
    NETWORK = "network"


class Artifact(BaseModel):
    id: str
    run_id: str
    type: ArtifactType
    path: str  # filesystem path
    url: str  # public API URL to retrieve it
    size_bytes: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


def new_artifact_id() -> str:
    return "artifact_" + uuid4().hex[:12]
