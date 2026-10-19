"""Test scenario generation.

Two modes:
* deterministic -- predefined templates keyed by goal keywords, resolved
  against elements discovered by the browser explorer.
* llm_assisted -- asks the configured LLM for additional cases grounded in
  the discovered UI, validated with Pydantic, with deterministic fallback.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.core.security import sanitize_for_llm
from app.schemas.exploration import ExplorationResult
from app.schemas.test_case import (
    ActionType,
    Step,
    TargetLocator,
    TestCase,
    TestPriority,
    TestRisk,
    new_test_id,
)

logger = get_logger(__name__)

# Synthetic test data only -- never real credentials or PII.
TEST_USER = {
    "name": "QA Tester",
    "email": "qa-tester@example.com",
    "password": "SecurePass123!",
    "invalid_email": "not-an-email",
}
DEMO_CREDENTIALS = {
    "email": "demo@example.com",
    "password": "Password123!",
    "wrong_password": "WrongPassword123!",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScenarioGenerator:
    def __init__(self, exploration: ExplorationResult, target_url: str):
        self.exploration = exploration
        self.target_url = target_url
        self.pages_by_path: dict[str, Any] = {}
        for page in exploration.pages:
            path = page.url.split("?")[0]
            self.pages_by_path.setdefault(path, page)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def generate(self, goal: str, llm_mode: str = "deterministic") -> list[TestCase]:
        """Generate test cases for the goal.

        LLM mode is attempted first when configured; any failure falls back
        to deterministic generation so the pipeline never stalls.
        """
        goal = (goal or "").strip()
        if llm_mode and llm_mode != "disabled":
            try:
                llm_cases = self._llm_generate(goal)
                if llm_cases:
                    logger.info(
                        "Generated %d LLM-assisted test cases", len(llm_cases)
                    )
                    return llm_cases
            except Exception as exc:  # pragma: no cover - LLM is external
                logger.warning("LLM generation failed: %s; using deterministic mode", exc)
        cases = self._deterministic(goal)
        logger.info("Generated %d deterministic test cases", len(cases))
        return cases

    # ------------------------------------------------------------------ #
    # Deterministic templates
    # ------------------------------------------------------------------ #
    def _deterministic(self, goal: str) -> list[TestCase]:
        lower = goal.lower()
        tests: list[TestCase] = []

        if any(k in lower for k in ("register", "registration", "sign up", "create account")):
            tests.extend(self._registration_tests())
        if any(k in lower for k in ("login", "log in", "sign in", "sign-in")):
            tests.extend(self._login_tests())
        if any(k in lower for k in ("search", "find hotel")):
            tests.extend(self._search_tests())
        if any(k in lower for k in ("room", "select a room")):
            tests.extend(self._room_selection_tests())
        if any(k in lower for k in ("book", "booking", "complete the booking")):
            tests.extend(self._booking_tests())
        if any(k in lower for k in ("validation", "invalid", "error", "reject")):
            tests.extend(self._validation_tests())

        if not tests:
            tests.append(self._generic_exploration_test(goal))

        # Run ID will be assigned by the caller/pipeline before persistence.
        for test in tests:
            if not test.run_id:
                test.run_id = "pending"
        return tests

    def _page_for(self, path_hint: str):
        for path, page in self.pages_by_path.items():
            if path_hint in path:
                return page
        return None

    def _resolve_target(
        self, role: str, name_candidates: list[str | None]
    ) -> TargetLocator | None:
        """Match a step target against discovered elements."""
        for page in self.exploration.pages:
            for el in page.elements:
                if el.role != role:
                    continue
                for cand in name_candidates:
                    if not cand:
                        continue
                    if el.name == cand or el.label == cand or el.placeholder == cand:
                        return el
        return None

    def _target_hint(self, role: str, name: str | None) -> TargetLocator:
        return TargetLocator(role=role, name=name)

    # ----- individual scenario families --------------------------------- #
    def _registration_tests(self) -> list[TestCase]:
        register_page = self._page_for("/register") or self._page_for("register")
        reg_url = register_page.url if register_page else self.target_url + "/register.html"
        email_target = self._resolve_target("textbox", ["Email", "Email address"])
        name_target = self._resolve_target("textbox", ["Full name", "Name"])
        pass_target = self._resolve_target("textbox", ["Password"])
        confirm_target = self._resolve_target("textbox", ["Confirm password"])
        submit_target = self._resolve_target("button", ["Create account"])

        steps_valid = [
            Step(action=ActionType.NAVIGATE, value=reg_url, description="Navigate to registration page"),
            Step(action=ActionType.FILL, target=name_target or self._target_hint("textbox", "Full name"), value=TEST_USER["name"], description="Enter full name"),
            Step(action=ActionType.FILL, target=email_target or self._target_hint("textbox", "Email"), value=TEST_USER["email"], description="Enter email"),
            Step(action=ActionType.FILL, target=pass_target or self._target_hint("textbox", "Password"), value=TEST_USER["password"], description="Enter password"),
            Step(action=ActionType.FILL, target=confirm_target or self._target_hint("textbox", "Confirm password"), value=TEST_USER["password"], description="Confirm password"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Create account"), description="Click Create account"),
            Step(action=ActionType.ASSERT_VISIBLE, target=TargetLocator(role="generic", test_id="register-success"), description="Assert registration success message is shown"),
        ]

        steps_invalid_email = [
            Step(action=ActionType.NAVIGATE, value=reg_url, description="Navigate to registration page"),
            Step(action=ActionType.FILL, target=name_target or self._target_hint("textbox", "Full name"), value=TEST_USER["name"], description="Enter full name"),
            Step(action=ActionType.FILL, target=email_target or self._target_hint("textbox", "Email"), value=TEST_USER["invalid_email"], description="Enter invalid email"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Create account"), description="Click Create account"),
            Step(action=ActionType.ASSERT_VISIBLE, target=TargetLocator(role="generic", test_id="reg-email-error"), description="Assert validation message for invalid email is shown"),
        ]

        return [
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Register with valid data",
                objective="A user can register with valid data and receive a success confirmation.",
                generation_mode="deterministic",
                preconditions=["Registration page is reachable"],
                steps=steps_valid,
                target_elements=[e for e in [email_target, name_target, pass_target, confirm_target, submit_target] if e],
                test_data=TEST_USER,
                expected_outcome="Registration succeeds and a success message or confirmation is displayed.",
                priority=TestPriority.CRITICAL,
                risk_level=TestRisk.HIGH,
                required_assertions=["success message visible after registration"],
                created_at=_utcnow(),
            ),
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Reject invalid registration email",
                objective="The registration form rejects an invalid email address with a validation message.",
                generation_mode="deterministic",
                preconditions=["Registration page is reachable"],
                steps=steps_invalid_email,
                target_elements=[e for e in [email_target, submit_target] if e],
                test_data={"email": TEST_USER["invalid_email"]},
                expected_outcome="Registration is rejected and an appropriate validation message is displayed.",
                priority=TestPriority.HIGH,
                risk_level=TestRisk.HIGH,
                required_assertions=["validation message visible for invalid email"],
                created_at=_utcnow(),
            ),
        ]

    def _login_tests(self) -> list[TestCase]:
        login_page = self._page_for("/login") or self._page_for("login")
        login_url = login_page.url if login_page else self.target_url + "/login.html"
        email_target = self._resolve_target("textbox", ["Email", "Email address"])
        pass_target = self._resolve_target("textbox", ["Password"])
        submit_target = self._resolve_target("button", ["Sign in"])

        steps_valid = [
            Step(action=ActionType.NAVIGATE, value=login_url, description="Navigate to login page"),
            Step(action=ActionType.FILL, target=email_target or self._target_hint("textbox", "Email"), value=DEMO_CREDENTIALS["email"], description="Enter registered email"),
            Step(action=ActionType.FILL, target=pass_target or self._target_hint("textbox", "Password"), value=DEMO_CREDENTIALS["password"], description="Enter password"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Sign in"), description="Click Sign in"),
            Step(action=ActionType.ASSERT_URL, value=self.target_url.rstrip("/") + "/search.html", description="Assert navigation to search page after login"),
        ]

        steps_invalid = [
            Step(action=ActionType.NAVIGATE, value=login_url, description="Navigate to login page"),
            Step(action=ActionType.FILL, target=email_target or self._target_hint("textbox", "Email"), value=DEMO_CREDENTIALS["email"], description="Enter registered email"),
            Step(action=ActionType.FILL, target=pass_target or self._target_hint("textbox", "Password"), value=DEMO_CREDENTIALS["wrong_password"], description="Enter wrong password"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Sign in"), description="Click Sign in"),
            Step(action=ActionType.ASSERT_VISIBLE, target=TargetLocator(role="generic", test_id="login-error"), description="Assert login error is shown"),
            Step(action=ActionType.ASSERT_TEXT, target=TargetLocator(role="generic", test_id="login-error"), assertion_value="Invalid email or password.", description="Assert incorrect credentials error message"),
        ]

        return [
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Login with valid credentials",
                objective="A registered user can sign in and reach the search page.",
                generation_mode="deterministic",
                preconditions=["Account exists", "Login page is reachable"],
                steps=steps_valid,
                target_elements=[e for e in [email_target, pass_target, submit_target] if e],
                test_data={"email": DEMO_CREDENTIALS["email"]},
                expected_outcome="Sign in succeeds and the user is navigated to the search page.",
                priority=TestPriority.CRITICAL,
                risk_level=TestRisk.HIGH,
                required_assertions=["URL is the search page after login"],
                created_at=_utcnow(),
            ),
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Login rejects invalid credentials",
                objective="Sign in with a wrong password shows an error message.",
                generation_mode="deterministic",
                preconditions=["Login page is reachable"],
                steps=steps_invalid,
                target_elements=[e for e in [email_target, pass_target, submit_target] if e],
                test_data={"email": DEMO_CREDENTIALS["email"], "password": DEMO_CREDENTIALS["wrong_password"]},
                expected_outcome="Sign in is rejected and 'Invalid email or password.' is displayed.",
                priority=TestPriority.HIGH,
                risk_level=TestRisk.MEDIUM,
                required_assertions=["error message visible after failed login"],
                created_at=_utcnow(),
            ),
        ]

    def _search_tests(self) -> list[TestCase]:
        search_page = self._page_for("/search") or self._page_for("search")
        search_url = search_page.url if search_page else self.target_url + "/search.html"
        dest_target = self._resolve_target("textbox", ["Destination", "City or hotel name"])
        submit_target = self._resolve_target("button", ["Search"])

        steps = [
            Step(action=ActionType.NAVIGATE, value=search_url, description="Navigate to search page"),
            Step(action=ActionType.FILL, target=dest_target or self._target_hint("textbox", "Destination"), value="Lakeview", description="Enter destination"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Search"), description="Click Search"),
            Step(action=ActionType.ASSERT_VISIBLE, target=TargetLocator(role="generic", test_id="results-list"), description="Assert search results are displayed"),
        ]

        filter_target = self._resolve_target("combobox", ["Price filter"])
        filter_steps = [
            Step(action=ActionType.NAVIGATE, value=search_url, description="Navigate to search page"),
            Step(action=ActionType.FILL, target=dest_target or self._target_hint("textbox", "Destination"), value="Lakeview", description="Enter destination"),
            Step(action=ActionType.SELECT_OPTION, target=filter_target or self._target_hint("combobox", "Price filter"), value="under100", description="Select under $100/night filter"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Search"), description="Click Search"),
            Step(action=ActionType.ASSERT_COUNT, target=TargetLocator(role="generic", test_id="hotel-card"), assertion_value="0", description="Assert no $120 hotel appears under the $100 filter"),
        ]

        return [
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Search for a hotel",
                objective="Searching with a destination returns matching hotel results.",
                generation_mode="deterministic",
                preconditions=["Search page is reachable"],
                steps=steps,
                target_elements=[e for e in [dest_target, submit_target] if e],
                test_data={"destination": "Lakeview"},
                expected_outcome="Search results page lists hotels matching the destination.",
                priority=TestPriority.HIGH,
                risk_level=TestRisk.MEDIUM,
                required_assertions=["at least one hotel result visible"],
                created_at=_utcnow(),
            ),
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Search respects price filter",
                objective="Results honor the selected price filter.",
                generation_mode="deterministic",
                preconditions=["Search page is reachable"],
                steps=filter_steps,
                target_elements=[e for e in [dest_target, filter_target, submit_target] if e],
                test_data={"destination": "Lakeview", "filter": "under100"},
                expected_outcome="No hotel priced at $120/night appears when the under $100 filter is selected.",
                priority=TestPriority.MEDIUM,
                risk_level=TestRisk.MEDIUM,
                required_assertions=["zero hotel cards match the filtered results"],
                created_at=_utcnow(),
            )
        ]

    def _room_selection_tests(self) -> list[TestCase]:
        search_page = self._page_for("/search") or self._page_for("search")
        search_url = search_page.url if search_page else self.target_url + "/search.html"
        dest_target = self._resolve_target("textbox", ["Destination", "City or hotel name"])
        submit_target = self._resolve_target("button", ["Search"])
        return [
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Select a room from search results",
                objective="A user can select a room on the search results page and reach the booking form.",
                generation_mode="deterministic",
                preconditions=["Search page is reachable"],
                steps=[
                    Step(action=ActionType.NAVIGATE, value=search_url, description="Navigate to search page"),
                    Step(action=ActionType.FILL, target=dest_target or self._target_hint("textbox", "Destination"), value="Lakeview", description="Enter destination"),
                    Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Search"), description="Click Search"),
                    Step(
                        action=ActionType.CLICK,
                        target=TargetLocator(role="link", name="Select room", index=0),
                        description="Click Select room for the first hotel",
                    ),
                    Step(
                        action=ActionType.ASSERT_VISIBLE,
                        target=self._resolve_target("textbox", ["Guest name"]) or self._target_hint("textbox", "Guest name"),
                        description="Assert booking form is displayed",
                    ),
                ],
                target_elements=[e for e in [dest_target, submit_target] if e],
                test_data={"destination": "Lakeview"},
                expected_outcome="Booking form loads with the selected hotel prefilled.",
                priority=TestPriority.MEDIUM,
                risk_level=TestRisk.MEDIUM,
                required_assertions=["booking form visible"],
                created_at=_utcnow(),
            )
        ]

    def _booking_tests(self) -> list[TestCase]:
        booking_page = self._page_for("/booking") or self._page_for("booking")
        if booking_page:
            booking_url = booking_page.url
            if "?" not in booking_url:
                booking_url += "?hotel=lakeview"
        else:
            booking_url = self.target_url + "/booking.html?hotel=lakeview"
        name_target = self._resolve_target("textbox", ["Guest name"])
        email_target = self._resolve_target("textbox", ["Email"])
        checkin_target = self._resolve_target("textbox", ["Check-in date"])
        checkout_target = self._resolve_target("textbox", ["Check-out date"])
        submit_target = self._resolve_target("button", ["Book now"])

        steps = [
            Step(action=ActionType.NAVIGATE, value=booking_url, description="Navigate to booking page"),
            Step(action=ActionType.FILL, target=name_target or self._target_hint("textbox", "Guest name"), value=TEST_USER["name"], description="Enter guest name"),
            Step(action=ActionType.FILL, target=email_target or self._target_hint("textbox", "Email"), value=TEST_USER["email"], description="Enter email"),
            Step(action=ActionType.FILL, target=checkin_target or self._target_hint("textbox", "Check-in date"), value="2026-11-01", description="Select check-in date"),
            Step(action=ActionType.FILL, target=checkout_target or self._target_hint("textbox", "Check-out date"), value="2026-11-03", description="Select check-out date"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Book now"), description="Click Book now"),
            Step(action=ActionType.ASSERT_URL, value=self.target_url.rstrip("/") + "/confirmation.html", description="Assert navigation to confirmation page"),
        ]

        return [
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Complete a hotel booking",
                objective="A user can complete the booking form and receive a booking confirmation.",
                generation_mode="deterministic",
                preconditions=["User is signed in", "Booking page is reachable"],
                steps=steps,
                target_elements=[e for e in [name_target, email_target, checkin_target, checkout_target, submit_target] if e],
                test_data={"check_in": "2026-11-01", "check_out": "2026-11-03"},
                expected_outcome="Booking is confirmed and a confirmation page with a reference is displayed.",
                priority=TestPriority.CRITICAL,
                risk_level=TestRisk.HIGH,
                required_assertions=["confirmation page visible after booking"],
                created_at=_utcnow(),
            )
        ]

    def _validation_tests(self) -> list[TestCase]:
        # Covered by register invalid email and login invalid credentials,
        # plus a booking date-range validation case.
        booking_page = self._page_for("/booking") or self._page_for("booking")
        if booking_page:
            booking_url = booking_page.url
            if "?" not in booking_url:
                booking_url += "?hotel=lakeview"
        else:
            booking_url = self.target_url + "/booking.html?hotel=lakeview"
        checkin_target = self._resolve_target("textbox", ["Check-in date"])
        checkout_target = self._resolve_target("textbox", ["Check-out date"])
        submit_target = self._resolve_target("button", ["Book now"])

        steps = [
            Step(action=ActionType.NAVIGATE, value=booking_url, description="Navigate to booking page"),
            Step(action=ActionType.FILL, target=checkin_target or self._target_hint("textbox", "Check-in date"), value="2026-11-05", description="Select check-in date"),
            Step(action=ActionType.FILL, target=checkout_target or self._target_hint("textbox", "Check-out date"), value="2026-11-01", description="Select check-out date before check-in"),
            Step(action=ActionType.CLICK, target=submit_target or self._target_hint("button", "Book now"), description="Click Book now"),
            Step(action=ActionType.ASSERT_VISIBLE, target=TargetLocator(role="generic", test_id="booking-error"), description="Assert date-range validation message is shown"),
            Step(action=ActionType.ASSERT_TEXT, target=TargetLocator(role="generic", test_id="booking-error"), assertion_value="Check-out date must be on or after the check-in date.", description="Assert date-range validation message text"),
        ]

        return [
            TestCase(
                id=new_test_id(),
                run_id="",
                title="Reject invalid booking date range",
                objective="Booking rejects a check-out date before the check-in date.",
                generation_mode="deterministic",
                preconditions=["Booking page is reachable"],
                steps=steps,
                target_elements=[e for e in [checkin_target, checkout_target, submit_target] if e],
                test_data={"check_in": "2026-11-05", "check_out": "2026-11-01"},
                expected_outcome="Invalid date range is rejected with a validation message.",
                priority=TestPriority.MEDIUM,
                risk_level=TestRisk.MEDIUM,
                required_assertions=["validation message visible for invalid date range"],
                created_at=_utcnow(),
            )
        ]

    def _generic_exploration_test(self, goal: str) -> TestCase:
        return TestCase(
            id=new_test_id(),
            run_id="",
            title="Explore application interface",
            objective=f"No matching workflow template for goal: {goal}. Verify the application loads and interactive elements are reachable.",
            generation_mode="deterministic",
            preconditions=["Target URL is reachable"],
            steps=[
                Step(action=ActionType.NAVIGATE, value=self.target_url, description="Navigate to target URL"),
                Step(action=ActionType.ASSERT_VISIBLE, target=self._target_hint("textbox", ""), description="Assert page contains interactive elements"),
            ],
            target_elements=[],
            test_data={},
            expected_outcome="Application home page loads successfully.",
            priority=TestPriority.LOW,
            risk_level=TestRisk.LOW,
            required_assertions=["home page loads"],
            created_at=_utcnow(),
        )

    # ------------------------------------------------------------------ #
    # LLM-assisted generation
    # ------------------------------------------------------------------ #
    def _llm_generate(self, goal: str) -> list[TestCase] | None:
        from app.services.llm_provider import llm_manager

        if not llm_manager.is_available():
            return None

        pages_summary = []
        for page in self.exploration.pages:
            pages_summary.append(
                f"- {page.url} (title: {page.title}): "
                + "; ".join(
                    f"{el.role} '{el.name or el.label or ''}'"
                    for el in page.elements[:12]
                )
            )
        pages_text = "\n".join(pages_summary) or "no pages discovered"

        system = (
            "You are a test automation architect. Generate test cases as a JSON array only. "
            "Each item must have: title, objective, preconditions (array), steps (array), "
            "expected_outcome, priority (low/medium/high/critical), risk_level (low/medium/high). "
            "Each step must have: action (one of: navigate, click, fill, select_option, check, "
            "uncheck, assert_visible, assert_text, assert_url, assert_enabled, assert_disabled, "
            "assert_count, assert_attribute), target {role, name, label, placeholder, test_id}, "
            "value, assertion_value, description. Use ONLY elements discovered in the UI below. "
            "Do not invent elements. Output valid JSON and nothing else."
        )
        prompt = (
            f"Goal: {sanitize_for_llm(goal)}\n"
            f"Target URL: {sanitize_for_llm(self.target_url)}\n"
            f"Discovered pages and elements:\n{pages_text}\n"
            "Generate 4-8 test cases covering the goal, including input validation and error handling where relevant."
        )

        raw = llm_manager.generate_json(prompt, system, timeout=45.0)
        if not isinstance(raw, list):
            return None

        cases: list[TestCase] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                steps = [
                    Step(
                        action=ActionType(s.get("action")),
                        target=TargetLocator(**s.get("target") or {}),
                        value=s.get("value"),
                        assertion_value=s.get("assertion_value"),
                        description=s.get("description", ""),
                    )
                    for s in item.get("steps", [])
                ]
            except Exception as exc:
                logger.warning("LLM test case skipped (invalid steps): %s", exc)
                continue
            try:
                case = TestCase(
                    id=new_test_id(),
                    run_id="",
                    title=str(item.get("title", "Untitled LLM test")),
                    objective=str(item.get("objective", "")),
                    generation_mode="llm_assisted",
                    preconditions=list(item.get("preconditions") or []),
                    steps=steps,
                    test_data=dict(item.get("test_data") or {}),
                    expected_outcome=str(item.get("expected_outcome", "")),
                    priority=item.get("priority", "medium"),
                    risk_level=item.get("risk_level", "low"),
                    required_assertions=list(item.get("required_assertions") or []),
                    created_at=_utcnow(),
                )
                cases.append(case)
            except Exception as exc:  # validation failure -> skip case
                logger.warning("LLM test case skipped (schema): %s", exc)
                continue
        return cases or None
