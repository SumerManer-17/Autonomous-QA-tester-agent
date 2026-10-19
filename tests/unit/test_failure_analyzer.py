"""Unit tests for deterministic failure classification."""

from app.schemas.test_result import FailureCategory, TestStatus
from app.services.failure_analyzer import FailureAnalyzer


class _FakeStep:
    def __init__(self, status_value):
        self.status = type("S", (), {"value": status_value})()


def _analyze(analyzer, status, error, category, prior_ok=False):
    return analyzer.analyze(
        title="Test X",
        expected_outcome="Element should be visible",
        status=status,
        error_message=error,
        category=category,
        step_results=[_FakeStep("passed")] if prior_ok else [],
        console_errors=[],
        network_errors=[],
        logs=[],
        screenshot_path=None,
        test_data={},
    )


class TestAssertionFailure:
    def test_is_application_defect(self):
        a = FailureAnalyzer()
        result = _analyze(a, TestStatus.FAILED, "text mismatch", FailureCategory.ASSERTION_FAILURE)
        assert result.category == FailureCategory.ASSERTION_FAILURE
        assert result.confidence == "high"
        assert result.is_application_defect is True
        assert result.confidence_score >= 0.8

    def test_not_failed_returns_inconclusive(self):
        a = FailureAnalyzer()
        result = _analyze(a, TestStatus.PASSED, None, None)
        assert result.category == FailureCategory.INCONCLUSIVE
        assert result.is_application_defect is False


class TestElementNotFound:
    def test_prior_passed_means_app_defect(self):
        a = FailureAnalyzer()
        result = _analyze(
            a, TestStatus.FAILED, "element not found", FailureCategory.ELEMENT_NOT_FOUND, prior_ok=True
        )
        assert result.is_application_defect is True
        assert result.confidence_score >= 0.7

    def test_no_prior_means_not_necessarily_defect(self):
        a = FailureAnalyzer()
        result = _analyze(
            a, TestStatus.FAILED, "element not found", FailureCategory.ELEMENT_NOT_FOUND, prior_ok=False
        )
        assert result.is_application_defect is False


class TestNavigationFailure:
    def test_is_application_defect(self):
        a = FailureAnalyzer()
        result = _analyze(a, TestStatus.FAILED, "timeout", FailureCategory.NAVIGATION_FAILURE)
        assert result.is_application_defect is True


class TestBrowserInfrastructure:
    def test_is_not_application_defect(self):
        a = FailureAnalyzer()
        result = _analyze(a, TestStatus.FAILED, "browser crashed", FailureCategory.BROWSER_INFRASTRUCTURE_FAILURE)
        assert result.is_application_defect is False


class TestTestSetupFailure:
    def test_is_not_application_defect(self):
        a = FailureAnalyzer()
        result = _analyze(a, TestStatus.FAILED, "bad step", FailureCategory.TEST_SETUP_FAILURE)
        assert result.is_application_defect is False


class TestTimeout:
    def test_network_error_is_not_defect(self):
        a = FailureAnalyzer()
        result = a.analyze(
            title="T",
            expected_outcome="E",
            status=TestStatus.FAILED,
            error_message="timeout",
            category=FailureCategory.TIMEOUT,
            step_results=[],
            console_errors=[],
            network_errors=["request failed"],
            logs=[],
            screenshot_path=None,
            test_data={},
        )
        assert result.category == FailureCategory.TIMEOUT
        assert result.is_application_defect is False

    def test_js_error_is_defect(self):
        a = FailureAnalyzer()
        result = a.analyze(
            title="T",
            expected_outcome="E",
            status=TestStatus.FAILED,
            error_message="timeout",
            category=FailureCategory.TIMEOUT,
            step_results=[],
            console_errors=["JS error: boom"],
            network_errors=[],
            logs=[],
            screenshot_path=None,
            test_data={},
        )
        assert result.is_application_defect is True
        assert result.confidence_score >= 0.7

    def test_plain_timeout_is_inconclusive_leaning(self):
        a = FailureAnalyzer()
        result = _analyze(a, TestStatus.FAILED, "timeout", FailureCategory.TIMEOUT)
        assert result.is_application_defect is False
        assert result.confidence == "medium"
