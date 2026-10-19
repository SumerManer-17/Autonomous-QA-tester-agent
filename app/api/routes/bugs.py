from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Path

from app.repositories import bug_repository

router = APIRouter(prefix="/bugs", tags=["bugs"])


@router.get("/{bug_id}")
async def get_bug(bug_id: str = Path(...)):
    row = bug_repository.get_bug_report(bug_id)
    if not row:
        raise HTTPException(status_code=404, detail="bug report not found")
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "test_id": row["test_id"],
        "title": row["title"],
        "severity": row["severity"],
        "priority": row["priority"],
        "environment": row["environment"],
        "browser": row["browser"],
        "browser_version": row["browser_version"],
        "target_url": row["target_url"],
        "reproduction_steps": json.loads(row["reproduction_steps"] or "[]"),
        "preconditions": json.loads(row["preconditions"] or "[]"),
        "test_data": json.loads(row["test_data"] or "{}"),
        "expected_result": row["expected_result"],
        "actual_result": row["actual_result"],
        "failure_category": row["failure_category"],
        "timestamp": row["timestamp"],
        "screenshot_path": row["screenshot_path"],
        "console_errors": json.loads(row["console_errors"] or "[]"),
        "network_requests": json.loads(row["network_requests"] or "[]"),
        "execution_logs": json.loads(row["execution_logs"] or "[]"),
        "probable_cause": row["probable_cause"],
        "confidence": row["confidence"],
        "limitations": row["limitations"],
        "dedup_key": row["dedup_key"],
        "created_at": row["created_at"],
    }
