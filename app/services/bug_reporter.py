"""Reproducible bug report generation with deterministic severity.

Reports are evidence-based: a report is only created when a test failure has
supporting evidence. The same failure recurring across reruns is attached to
the existing report instead of creating duplicates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.schemas.bug_report import BugReport, Priority, Severity, new_bug_id
from app.schemas.test_result import FailureCategory, TestStatus

logger = get_logger(__name__)

_AUTH_KEYWORDS = (
    "login",
    "log in",
    "sign in",
    "register",
    "registration",
    "sign up",
    "account",
)
_BOOKING_KEYWORDS = ("book", "booking", "reservation", "checkout")
_MEDIUM_KEYWORDS = ("search", "filter", "validation", "invalid", "error", "reject")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def classify_severity(test_title: str, test_objective: str, category: FailureCategory) -> Severity:
    """Deterministic severity based on affected functionality and impact.

    This function is the authority for severity so an LLM cannot mislabel a
    broken login flow as low severity. An LLM may recommend, but rules decide.
    """
    text = f"{test_title} {test_objective or ''}".lower()

    if any(keyword in text for keyword in _AUTH_KEYWORDS):
        if category in (
            FailureCategory.ASSERTION_FAILURE,
            FailureCategory.ELEMENT_NOT_FOUND,
            FailureCategory.NAVIGATION_FAILURE,
            FailureCategory.APPLICATION_HTTP_ERROR,
        ):
            return Severity.CRITICAL
        return Severity.HIGH

    if any(keyword in text for keyword in _BOOKING_KEYWORDS):
        return Severity.HIGH

    if any(keyword in text for keyword in _MEDIUM_KEYWORDS) or category in (
        FailureCategory.ASSERTION_FAILURE,
        FailureCategory.FAILED_NETWORK_REQUEST,
    ):
        return Severity.MEDIUM

    if category in (
        FailureCategory.ELEMENT_AMBIGUOUS,
        FailureCategory.TEST_SETUP_FAILURE,
        FailureCategory.BROWSER_INFRASTRUCTURE_FAILURE,
    ):
        return Severity.LOW

    return Severity.MEDIUM


def classify_priority(severity: Severity) -> Priority:
    return {
        Severity.CRITICAL: Priority.IMMEDIATE,
        Severity.HIGH: Priority.HIGH,
        Severity.MEDIUM: Priority.MEDIUM,
        Severity.LOW: Priority.LOW,
    }[severity]


class BugReporter:
    def __init__(self, browser_name: str, browser_version: str | None = None):
        self.browser_name = browser_name
        self.browser_version = browser_version or "unknown"

    def report(
        self,
        *,
        run_id: str,
        test_id: str,
        test_title: str,
        test_objective: str,
        test_data: dict,
        expected_outcome: str,
        result,
        analysis,
        target_url: str,
        environment: str | None = None,
        dedup_check=None,
    ):
        """Create a bug report for a failed test.

        Returns None when there is no failure evidence to report.
        """
        if result.status != TestStatus.FAILED or not result.error_message:
            return None

        category = result.failure_category or FailureCategory.INCONCLUSIVE
        severity = classify_severity(test_title, test_objective, category)
        priority = classify_priority(severity)

        steps = []
        for sr in result.step_results or []:
            steps.append(
                f"Step {sr.step_index + 1} [{sr.action}]: {sr.status.value}"
                + (f" -- {sr.error}" if sr.error else "")
            )

        actual_result = (
            f"{result.error_message}\n"
            f"Observed: {analysis.observed_behavior}\n"
            f"Probable cause: {analysis.probable_cause}"
        ).strip()

        cat_value = category.value if hasattr(category, "value") else category
        dedup_key = f"{cat_value}:{_slug(test_title)}"

        # Dedup: attach reruns to the existing report instead of duplicating.
        if dedup_check is not None:
            existing = dedup_check(dedup_key)
            if existing is not None:
                logger.info(
                    "Bug %s already reported for %s; associating rerun instead of duplicating",
                    existing["id"],
                    dedup_key,
                )
                return existing

        title = f"{test_title} — {category.value.replace('_', ' ').title()}"

        score = analysis.confidence_score or 0.5
        if score >= 0.8:
            confidence = "high"
        elif score >= 0.6:
            confidence = "medium"
        else:
            confidence = "low"

        report = BugReport(
            id=new_bug_id(),
            run_id=run_id,
            test_id=test_id,
            title=title,
            severity=severity,
            priority=priority,
            environment=environment or target_url,
            browser=self.browser_name,
            browser_version=self.browser_version,
            target_url=target_url,
            reproduction_steps=steps or ["Run the failed test case and observe the failure."],
            preconditions=[],
            test_data={
                k: v
                for k, v in (test_data or {}).items()
                if "secret" not in k.lower() and "password" not in k.lower()
            },
            expected_result=expected_outcome,
            actual_result=actual_result,
            failure_category=category.value,
            timestamp=_utcnow(),
            screenshot_path=result.screenshot_path,
            console_errors=list(analysis.related_console_errors),
            network_requests=list(analysis.related_network_errors),
            execution_logs=list(result.logs or []),
            probable_cause=analysis.probable_cause,
            confidence=f"{confidence} (score {score:.2f})",
            limitations=(
                "Automatically generated from execution evidence. "
                "Manual confirmation recommended before scheduling a fix."
            ),
            dedup_key=dedup_key,
            created_at=_utcnow(),
        )
        logger.info(
            "Created bug report %s (%s, %s) for test %s",
            report.id,
            severity.value,
            category.value,
            test_id,
        )
        return report
