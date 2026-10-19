"""Orchestrates a full testing run: explore -> generate -> validate ->
execute -> analyze -> report -> persist.

Kept separate from the HTTP layer so the same pipeline can be reused by the
API, the CLI, or tests without starting the server.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import validate_target_url
import sqlite3

from app.repositories import (
    bug_repository,
    database,
    run_repository,
    test_repository,
)
from app.repositories.database import execute
from app.schemas.bug_report import new_bug_id
from app.schemas.exploration import new_page_id
from app.schemas.run import RunStatus
from app.schemas.test_result import TestStatus, new_result_id
from app.services.browser_explorer import BrowserExplorer
from app.services.bug_reporter import BugReporter
from app.services.failure_analyzer import FailureAnalyzer
from app.services.plan_validator import PlanValidator
from app.services.scenario_generator import ScenarioGenerator
from app.services.test_executor import TestExecutor

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunPipeline:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or settings.DATABASE_URL

    # ------------------------------------------------------------------ #
    # Entry point (called from FastAPI background task)
    # ------------------------------------------------------------------ #
    async def execute_run(
        self,
        run_id: str,
        target_url: str,
        goal: str,
        llm_mode: str,
    ) -> None:
        database.init_db(self.database_url)
        run_repository.create_run(run_id, target_url, goal, llm_mode)
        run_repository.update_run_status(run_id, RunStatus.RUNNING.value, started_at=_utcnow())

        browser_version = "unknown"
        try:
            safe_url = validate_target_url(target_url)

            # 1. Explore
            async with BrowserExplorer() as explorer:
                exploration = await explorer.explore(
                    safe_url,
                    max_pages=settings.MAX_CRAWL_PAGES,
                    max_depth=settings.MAX_CRAWL_DEPTH,
                )
                browser_version = getattr(explorer._browser, "version", "unknown") or "unknown"

            self._persist_exploration(run_id, exploration)

            # 2. Generate
            generator = ScenarioGenerator(exploration, safe_url)
            test_cases = generator.generate(goal, llm_mode)

            # 3. Validate
            validation = PlanValidator(exploration).validate(test_cases)
            for case in validation.valid:
                case.run_id = run_id
            self._persist_test_cases(run_id, validation.valid)

            logger.info(
                "Run %s: %d test cases generated, %d valid, %d rejected",
                run_id,
                len(test_cases),
                len(validation.valid),
                len(validation.rejected),
            )

            # 4. Execute
            analyzer = FailureAnalyzer(llm_summarize=llm_mode != "disabled")
            reporter = BugReporter(settings.BROWSER, browser_version)

            async with TestExecutor() as executor:
                passed = failed = skipped = inconclusive = 0
                for case in validation.valid:
                    context = await executor._browser.new_context(ignore_https_errors=True)  # noqa: SLF001
                    try:
                        result = await executor.execute_case(case, safe_url, context)
                    finally:
                        await context.close()

                    self._persist_result(case, result)

                    if result.status == TestStatus.PASSED:
                        passed += 1
                    elif result.status == TestStatus.SKIPPED:
                        skipped += 1
                    elif result.status == TestStatus.INCONCLUSIVE:
                        inconclusive += 1
                    else:
                        failed += 1
                        self._handle_failure(
                            run_id, case, result, exploration, analyzer, reporter, safe_url
                        )

                summary = {
                    "total": len(validation.valid),
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "inconclusive": inconclusive,
                    "rejected": len(validation.rejected),
                    "warnings": validation.warnings,
                }
                run_repository.update_run_status(
                    run_id,
                    RunStatus.COMPLETED.value,
                    finished_at=_utcnow(),
                    summary=json.dumps(summary),
                )
                logger.info("Run %s completed: %s", run_id, summary)

        except Exception as exc:  # pragma: no cover - infrastructure
            logger.exception("Run %s failed: %s", run_id, exc)
            run_repository.update_run_status(
                run_id,
                RunStatus.FAILED.value,
                finished_at=_utcnow(),
                summary=json.dumps({"error": str(exc)}),
            )

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Rerun of a single test case
    # ------------------------------------------------------------------ #
    async def execute_single_test(
        self, case, run_id: str, base_url: str, result_id: str
    ) -> None:
        """Re-execute a single stored test case (used by the rerun endpoint)."""
        database.init_db(self.database_url)
        case.run_id = run_id
        test_repository.finish_test_result(
            result_id=result_id,
            status="running",
            error_message=None,
            failure_category=None,
            confidence=None,
            finished_at=_utcnow(),
            duration_ms=0,
            screenshot_path=None,
            console_errors="[]",
            network_errors="[]",
            logs="[]",
        )

        analyzer = FailureAnalyzer(llm_summarize=False)
        reporter = BugReporter(settings.BROWSER)

        async with TestExecutor() as executor:
            context = await executor._browser.new_context(ignore_https_errors=True)  # noqa: SLF001
            try:
                result = await executor.execute_case(case, base_url, context)
            finally:
                await context.close()

        result.id = result_id
        result.test_id = case.id
        result.run_id = run_id
        # The rerun endpoint already inserted a pending result row.
        self._persist_result(case, result, create_row=False)

        if result.status == TestStatus.FAILED:
            self._handle_failure(
                run_id, case, result, None, analyzer, reporter, base_url
            )

    def _record_artifact(self, run_id: str, type_: str, path: str | None) -> None:
        if not path:
            return
        from app.schemas.artifact import new_artifact_id

        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        rel = os.path.relpath(path, settings.ARTIFACTS_DIR).replace(os.sep, "/")
        url = "/artifacts/" + rel
        execute(
            """
            INSERT INTO artifacts (id, run_id, type, path, url, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_artifact_id(),
                run_id,
                type_,
                path,
                url,
                size,
                _utcnow().isoformat(),
            ),
        )

    def _persist_exploration(self, run_id: str, exploration) -> None:
        from app.repositories.database import execute

        for page in exploration.pages:
            execute(
                """
                INSERT INTO discovered_pages
                (id, run_id, url, title, depth, screenshot_path, console_errors, network_errors, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_page_id(),
                    run_id,
                    page.url,
                    page.title,
                    page.depth,
                    page.screenshot_path,
                    json.dumps(page.console_errors),
                    json.dumps(page.network_errors),
                    _utcnow().isoformat(),
                ),
            )

    def _persist_test_cases(self, run_id: str, cases) -> None:
        from app.schemas.test_case import ActionType

        for case in cases:
            test_repository.create_test_case(
                test_id=case.id,
                run_id=run_id,
                title=case.title,
                objective=case.objective,
                generation_mode=case.generation_mode,
                priority=case.priority.value if hasattr(case.priority, "value") else case.priority,
                risk_level=case.risk_level.value if hasattr(case.risk_level, "value") else case.risk_level,
                preconditions=json.dumps(case.preconditions),
                steps=json.dumps(
                    [
                        {
                            "action": s.action.value,
                            "target": s.target.model_dump() if s.target else None,
                            "value": s.value,
                            "assertion_value": s.assertion_value,
                            "attribute": s.attribute,
                            "description": s.description,
                        }
                        for s in case.steps
                    ]
                ),
                target_elements=json.dumps([t.model_dump() for t in case.target_elements]),
                test_data=json.dumps(case.test_data),
                expected_outcome=case.expected_outcome,
                required_assertions=json.dumps(case.required_assertions),
            )

    def _persist_result(self, case, result, create_row: bool = True) -> None:
        if create_row:
            test_repository.create_test_result(
                result_id=result.id,
                test_id=case.id,
                run_id=case.run_id,
                status=result.status.value,
                started_at=result.started_at,
            )
        for sr in result.step_results:
            test_repository.add_step_result(
                result_id=result.id,
                step_index=sr.step_index,
                action=sr.action,
                status=sr.status.value,
                error=sr.error,
                duration_ms=sr.duration_ms,
                screenshot_path=sr.screenshot_path,
                target=sr.target,
            )
        test_repository.finish_test_result(
            result_id=result.id,
            status=result.status.value,
            error_message=result.error_message,
            failure_category=(
                result.failure_category.value
                if result.failure_category and hasattr(result.failure_category, "value")
                else result.failure_category
            ),
            confidence=result.confidence,
            finished_at=result.finished_at or _utcnow(),
            duration_ms=result.duration_ms or 0,
            screenshot_path=result.screenshot_path,
            console_errors=json.dumps(result.console_errors or []),
            network_errors=json.dumps(result.network_errors or []),
            logs=json.dumps(result.logs or []),
        )

    def _handle_failure(self, run_id, case, result, exploration, analyzer, reporter, safe_url) -> None:
        analysis = analyzer.analyze(
            title=case.title,
            expected_outcome=case.expected_outcome,
            status=result.status,
            error_message=result.error_message,
            category=result.failure_category,
            step_results=result.step_results,
            console_errors=result.console_errors or [],
            network_errors=result.network_errors or [],
            logs=result.logs or [],
            screenshot_path=result.screenshot_path,
            test_data=case.test_data,
        )

        # Update the result with refined classification and confidence.
        test_repository.finish_test_result(
            result_id=result.id,
            status=result.status.value,
            error_message=result.error_message,
            failure_category=analysis.category.value,
            confidence=analysis.confidence,
            finished_at=result.finished_at or _utcnow(),
            duration_ms=result.duration_ms or 0,
            screenshot_path=result.screenshot_path,
            console_errors=json.dumps(result.console_errors or []),
            network_errors=json.dumps(result.network_errors or []),
            logs=json.dumps(result.logs or []),
        )

        # Only genuine application defects backed by evidence become bug reports.
        if not analysis.is_application_defect:
            logger.info(
                "Run %s test %s failure (%s) is not classified as an application defect; no bug report.",
                run_id,
                case.id,
                analysis.category,
            )
            return

        def dedup_check(dedup_key: str):
            return bug_repository.find_bug_by_dedup_key(dedup_key)

        bug = reporter.report(
            run_id=run_id,
            test_id=case.id,
            test_title=case.title,
            test_objective=case.objective,
            test_data=case.test_data,
            expected_outcome=case.expected_outcome,
            result=result,
            analysis=analysis,
            target_url=safe_url,
            environment=safe_url,
            dedup_check=dedup_check,
        )
        if bug is None:
            return

        # A rerun that hits an existing dedup key returns the stored row;
        # associate the rerun with that report instead of duplicating it.
        if isinstance(bug, sqlite3.Row):
            bug_repository.create_rerun_history(
                f"rerun_{result.id}", case.id, run_id, result.id, "regression check"
            )
            return

        bug_id = bug["id"] if isinstance(bug, sqlite3.Row) else bug.id
        bug_repository.create_bug_report(
            bug_id=bug_id,
            run_id=run_id,
            test_id=case.id,
            title=bug["title"] if isinstance(bug, sqlite3.Row) else bug.title,
            severity=(
                bug["severity"]
                if isinstance(bug, sqlite3.Row)
                else (bug.severity.value if hasattr(bug.severity, "value") else bug.severity)
            ),
            priority=(
                bug["priority"]
                if isinstance(bug, sqlite3.Row)
                else (bug.priority.value if hasattr(bug.priority, "value") else bug.priority)
            ),
            environment=bug["environment"] if isinstance(bug, sqlite3.Row) else bug.environment,
            browser=bug["browser"] if isinstance(bug, sqlite3.Row) else bug.browser,
            browser_version=(
                bug["browser_version"]
                if isinstance(bug, sqlite3.Row)
                else bug.browser_version
            ),
            target_url=bug["target_url"] if isinstance(bug, sqlite3.Row) else bug.target_url,
            reproduction_steps=json.dumps(
                bug["reproduction_steps"]
                if isinstance(bug, sqlite3.Row)
                else bug.reproduction_steps
            ),
            preconditions=json.dumps(
                bug["preconditions"] if isinstance(bug, sqlite3.Row) else bug.preconditions
            ),
            test_data=json.dumps(bug["test_data"] if isinstance(bug, sqlite3.Row) else bug.test_data),
            expected_result=bug["expected_result"] if isinstance(bug, sqlite3.Row) else bug.expected_result,
            actual_result=bug["actual_result"] if isinstance(bug, sqlite3.Row) else bug.actual_result,
            failure_category=bug["failure_category"] if isinstance(bug, sqlite3.Row) else bug.failure_category,
            timestamp=bug["timestamp"] if isinstance(bug, sqlite3.Row) else bug.timestamp,
            screenshot_path=bug["screenshot_path"] if isinstance(bug, sqlite3.Row) else bug.screenshot_path,
            console_errors=json.dumps(
                bug["console_errors"] if isinstance(bug, sqlite3.Row) else bug.console_errors
            ),
            network_requests=json.dumps(
                bug["network_requests"] if isinstance(bug, sqlite3.Row) else bug.network_requests
            ),
            execution_logs=json.dumps(
                bug["execution_logs"] if isinstance(bug, sqlite3.Row) else bug.execution_logs
            ),
            probable_cause=bug["probable_cause"] if isinstance(bug, sqlite3.Row) else bug.probable_cause,
            confidence=bug["confidence"] if isinstance(bug, sqlite3.Row) else bug.confidence,
            limitations=bug["limitations"] if isinstance(bug, sqlite3.Row) else bug.limitations,
            dedup_key=bug["dedup_key"] if isinstance(bug, sqlite3.Row) else bug.dedup_key,
        )
        self._record_artifact(run_id, "screenshot", bug["screenshot_path"] if isinstance(bug, sqlite3.Row) else bug.screenshot_path)
