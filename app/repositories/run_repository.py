"""Repository for test runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.repositories.database import execute, query_all, query_one


def create_run(run_id: str, target_url: str, goal: str, llm_mode: str) -> None:
    # Idempotent: the API route creates the run row and the background
    # pipeline re-inserts the same row when it starts executing.
    execute(
        """
        INSERT OR IGNORE INTO runs (id, target_url, goal, status, llm_mode, created_at)
        VALUES (?, ?, ?, 'pending', ?, ?)
        """,
        (run_id, target_url, goal, llm_mode, _iso(datetime.now(timezone.utc))),
    )


def get_run(run_id: str):
    return query_one("SELECT * FROM runs WHERE id = ?", (run_id,))


def list_runs(limit: int = 50) -> list:
    return query_all(
        "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
    )


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def update_run_status(
    run_id: str,
    status: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    summary: str | None = None,
) -> None:
    fields = ["status = ?"]
    params: list = [status]
    if started_at is not None:
        fields.append("started_at = ?")
        params.append(_iso(started_at))
    if finished_at is not None:
        fields.append("finished_at = ?")
        params.append(_iso(finished_at))
    if summary is not None:
        fields.append("summary = ?")
        params.append(summary)
    params.append(run_id)
    execute(
        f"UPDATE runs SET {', '.join(fields)} WHERE id = ?",
        tuple(params),
    )


def set_run_summary(run_id: str, summary: str) -> None:
    execute("UPDATE runs SET summary = ? WHERE id = ?", (summary, run_id))
