"""Unit tests for Pydantic test-plan schema validation."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.test_case import ActionType, Step, TargetLocator, TestCase
from app.schemas.test_result import FailureCategory, StepResult, TestResult, TestStatus


class TestTargetLocator:
    def test_requires_at_least_one_attribute(self):
        with pytest.raises(ValidationError):
            TargetLocator()

    def test_describe(self):
        el = TargetLocator(role="textbox", name="Email")
        assert "role='textbox'" in el.describe()
        assert "name='Email'" in el.describe()


class TestStep:
    def test_navigate_requires_value(self):
        with pytest.raises(ValidationError):
            Step(action=ActionType.NAVIGATE)

    def test_fill_requires_target_and_value(self):
        with pytest.raises(ValidationError):
            Step(action=ActionType.FILL, target=TargetLocator(role="textbox", name="x"))

    def test_assert_text_requires_assertion_value(self):
        with pytest.raises(ValidationError):
            Step(action=ActionType.ASSERT_TEXT, target=TargetLocator(role="textbox", name="x"))

    def test_assert_count_requires_target(self):
        with pytest.raises(ValidationError):
            Step(action=ActionType.ASSERT_COUNT, assertion_value="1")

    def test_unsupported_action_rejected(self):
        with pytest.raises(ValidationError):
            Step(action="arbitrary_code_execution")  # type: ignore[arg-type]

    def test_supported_actions(self):
        assert ActionType.CLICK.value in ActionType.supported()
        assert ActionType.ASSERT_ATTRIBUTE.value in ActionType.supported()
        assert len(ActionType.supported()) >= 12


class TestTestCase:
    def test_empty_steps_rejected(self):
        with pytest.raises(ValidationError):
            TestCase(
                id="t1",
                run_id="r1",
                title="x",
                objective="y",
                steps=[],
                expected_outcome="z",
                created_at=datetime.now(timezone.utc),
            )

    def test_minimal_valid(self):
        case = TestCase(
            id="t1",
            run_id="r1",
            title="Title",
            objective="Obj",
            steps=[
                Step(
                    action=ActionType.NAVIGATE,
                    value="http://localhost:3000/",
                ),
                Step(
                    action=ActionType.ASSERT_VISIBLE,
                    target=TargetLocator(role="button", name="Submit"),
                ),
            ],
            expected_outcome="Page loads",
            created_at=datetime.now(timezone.utc),
        )
        assert case.id == "t1"
        assert case.priority == "medium"


class TestFailureCategory:
    def test_categories_are_strings(self):
        assert FailureCategory.ASSERTION_FAILURE.value == "application_assertion_failure"
        assert FailureCategory.TIMEOUT.value == "timeout"


class TestStepResultAndTestResult:
    def test_step_result_defaults(self):
        sr = StepResult(step_index=0, action="click", status=TestStatus.PASSED)
        assert sr.status == TestStatus.PASSED

    def test_test_result_fields(self):
        tr = TestResult(
            id="res1",
            test_id="t1",
            run_id="r1",
            status=TestStatus.FAILED,
            error_message="boom",
            failure_category=FailureCategory.ELEMENT_NOT_FOUND,
            confidence="low",
            started_at=datetime.now(timezone.utc),
        )
        assert tr.status == TestStatus.FAILED
        tr.mark_step(1, "fill", TestStatus.FAILED, error="not found")
        assert len(tr.step_results) == 1
