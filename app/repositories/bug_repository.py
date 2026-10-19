"""Repository for bug reports and rerun history."""

from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.database import execute, query_all, query_one


def create_bug_report(
    bug_id: str,
    run_id: str,
    test_id: str,
    title: str,
    severity: str,
    priority: str,
    environment: str,
    browser: str,
    browser_version: str,
    target_url: str,
    reproduction_steps: str,
    preconditions: str,
    test_data: str,
    expected_result: str,
    actual_result: str,
    failure_category: str,
    timestamp,
    screenshot_path: str | None,
    console_errors: str,
    network_requests: str,
    execution_logs: str,
    probable_cause: str | None,
    confidence: str | None,
    limitations: str | None,
    dedup_key: str | None,
) -> None:
    execute(
        """
        INSERT INTO bug_reports
        (id, run_id, test_id, title, severity, priority, environment, browser,
         browser_version, target_url, reproduction_steps, preconditions, test_data,
         expected_result, actual_result, failure_category, timestamp,
         screenshot_path, console_errors, network_requests, execution_logs,
         probable_cause, confidence, limitations, dedup_key, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            bug_id,
            run_id,
            test_id,
            title,
            severity,
            priority,
            environment,
            browser,
            browser_version,
            target_url,
            reproduction_steps,
            preconditions,
            test_data,
            expected_result,
            actual_result,
            failure_category,
            timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            screenshot_path,
            console_errors,
            network_requests,
            execution_logs,
            probable_cause,
            confidence,
            limitations,
            dedup_key,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def get_bug_report(bug_id: str):
    return query_one("SELECT * FROM bug_reports WHERE id = ?", (bug_id,))


def list_bugs_for_run(run_id: str) -> list:
    return query_all(
        "SELECT * FROM bug_reports WHERE run_id = ? ORDER BY created_at DESC",
        (run_id,),
    )


def find_bug_by_dedup_key(dedup_key: str):
    return query_one(
        "SELECT * FROM bug_reports WHERE dedup_key = ? ORDER BY created_at LIMIT 1",
        (dedup_key,),
    )


def create_rerun_history(
    rerun_id: str,
    original_test_id: str,
    run_id: str,
    test_result_id: str,
    reason: str | None,
) -> None:
    execute(
        """
        INSERT INTO rerun_history
        (id, original_test_id, run_id, test_result_id, triggered_at, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            rerun_id,
            original_test_id,
            run_id,
            test_result_id,
            datetime.now(timezone.utc).isoformat(),
            reason,
        ),
    )
