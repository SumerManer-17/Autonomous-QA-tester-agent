"""Repository for test cases, results, and step results."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.repositories.database import execute, query_all, query_one


def create_test_case(
    test_id: str,
    run_id: str,
    title: str,
    objective: str,
    generation_mode: str,
    priority: str,
    risk_level: str,
    preconditions: str,
    steps: str,
    target_elements: str,
    test_data: str,
    expected_outcome: str,
    required_assertions: str,
) -> None:
    execute(
        """
        INSERT INTO test_cases
        (id, run_id, title, objective, generation_mode, priority, risk_level,
         preconditions, steps, target_elements, test_data, expected_outcome,
         required_assertions, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            test_id,
            run_id,
            title,
            objective,
            generation_mode,
            priority,
            risk_level,
            preconditions,
            steps,
            target_elements,
            test_data,
            expected_outcome,
            required_assertions,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def get_test_case(test_id: str):
    return query_one("SELECT * FROM test_cases WHERE id = ?", (test_id,))


def list_test_cases_for_run(run_id: str) -> list:
    return query_all(
        "SELECT * FROM test_cases WHERE run_id = ? ORDER BY created_at", (run_id,)
    )


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def create_test_result(
    result_id: str,
    test_id: str,
    run_id: str,
    status: str,
    started_at,
) -> None:
    execute(
        """
        INSERT INTO test_results
        (id, test_id, run_id, status, error_message, failure_category, confidence,
         started_at, finished_at, duration_ms, screenshot_path, console_errors,
         network_errors, logs)
        VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, '[]', '[]', '[]')
        """,
        (result_id, test_id, run_id, status, _iso(started_at)),
    )


def finish_test_result(
    result_id: str,
    status: str,
    error_message: str | None,
    failure_category: str | None,
    confidence: str | None,
    finished_at,
    duration_ms: int,
    screenshot_path: str | None,
    console_errors: str,
    network_errors: str,
    logs: str,
) -> None:
    execute(
        """
        UPDATE test_results
        SET status = ?, error_message = ?, failure_category = ?, confidence = ?,
            finished_at = ?, duration_ms = ?, screenshot_path = ?,
            console_errors = ?, network_errors = ?, logs = ?
        WHERE id = ?
        """,
        (
            status,
            error_message,
            failure_category,
            confidence,
            _iso(finished_at),
            duration_ms,
            screenshot_path,
            console_errors,
            network_errors,
            logs,
            result_id,
        ),
    )


def get_test_result(result_id: str):
    return query_one("SELECT * FROM test_results WHERE id = ?", (result_id,))


def list_test_results_for_run(run_id: str) -> list:
    return query_all(
        "SELECT * FROM test_results WHERE run_id = ? ORDER BY started_at", (run_id,)
    )


def get_test_result_by_test(test_id: str):
    return query_one(
        "SELECT * FROM test_results WHERE test_id = ? ORDER BY started_at DESC LIMIT 1",
        (test_id,),
    )


def list_step_results(result_id: str) -> list:
    return query_all(
        "SELECT * FROM step_results WHERE test_result_id = ? ORDER BY step_index",
        (result_id,),
    )


def add_step_result(
    result_id: str,
    step_index: int,
    action: str,
    status: str,
    error: str | None,
    duration_ms: int | None,
    screenshot_path: str | None,
    target: str | None = None,
) -> None:
    execute(
        """
        INSERT INTO step_results
        (id, test_result_id, step_index, action, target, status, error,
         duration_ms, screenshot_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"step_{result_id}_{step_index}",
            result_id,
            step_index,
            action,
            json.dumps(target) if target is not None else None,
            status,
            error,
            duration_ms,
            screenshot_path,
        ),
    )
