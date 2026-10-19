"""Deterministic failure classification with optional LLM summarization.

Categories distinguish application defects from test infrastructure
problems. A timeout, for example, may be a slow environment, a broken
selector, or a real application hang -- the surrounding evidence decides.

The LLM is only allowed to rephrase evidence; it never changes the category,
confidence, or invents facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.core.security import sanitize_for_llm
from app.schemas.test_result import FailureCategory, TestStatus

logger = get_logger(__name__)


@dataclass
class FailureAnalysis:
    category: FailureCategory
    confidence: str  # low | medium | high
    confidence_score: float  # 0.0 - 1.0
    observed_behavior: str
    expected_behavior: str
    assertion_or_exception: str | None
    related_console_errors: list[str] = field(default_factory=list)
    related_network_errors: list[str] = field(default_factory=list)
    probable_cause: str = ""
    recommended_step: str = ""
    is_application_defect: bool = False  # deterministic opinion


class FailureAnalyzer:
    def __init__(self, llm_summarize: bool = False):
        self.llm_summarize = llm_summarize

    def analyze(
        self,
        *,
        title: str,
        expected_outcome: str,
        status: TestStatus,
        error_message: str | None,
        category: FailureCategory | None,
        step_results,
        console_errors: list[str],
        network_errors: list[str],
        logs: list[str],
        screenshot_path: str | None,
        test_data: dict | None = None,
    ) -> FailureAnalysis:
        if status != TestStatus.FAILED or not error_message:
            return FailureAnalysis(
                category=category or FailureCategory.INCONCLUSIVE,
                confidence="low",
                confidence_score=0.3,
                observed_behavior="Test did not fail.",
                expected_behavior=expected_outcome or "No expected outcome recorded.",
                assertion_or_exception=None,
                related_console_errors=console_errors[:10],
                related_network_errors=network_errors[:10],
                probable_cause="No failure evidence available.",
                recommended_step="No investigation needed.",
                is_application_defect=False,
            )

        category = category or FailureCategory.INCONCLUSIVE
        analysis = self._classify(
            error_message=error_message,
            category=category,
            step_results=step_results,
            console_errors=console_errors,
            network_errors=network_errors,
        )

        analysis.expected_behavior = expected_outcome or "No expected outcome recorded."
        analysis.assertion_or_exception = error_message
        analysis.related_console_errors = console_errors[:10]
        analysis.related_network_errors = network_errors[:10]

        if screenshot_path:
            analysis.observed_behavior += f" Evidence: screenshot {screenshot_path}."

        if self.llm_summarize:
            try:
                self._llm_refine(analysis, title, test_data or {})
            except Exception as exc:  # pragma: no cover - LLM is optional
                logger.warning("LLM failure summarization skipped: %s", exc)

        return analysis

    # ------------------------------------------------------------------ #
    # Deterministic classification
    # ------------------------------------------------------------------ #
    def _classify(self, error_message, category, step_results, console_errors, network_errors):
        msg = (error_message or "").lower()

        if category == FailureCategory.ELEMENT_NOT_FOUND:
            return self._element_not_found(msg, step_results, console_errors)
        if category == FailureCategory.ELEMENT_AMBIGUOUS:
            return FailureAnalysis(
                category=FailureCategory.ELEMENT_AMBIGUOUS,
                confidence="high",
                confidence_score=0.9,
                observed_behavior=f"Multiple elements matched the step target: {error_message}",
                expected_behavior="Exactly one element matches the step target.",
                assertion_or_exception=error_message,
                probable_cause="The test selector is not unique (UI changed or selector too broad).",
                recommended_step="Refine the locator (add data-testid or narrow the accessible name).",
                is_application_defect=False,
            )
        if category == FailureCategory.NAVIGATION_FAILURE:
            return FailureAnalysis(
                category=FailureCategory.NAVIGATION_FAILURE,
                confidence="high",
                confidence_score=0.85,
                observed_behavior=f"Navigation failed: {error_message}",
                expected_behavior="The requested page loads within the navigation timeout.",
                assertion_or_exception=error_message,
                probable_cause="Target page unreachable, redirect outside authorized origin, or network failure.",
                recommended_step="Verify the target URL is up and navigation stays within the same origin.",
                is_application_defect=True,
            )
        if category == FailureCategory.APPLICATION_HTTP_ERROR:
            return FailureAnalysis(
                category=FailureCategory.APPLICATION_HTTP_ERROR,
                confidence="high",
                confidence_score=0.95,
                observed_behavior=f"The application returned an HTTP error: {error_message}",
                expected_behavior="The application returns a successful HTTP status.",
                assertion_or_exception=error_message,
                probable_cause="Application server error or broken route.",
                recommended_step="Inspect server logs for the failing route.",
                is_application_defect=True,
            )
        if category == FailureCategory.FAILED_NETWORK_REQUEST:
            return FailureAnalysis(
                category=FailureCategory.FAILED_NETWORK_REQUEST,
                confidence="high",
                confidence_score=0.8,
                observed_behavior=f"A network request failed during the test: {error_message}",
                expected_behavior="All network requests required by the flow succeed.",
                assertion_or_exception=error_message,
                related_network_errors=network_errors,
                probable_cause="A request required by the flow failed (see related_network_errors).",
                recommended_step="Check failed network requests and server availability.",
                is_application_defect=True,
            )
        if category == FailureCategory.TIMEOUT:
            return self._timeout_analysis(msg, console_errors, network_errors)
        if category == FailureCategory.BROWSER_INFRASTRUCTURE_FAILURE:
            return FailureAnalysis(
                category=FailureCategory.BROWSER_INFRASTRUCTURE_FAILURE,
                confidence="medium",
                confidence_score=0.7,
                observed_behavior=f"Browser or infrastructure error: {error_message}",
                expected_behavior="The browser executes the step without crashing.",
                assertion_or_exception=error_message,
                probable_cause="Test infrastructure problem (browser launch, context, or Playwright error).",
                recommended_step="Retry the test; check browser installation and system resources.",
                is_application_defect=False,
            )
        if category == FailureCategory.TEST_SETUP_FAILURE:
            return FailureAnalysis(
                category=FailureCategory.TEST_SETUP_FAILURE,
                confidence="high",
                confidence_score=0.95,
                observed_behavior=f"Test setup failure: {error_message}",
                expected_behavior="The test case is valid and executable.",
                assertion_or_exception=error_message,
                probable_cause="Invalid test case definition (missing value, unsupported action, or budget exceeded).",
                recommended_step="Fix the generated test case; this is not an application defect.",
                is_application_defect=False,
            )
        if category == FailureCategory.ASSERTION_FAILURE:
            return self._assertion_analysis(error_message, console_errors, network_errors)

        return FailureAnalysis(
            category=FailureCategory.INCONCLUSIVE,
            confidence="low",
            confidence_score=0.4,
            observed_behavior=f"Unclassified failure: {error_message}",
            expected_behavior="See expected outcome.",
            assertion_or_exception=error_message,
            related_console_errors=console_errors[:5],
            related_network_errors=network_errors[:5],
            probable_cause="Insufficient evidence to classify the failure.",
            recommended_step="Re-run the test and collect more evidence.",
            is_application_defect=False,
        )

    def _element_not_found(self, msg, step_results, console_errors) -> FailureAnalysis:
        prior_ok = any(
            getattr(s, "status", None) and s.status.value == "passed" for s in step_results
        )
        confidence_score = 0.75 if prior_ok else 0.55
        return FailureAnalysis(
            category=FailureCategory.ELEMENT_NOT_FOUND,
            confidence="medium" if prior_ok else "low",
            confidence_score=confidence_score,
            observed_behavior=f"The target element was not found on the page: {msg}",
            expected_behavior="The element should be present and interactable.",
            assertion_or_exception=msg or "element not found",
            related_console_errors=console_errors[:5],
            probable_cause=(
                "The UI changed (element removed or renamed) -- possible application defect"
                if prior_ok
                else "The selector may be stale or the page did not reach the expected state"
            ),
            recommended_step=(
                "Compare against a working release; if the element is gone, file a UI regression bug."
                if prior_ok
                else "Refresh the discovered element map and regenerate the test case."
            ),
            is_application_defect=prior_ok,
        )

    def _timeout_analysis(self, msg, console_errors, network_errors) -> FailureAnalysis:
        has_network_issue = any("failed" in n.lower() for n in network_errors)
        has_js_error = any("error" in c.lower() for c in console_errors)
        if has_network_issue:
            score, cause, step, defect = (
                0.8,
                "Network requests failed around the timeout.",
                "Check failed network requests and server connectivity.",
                False,
            )
        elif has_js_error:
            score, cause, step, defect = (
                0.75,
                "JavaScript errors on the page may have blocked the action.",
                "Review console errors; likely an application defect.",
                True,
            )
        else:
            score, cause, step, defect = (
                0.55,
                "The action took longer than the timeout (slow environment, slow selector, or real hang).",
                "Re-run with a longer timeout; capture a trace if it recurs.",
                False,
            )
        return FailureAnalysis(
            category=FailureCategory.TIMEOUT,
            confidence="medium",
            confidence_score=score,
            observed_behavior=f"The step timed out: {msg}",
            expected_behavior="The action completes within the configured timeout.",
            assertion_or_exception=msg or "timeout",
            related_console_errors=console_errors[:5],
            related_network_errors=network_errors[:5],
            probable_cause=cause,
            recommended_step=step,
            is_application_defect=defect,
        )

    def _assertion_analysis(self, error_message, console_errors, network_errors) -> FailureAnalysis:
        has_console = bool(console_errors)
        has_network = bool(network_errors)
        score = 0.8 + (0.1 if has_console else 0.0) + (0.1 if has_network else 0.0)
        score = min(score, 0.98)
        return FailureAnalysis(
            category=FailureCategory.ASSERTION_FAILURE,
            confidence="high",
            confidence_score=score,
            observed_behavior=f"Assertion failed: {error_message}",
            expected_behavior="See the test case's expected outcome.",
            assertion_or_exception=error_message,
            related_console_errors=console_errors[:5],
            related_network_errors=network_errors[:5],
            probable_cause=(
                "The application did not behave as expected (likely defect)."
                if score >= 0.8
                else "Assertion failed; corroborating evidence is limited."
            ),
            recommended_step=(
                "Reproduce manually in the browser and compare with the expected outcome."
                if score >= 0.8
                else "Re-run the test; if it fails consistently, review page state and selectors."
            ),
            is_application_defect=True,
        )

    # ------------------------------------------------------------------ #
    # LLM use: rephrase only, never invent facts
    # ------------------------------------------------------------------ #
    def _llm_refine(self, analysis: FailureAnalysis, title: str, test_data: dict) -> None:
        from app.services.llm_provider import llm_manager

        if not llm_manager.is_available():
            return
        system = (
            "You are a QA analyst. Rewrite the observed behavior, probable "
            "cause, and recommended step for a bug report. Use ONLY the facts "
            "provided. Do not invent errors, URLs, or behavior. Do not change "
            "the failure category or confidence. Output JSON with keys: "
            "observed_behavior, probable_cause, recommended_step."
        )
        prompt = (
            f"Test: {sanitize_for_llm(title)}\n"
            f"Category: {analysis.category}\n"
            f"Observed: {sanitize_for_llm(analysis.observed_behavior)}\n"
            f"Expected: {sanitize_for_llm(analysis.expected_behavior)}\n"
            f"Exception: {sanitize_for_llm(analysis.assertion_or_exception or '')}\n"
            f"Console errors: {sanitize_for_llm(' | '.join(analysis.related_console_errors))}\n"
            f"Network errors: {sanitize_for_llm(' | '.join(analysis.related_network_errors))}\n"
            f"Test data: {sanitize_for_llm(str(test_data))}"
        )
        raw = llm_manager.generate_json(prompt, system, timeout=30.0)
        if isinstance(raw, dict):
            for key in ("observed_behavior", "probable_cause", "recommended_step"):
                if raw.get(key):
                    setattr(analysis, key, str(raw[key]))
