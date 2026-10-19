from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path

from app.core.security import SecurityError, validate_target_url
from app.repositories import bug_repository, run_repository, test_repository
from app.schemas.run import LLMMode, RunCreate, RunListItem, RunResponse, RunStatus, new_run_id
from app.services.run_pipeline import RunPipeline

router = APIRouter(prefix="/runs", tags=["runs"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_run_response(row) -> RunResponse:
    summary = json.loads(row["summary"]) if row["summary"] else None
    return RunResponse(
        id=row["id"],
        target_url=row["target_url"],
        goal=row["goal"],
        status=RunStatus(row["status"]),
        llm_mode=LLMMode(row["llm_mode"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        summary=summary,
    )


def _counts_for_run(run_id: str) -> dict:
    rows = test_repository.list_test_results_for_run(run_id)
    counts = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "inconclusive": 0}
    for row in rows:
        counts["total"] += 1
        status = row["status"]
        if status in counts:
            counts[status] += 1
    return counts


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(payload: RunCreate, background: BackgroundTasks):
    """Create and start a testing run.

    Execution happens in a background task so the API responds immediately;
    poll GET /api/v1/runs/{run_id} for status.
    """
    try:
        validate_target_url(payload.target_url)
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = new_run_id()
    run_repository.create_run(
        run_id=run_id,
        target_url=payload.target_url,
        goal=payload.goal,
        llm_mode=payload.llm_mode.value,
    )
    background.add_task(
        RunPipeline().execute_run,
        run_id,
        payload.target_url,
        payload.goal,
        payload.llm_mode.value,
    )
    return _row_to_run_response(run_repository.get_run(run_id))


@router.get("", response_model=list[RunListItem])
async def list_runs():
    rows = run_repository.list_runs()
    items = []
    for row in rows:
        counts = _counts_for_run(row["id"])
        items.append(
            RunListItem(
                id=row["id"],
                target_url=row["target_url"],
                status=RunStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                **counts,
            )
        )
    return items


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str = Path(...)):
    row = run_repository.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    return _row_to_run_response(row)


@router.get("/{run_id}/tests")
async def get_run_tests(run_id: str = Path(...)):
    if not run_repository.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    cases = test_repository.list_test_cases_for_run(run_id)
    results = test_repository.list_test_results_for_run(run_id)
    latest: dict[str, dict] = {}
    for row in results:
        prev = latest.get(row["test_id"])
        if prev is None or row["started_at"] > prev["started_at"]:
            latest[row["test_id"]] = row

    out = []
    for case in cases:
        case_dict = dict(case)
        for json_field in ("preconditions", "steps", "target_elements", "test_data", "required_assertions"):
            try:
                case_dict[json_field] = json.loads(case_dict[json_field] or "[]")
            except json.JSONDecodeError:
                case_dict[json_field] = []
        result = latest.get(case["id"])
        case_dict["latest_result"] = dict(result) if result else None
        if case_dict["latest_result"]:
            for json_field in ("console_errors", "network_errors", "logs"):
                try:
                    case_dict["latest_result"][json_field] = json.loads(
                        case_dict["latest_result"][json_field] or "[]"
                    )
                except json.JSONDecodeError:
                    case_dict["latest_result"][json_field] = []
        out.append(case_dict)
    return out


@router.get("/{run_id}/bugs")
async def get_run_bugs(run_id: str = Path(...)):
    if not run_repository.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    rows = bug_repository.list_bugs_for_run(run_id)
    return [_bug_row_to_dict(row) for row in rows]


@router.get("/{run_id}/artifacts")
async def get_run_artifacts(run_id: str = Path(...)):
    if not run_repository.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    from app.repositories.database import query_all

    rows = query_all(
        "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at DESC", (run_id,)
    )
    return [
        {
            "id": row["id"],
            "type": row["type"],
            "path": row["path"],
            "url": row["url"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _bug_row_to_dict(row) -> dict:
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

