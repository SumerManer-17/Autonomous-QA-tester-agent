"""Unit tests for the SQLite repository layer."""

from datetime import datetime, timezone

import pytest

from app.repositories import bug_repository, run_repository, test_repository
from app.repositories.database import init_db


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def test_run_crud():
    init_db()
    run_id = "r_crud"
    run_repository.create_run(run_id, "http://localhost:3000", "goal", "disabled")
    row = run_repository.get_run(run_id)
    assert row is not None
    assert row["status"] == "pending"
    assert row["goal"] == "goal"

    run_repository.update_run_status(run_id, "running", started_at=_utcnow())
    row = run_repository.get_run(run_id)
    assert row["status"] == "running"

    runs = run_repository.list_runs()
    assert any(r["id"] == run_id for r in runs)

    run_repository.set_run_summary(run_id, '{"passed": 1}')
    assert run_repository.get_run(run_id)["summary"] == '{"passed": 1}'


def test_test_case_and_result_crud():
    init_db()
    run_id = "r_tc"
    run_repository.create_run(run_id, "http://localhost:3000", "goal", "disabled")
    test_repository.create_test_case(
        test_id="t_tc",
        run_id=run_id,
        title="Title",
        objective="Obj",
        generation_mode="deterministic",
        priority="high",
        risk_level="high",
        preconditions="[]",
        steps="[]",
        target_elements="[]",
        test_data="{}",
        expected_outcome="Outcome",
        required_assertions="[]",
    )
    case = test_repository.get_test_case("t_tc")
    assert case["title"] == "Title"

    test_repository.create_test_result("res_tc", "t_tc", run_id, "passed", _utcnow())
    test_repository.add_step_result(
        "res_tc", 0, "click", "passed", None, 120, None, '{"role":"button"}'
    )
    test_repository.finish_test_result(
        "res_tc",
        "passed",
        None,
        None,
        None,
        _utcnow(),
        120,
        None,
        "[]",
        "[]",
        "[]",
    )
    result = test_repository.get_test_result("res_tc")
    assert result["status"] == "passed"
    assert result["duration_ms"] == 120
    steps = test_repository.list_step_results("res_tc")
    assert len(steps) == 1
    assert steps[0]["action"] == "click"

    latest = test_repository.get_test_result_by_test("t_tc")
    assert latest["id"] == "res_tc"


def test_bug_report_crud():
    init_db()
    run_id = "r_bug"
    run_repository.create_run(run_id, "http://localhost:3000", "goal", "disabled")
    bug_repository.create_bug_report(
        bug_id="b_bug",
        run_id=run_id,
        test_id="t_bug",
        title="Bug title",
        severity="critical",
        priority="immediate",
        environment="http://localhost:3000",
        browser="chromium",
        browser_version="124",
        target_url="http://localhost:3000",
        reproduction_steps="[]",
        preconditions="[]",
        test_data="{}",
        expected_result="ok",
        actual_result="failed",
        failure_category="application_assertion_failure",
        timestamp=_utcnow(),
        screenshot_path="artifacts/screenshots/x.png",
        console_errors="[]",
        network_requests="[]",
        execution_logs="[]",
        probable_cause="cause",
        confidence="high",
        limitations="none",
        dedup_key="k_bug",
    )
    bugs = bug_repository.list_bugs_for_run(run_id)
    assert len(bugs) == 1
    assert bugs[0]["title"] == "Bug title"
    assert bugs[0]["severity"] == "critical"
    assert bugs[0]["dedup_key"] == "k_bug"

    got = bug_repository.get_bug_report("b_bug")
    assert got["confidence"] == "high"

    bug_repository.create_rerun_history("rh_bug", "t_bug", run_id, "res_tc", "user rerun")
