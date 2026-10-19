from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path

from app.repositories import bug_repository, run_repository, test_repository
from app.schemas.test_case import ActionType, Step, TargetLocator, TestCase
from app.services.run_pipeline import RunPipeline

router = APIRouter(prefix="/tests", tags=["tests"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_test_case(row) -> TestCase:
    return TestCase(
        id=row["id"],
        run_id=row["run_id"],
        title=row["title"],
        objective=row["objective"] or "",
        generation_mode=row["generation_mode"],
        preconditions=json.loads(row["preconditions"] or "[]"),
        steps=[
            Step(
                action=ActionType(s["action"]),
                target=TargetLocator(**s["target"]) if s.get("target") else None,
                value=s.get("value"),
                assertion_value=s.get("assertion_value"),
                attribute=s.get("attribute"),
                description=s.get("description", ""),
            )
            for s in json.loads(row["steps"] or "[]")
        ],
        target_elements=[
            TargetLocator(**t) for t in json.loads(row["target_elements"] or "[]")
        ],
        test_data=json.loads(row["test_data"] or "{}"),
        expected_outcome=row["expected_outcome"],
        priority=row["priority"],
        risk_level=row["risk_level"],
        required_assertions=json.loads(row["required_assertions"] or "[]"),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_result_dict(row) -> dict:
    d = dict(row)
    for field in ("console_errors", "network_errors", "logs"):
        try:
            d[field] = json.loads(d[field] or "[]")
        except json.JSONDecodeError:
            d[field] = []
    return d


@router.get("/{test_id}")
async def get_test(test_id: str = Path(...)):
    case_row = test_repository.get_test_case(test_id)
    if not case_row:
        raise HTTPException(status_code=404, detail="test case not found")
    result_row = test_repository.get_test_result_by_test(test_id)
    step_rows = []
    if result_row:
        step_rows = test_repository.list_step_results(result_row["id"])
    return {
        "test_case": {
            "id": case_row["id"],
            "title": case_row["title"],
            "objective": case_row["objective"],
            "generation_mode": case_row["generation_mode"],
            "priority": case_row["priority"],
            "risk_level": case_row["risk_level"],
            "expected_outcome": case_row["expected_outcome"],
            "steps": json.loads(case_row["steps"] or "[]"),
        },
        "result": _row_to_result_dict(result_row) if result_row else None,
        "steps": [dict(r) for r in step_rows],
    }


@router.post("/{test_id}/rerun")
async def rerun_test(test_id: str = Path(...), background: BackgroundTasks = None):
    case_row = test_repository.get_test_case(test_id)
    if not case_row:
        raise HTTPException(status_code=404, detail="test case not found")
    run_row = run_repository.get_run(case_row["run_id"])
    if not run_row:
        raise HTTPException(status_code=404, detail="run not found")

    case = _row_to_test_case(case_row)
    from app.schemas.test_result import new_result_id

    result_id = new_result_id()
    test_repository.create_test_result(
        result_id=result_id,
        test_id=test_id,
        run_id=case.run_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
    )

    async def _background() -> None:
        await RunPipeline().execute_single_test(
            case, case.run_id, run_row["target_url"], result_id
        )

    background.add_task(_background)
    return {"test_id": test_id, "result_id": result_id, "status": "pending"}
