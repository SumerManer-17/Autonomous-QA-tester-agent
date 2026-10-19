"""Test plan validation.

Reviews generated test cases against discovered UI elements before execution.
Rejects malformed plans and reports unresolvable targets honestly rather than
letting the executor fail mysteriously at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.schemas.exploration import ExplorationResult
from app.schemas.test_case import ActionType, Step, TestCase

logger = get_logger(__name__)

# Steps that legitimately appear before any page navigation (e.g. the first
# navigate of a test, or assertions on already-loaded pages).
NAVIGATE_ACTION = ActionType.NAVIGATE.value


@dataclass
class ValidationResult:
    valid: list[TestCase] = field(default_factory=list)
    rejected: list[tuple[TestCase, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.rejected and not self.warnings


class PlanValidator:
    def __init__(self, exploration: ExplorationResult):
        self.exploration = exploration
        # Flatten all discovered elements for target resolution hints.
        self.all_elements: list = []
        for page in exploration.pages:
            self.all_elements.extend(page.elements)

    def validate(self, test_cases: list[TestCase]) -> ValidationResult:
        result = ValidationResult()
        for case in test_cases:
            issue = self._validate_case(case)
            if issue:
                result.rejected.append((case, issue))
                logger.warning("Rejected test case %s: %s", case.id, issue)
                continue
            result.valid.append(case)
            for warning in self._case_warnings(case):
                result.warnings.append(f"{case.id}: {warning}")
        return result

    def _validate_case(self, case: TestCase) -> str | None:
        if not case.steps:
            return "test case has no steps"
        for index, step in enumerate(case.steps):
            if step.action not in ActionType.supported():
                return f"step {index}: unsupported action {step.action}"
            if step.action == NAVIGATE_ACTION and not step.value:
                return f"step {index}: navigate step requires a value (URL)"
            if (
                step.action not in (NAVIGATE_ACTION, ActionType.ASSERT_URL.value)
                and step.target is None
            ):
                return f"step {index}: {step.action} requires a target"
            if step.action == ActionType.ASSERT_TEXT and step.assertion_value is None:
                return f"step {index}: assert_text requires assertion_value"
            if step.action == ActionType.FILL and step.value is None:
                return f"step {index}: fill requires a value"
        # First meaningful step should navigate unless the test targets a page
        # already known to be loaded; warn rather than reject.
        return None

    def _case_warnings(self, case: TestCase) -> list[str]:
        warnings: list[str] = []
        has_navigate = any(s.action == NAVIGATE_ACTION for s in case.steps)
        if not has_navigate:
            warnings.append("no navigate step; assumes target page is already loaded")
        for index, step in enumerate(case.steps):
            if step.action == NAVIGATE_ACTION:
                continue
            if step.target and not self._target_resolves(step.target):
                warnings.append(
                    f"step {index} ({step.action}) target {step.target.describe()} "
                    "was not discovered on any explored page"
                )
        return warnings

    def _target_resolves(self, target) -> bool:
        for el in self.all_elements:
            if el.role != target.role:
                continue
            if target.name and (el.name == target.name or el.label == target.name):
                return True
            if target.test_id and el.test_id == target.test_id:
                return True
            if target.placeholder and el.placeholder == target.placeholder:
                return True
        return False
