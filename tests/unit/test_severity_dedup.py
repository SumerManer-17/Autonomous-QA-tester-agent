"""Unit tests for severity classification and bug-report deduplication."""

from app.repositories.bug_repository import create_bug_report, find_bug_by_dedup_key
from app.repositories.run_repository import create_run
from app.services.bug_reporter import classify_priority, classify_severity
from app.schemas.bug_report import Priority, Severity
from app.schemas.test_result import FailureCategory


class TestClassifySeverity:
    def test_login_assertion_failure_is_critical(self):
        sev = classify_severity(
            "Login with valid credentials", "A user can sign in.", FailureCategory.ASSERTION_FAILURE
        )
        assert sev == Severity.CRITICAL

    def test_registration_element_not_found_is_critical(self):
        sev = classify_severity(
            "Register with valid data", "Create account.", FailureCategory.ELEMENT_NOT_FOUND
        )
        assert sev == Severity.CRITICAL

    def test_booking_is_high(self):
        sev = classify_severity(
            "Complete a hotel booking", "Finish booking.", FailureCategory.ELEMENT_NOT_FOUND
        )
        assert sev == Severity.HIGH

    def test_search_validation_is_medium(self):
        sev = classify_severity(
            "Search respects price filter", "Filter results.", FailureCategory.ASSERTION_FAILURE
        )
        assert sev == Severity.MEDIUM

    def test_ambiguous_selector_is_low(self):
        sev = classify_severity("Some UI test", "Check UI.", FailureCategory.ELEMENT_AMBIGUOUS)
        assert sev == Severity.LOW

    def test_setup_failure_is_low(self):
        sev = classify_severity("X", "Y", FailureCategory.TEST_SETUP_FAILURE)
        assert sev == Severity.LOW


class TestClassifyPriority:
    def test_mapping(self):
        assert classify_priority(Severity.CRITICAL) == Priority.IMMEDIATE
        assert classify_priority(Severity.HIGH) == Priority.HIGH
        assert classify_priority(Severity.MEDIUM) == Priority.MEDIUM
        assert classify_priority(Severity.LOW) == Priority.LOW


class TestDedup:
    def test_find_bug_by_dedup_key_absent(self):
        assert find_bug_by_dedup_key("application_assertion_failure:no-such-key") is None

    def test_create_and_find_dedup_key(self):
        from app.repositories.database import init_db

        init_db()
        create_run("r_dedup", "http://localhost:3000", "g", "disabled")
        # Use a key unlikely to collide with other tests sharing the temp DB.
        key = "application_assertion_failure:dedup-test-key-1234"
        assert find_bug_by_dedup_key(key) is None
        create_bug_report(
            bug_id="bug1",
            run_id="r1",
            test_id="t1",
            title="Reject invalid registration email",
            severity=Severity.CRITICAL,
            priority=Priority.IMMEDIATE,
            environment="http://localhost:3000",
            browser="chromium",
            browser_version="124",
            target_url="http://localhost:3000",
            reproduction_steps="[]",
            preconditions="[]",
            test_data="{}",
            expected_result="rejected",
            actual_result="accepted",
            failure_category="application_assertion_failure",
            timestamp="2026-01-01T00:00:00+00:00",
            screenshot_path=None,
            console_errors="[]",
            network_requests="[]",
            execution_logs="[]",
            probable_cause="defect",
            confidence="high",
            limitations="none",
            dedup_key=key,
        )
        found = find_bug_by_dedup_key(key)
        assert found is not None
        assert found["id"] == "bug1"
