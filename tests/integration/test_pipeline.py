"""Integration tests for the full testing pipeline (explore -> generate -> execute -> report)."""

import json
from datetime import datetime, timezone

import pytest

from app.services.run_pipeline import RunPipeline

GOAL = (
    "Verify that a user can register, log in, search for a hotel, select a room, "
    "and complete the booking form. Check input validation and error handling."
)


@pytest.mark.asyncio
async def test_clean_run_all_pass(run_pipeline, no_defects):
    run_id = "run_clean"
    await run_pipeline.execute_run(run_id, "http://localhost:3000", GOAL, "disabled")

    from app.repositories import run_repository, test_repository

    run = run_repository.get_run(run_id)
    assert run["status"] == "completed"
    summary = json.loads(run["summary"] or "{}")
    assert summary["failed"] == 0
    assert summary["total"] > 0

    results = test_repository.list_test_results_for_run(run_id)
    for row in results:
        assert row["status"] == "passed", row


@pytest.mark.asyncio
async def test_injected_defect_is_detected(run_pipeline, invalid_email_defect):
    run_id = "run_defect"
    await run_pipeline.execute_run(run_id, "http://localhost:3000", GOAL, "disabled")

    from app.repositories import bug_repository, run_repository, test_repository

    run = run_repository.get_run(run_id)
    assert run["status"] == "completed"
    summary = json.loads(run["summary"] or "{}")
    assert summary["failed"] == 1, summary

    failed = [
        row for row in test_repository.list_test_results_for_run(run_id) if row["status"] == "failed"
    ]
    assert len(failed) == 1
    assert failed[0]["failure_category"] == "application_assertion_failure"

    # The same defect key is deduplicated across runs, so the report may live
    # under an earlier run. What matters is that a report exists for the key.
    from app.repositories.bug_repository import find_bug_by_dedup_key

    bug_key = "application_assertion_failure:reject-invalid-registration-email"
    bug = find_bug_by_dedup_key(bug_key)
    assert bug is not None, f"no bug report for dedup key {bug_key}"
    assert bug["severity"] == "critical"
    assert bug["confidence"].startswith("high")
    assert bug["screenshot_path"] is not None
    assert "registration" in bug["title"].lower() or "email" in bug["title"].lower()
    assert bug["screenshot_path"] is not None
    assert "registration" in bug["title"].lower() or "email" in bug["title"].lower()


@pytest.mark.asyncio
async def test_rerun_after_fix_passes(run_pipeline, invalid_email_defect):
    """Detect the defect, disable it, rerun the failing test -> it must pass."""
    run_id = "run_rerun"
    await run_pipeline.execute_run(run_id, "http://localhost:3000", GOAL, "disabled")

    from app.repositories import test_repository

    failed = [
        row
        for row in test_repository.list_test_results_for_run(run_id)
        if row["status"] == "failed"
    ][0]
    import json

    from app.schemas.test_case import ActionType, Step, TargetLocator, TestCase

    row = test_repository.get_test_case(failed["test_id"])
    test_case = TestCase(
        id=row["id"],
        run_id=row["run_id"],
        title=row["title"],
        objective=row["objective"],
        generation_mode=row["generation_mode"],
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
        expected_outcome=row["expected_outcome"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )

    # Simulate the fix: disable the injected defect.
    import json, urllib.request

    body = json.dumps({"defects": []}).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:3000/__demo/defects",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200

    # Rerun via the pipeline (mirrors POST /api/v1/tests/{test_id}/rerun,
    # which inserts a pending result row first).
    result_id = "rerun_res"
    test_repository.create_test_result(
        result_id, test_case.id, run_id, "pending", datetime.now(timezone.utc)
    )
    await run_pipeline.execute_single_test(
        test_case, run_id, "http://localhost:3000", result_id
    )

    result = test_repository.get_test_result(result_id)
    assert result["status"] == "passed", result["error_message"]
