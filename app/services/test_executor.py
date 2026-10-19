"""Safe Playwright test executor.

Executes a limited, explicit action vocabulary against a real browser.
Only actions in ACTION_REGISTRY can run -- never arbitrary JavaScript, shell
commands, or LLM-generated code. Every action validates its arguments,
resolves its target deterministically, uses bounded timeouts, records its
result, and captures evidence on failure.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import is_same_origin, sanitize_for_llm, validate_target_url
from app.schemas.test_case import ActionType, Step
from app.schemas.test_result import (
    FailureCategory,
    StepResult,
    TestResult,
    TestStatus,
    new_result_id,
)

logger = get_logger(__name__)

MAX_LOCATOR_MATCHES = 1


class StepExecutionError(Exception):
    """A step failed with a known failure category."""

    def __init__(self, message: str, category: FailureCategory):
        super().__init__(message)
        self.category = category


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


class TestExecutor:
    def __init__(
        self,
        browser_name: str | None = None,
        headless: bool | None = None,
        action_timeout_ms: int | None = None,
        navigation_timeout_ms: int | None = None,
    ):
        self.browser_name = browser_name or settings.BROWSER
        self.headless = settings.HEADLESS if headless is None else headless
        self.action_timeout_ms = action_timeout_ms or settings.ACTION_TIMEOUT_MS
        self.navigation_timeout_ms = (
            navigation_timeout_ms or settings.NAVIGATION_TIMEOUT_MS
        )
        self._playwright = None
        self._browser = None
        self._started = False

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    async def start(self):
        if self._started:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        browser_factory = getattr(self._playwright, self.browser_name, None)
        if browser_factory is None:
            raise ValueError(f"Unsupported browser: {self.browser_name}")
        self._browser = await browser_factory.launch(headless=self.headless)
        self._started = True

    async def stop(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._started = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def execute_case(self, case, base_url: str, context) -> TestResult:
        """Execute one test case inside an existing browser context.

        A fresh context per test case keeps localStorage/cookie state isolated.
        """
        result = TestResult(
            id=new_result_id(),
            test_id=case.id,
            run_id=case.run_id,
            status=TestStatus.PASSED,
            started_at=_utcnow(),
        )
        page = await context.new_page()
        page.set_default_timeout(self.action_timeout_ms)

        console_errors: list[str] = []
        network_errors: list[str] = []
        logs: list[str] = []

        page.on("console", lambda msg: self._collect_console(msg, console_errors, logs))
        page.on("pageerror", lambda err: console_errors.append(f"JS error: {err}"))
        page.on(
            "requestfailed",
            lambda req: network_errors.append(
                f"{req.method} {req.url} -> "
                f"{req.failure.get('errorText') if req.failure else 'failed'}"
            ),
        )

        try:
            for index, step in enumerate(case.steps):
                if index >= settings.MAX_ACTIONS_PER_RUN:
                    raise StepExecutionError(
                        f"action budget exceeded ({settings.MAX_ACTIONS_PER_RUN})",
                        FailureCategory.TEST_SETUP_FAILURE,
                    )
                step_start = time.monotonic()
                try:
                    await self._dispatch(page, step, base_url, logs)
                    result.mark_step(
                        step_index=index,
                        action=step.action.value,
                        status=TestStatus.PASSED,
                        duration_ms=_elapsed_ms(step_start),
                        target=step.target.model_dump() if step.target else None,
                    )
                except StepExecutionError as exc:
                    screenshot = await self._screenshot(page, f"fail-{result.id}-{index}.png")
                    result.mark_step(
                        step_index=index,
                        action=step.action.value,
                        status=TestStatus.FAILED,
                        error=str(exc),
                        duration_ms=_elapsed_ms(step_start),
                        screenshot_path=screenshot,
                        target=step.target.model_dump() if step.target else None,
                    )
                    result.status = TestStatus.FAILED
                    result.error_message = str(exc)
                    result.failure_category = exc.category
                    result.screenshot_path = screenshot
                    logger.warning(
                        "Test %s failed at step %d (%s): %s",
                        case.id, index, step.action, exc,
                    )
                    break
                except Exception as exc:  # unexpected infrastructure error
                    category = FailureCategory.BROWSER_INFRASTRUCTURE_FAILURE
                    if isinstance(exc, PlaywrightTimeoutError):
                        category = FailureCategory.TIMEOUT
                    screenshot = await self._screenshot(page, f"fail-{result.id}-{index}.png")
                    result.mark_step(
                        step_index=index,
                        action=step.action.value,
                        status=TestStatus.FAILED,
                        error=sanitize_for_llm(str(exc)),
                        duration_ms=_elapsed_ms(step_start),
                        screenshot_path=screenshot,
                        target=step.target.model_dump() if step.target else None,
                    )
                    result.status = TestStatus.FAILED
                    result.error_message = sanitize_for_llm(str(exc))
                    result.failure_category = category
                    result.screenshot_path = screenshot
                    break

            result.finished_at = _utcnow()
            result.duration_ms = int(
                (result.finished_at - result.started_at).total_seconds() * 1000
            )
        finally:
            result.console_errors = console_errors
            result.network_errors = network_errors
            result.logs = logs
            try:
                await page.close()
            except PlaywrightError:
                pass

        return result

    async def execute_run(
        self,
        test_cases: list,
        base_url: str,
        max_seconds: int | None = None,
    ) -> list[TestResult]:
        """Execute all test cases, one isolated browser context per case.

        Stops early if the run budget is exceeded; remaining cases are
        returned as skipped.
        """
        await self.start()
        results: list[TestResult] = []
        deadline = None
        if max_seconds:
            deadline = time.monotonic() + max_seconds

        try:
            for case in test_cases:
                if deadline and time.monotonic() > deadline:
                    results.append(
                        TestResult(
                            id=new_result_id(),
                            test_id=case.id,
                            run_id=case.run_id,
                            status=TestStatus.SKIPPED,
                            error_message="run duration budget exceeded",
                            failure_category=FailureCategory.TIMEOUT,
                            started_at=_utcnow(),
                            finished_at=_utcnow(),
                        )
                    )
                    continue
                context = await self._browser.new_context(
                    ignore_https_errors=True,
                )
                try:
                    result = await self.execute_case(case, base_url, context)
                    results.append(result)
                finally:
                    await context.close()
        finally:
            await self.stop()
        return results

    # ------------------------------------------------------------------ #
    # Action dispatch
    # ------------------------------------------------------------------ #
    async def _dispatch(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        action = step.action
        handler = ACTION_REGISTRY.get(action.value)
        if handler is None:
            raise StepExecutionError(
                f"unsupported action {action.value}",
                FailureCategory.TEST_SETUP_FAILURE,
            )
        await handler(self, page, step, base_url, logs)

    async def _resolve(self, page, step: Step, require_single: bool = True, allow_empty: bool = False):
        """Resolve a step target to a Playwright Locator using stable strategies."""
        target = step.target
        if target is None:
            raise StepExecutionError(
                f"{step.action} requires a target element",
                FailureCategory.ELEMENT_NOT_FOUND,
            )
        locator, strategy = self._locator_strategy(page, target)
        try:
            count = await locator.count()
        except PlaywrightError as exc:
            raise StepExecutionError(
                f"unable to count matches for {target.describe()}: {exc}",
                FailureCategory.ELEMENT_NOT_FOUND,
            ) from exc
        if count == 0 and not allow_empty:
            raise StepExecutionError(
                f"element not found: {target.describe()}",
                FailureCategory.ELEMENT_NOT_FOUND,
            )
        # An explicit index makes the choice deterministic (e.g. first
        # "Select room" button). Otherwise a single match is required.
        if target.index is not None:
            if target.index < 0 or target.index >= count:
                raise StepExecutionError(
                    f"element index {target.index} out of range ({count} matches): {target.describe()}",
                    FailureCategory.ELEMENT_NOT_FOUND,
                )
            return locator.nth(target.index)
        if require_single and count > MAX_LOCATOR_MATCHES:
            if target.name is not None:
                exact = await self._exact_name_matches(locator, count, target.name)
                if len(exact) == 1:
                    return locator.nth(exact[0])
                if len(exact) > 1:
                    logger.warning(
                        "Still ambiguous after exact name match: %s", target.describe()
                    )
            raise StepExecutionError(
                f"ambiguous element ({count} matches): {target.describe()}",
                FailureCategory.ELEMENT_AMBIGUOUS,
            )
        return locator

    async def _exact_name_matches(self, locator, count: int, name: str) -> list[int]:
        """Return indexes whose accessible name equals the target name exactly.

        Playwright role/name matching can be substring-based, so multiple DOM
        elements can share a name prefix (e.g. "Password" vs "Confirm password").
        """
        wanted = name.strip().lower()
        matches: list[int] = []
        for i in range(count):
            handle = locator.nth(i)
            accessible = await handle.evaluate(
                """(el) => {
                const aria = el.getAttribute('aria-label');
                if (aria) return aria.trim();
                const labelled = el.getAttribute('aria-labelledby');
                if (labelled) {
                  const node = document.getElementById(labelled);
                  if (node) return node.textContent.trim();
                }
                const label = el.closest('label');
                if (label) return label.textContent.trim();
                return el.textContent.trim();
              }"""
            )
            if (accessible or "").strip().lower() == wanted:
                matches.append(i)
        return matches

    def _locator_strategy(self, page, target):
        # Order: most stable / explicit first.
        if target.test_id:
            escaped = target.test_id.replace('"', '\\"')
            return (
                page.locator(f'[data-testid="{escaped}"]'),
                f"data-testid={target.test_id}",
            )
        if target.role and target.name:
            return (
                page.get_by_role(target.role, name=target.name),
                f"role={target.role} name={target.name}",
            )
        if target.role:
            return (
                page.get_by_role(target.role),
                f"role={target.role}",
            )
        if target.label:
            return (
                page.get_by_label(target.label),
                f"label={target.label}",
            )
        if target.placeholder:
            return (
                page.get_by_placeholder(target.placeholder),
                f"placeholder={target.placeholder}",
            )
        if target.text:
            return (
                page.get_by_text(target.text),
                f"text={target.text}",
            )
        raise StepExecutionError(
            f"target has no usable locator strategy: {target.describe()}",
            FailureCategory.ELEMENT_NOT_FOUND,
        )

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    async def _action_navigate(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        url = step.value
        if not url:
            raise StepExecutionError("navigate requires a URL", FailureCategory.TEST_SETUP_FAILURE)
        # Resolve relative URLs against the base target origin.
        from urllib.parse import urljoin, urlparse

        absolute = urljoin(base_url, url) if not urlparse(url).scheme else url
        validate_target_url(absolute)  # re-validate every navigation target
        if not is_same_origin(absolute, base_url):
            raise StepExecutionError(
                f"navigation leaves authorized origin: {absolute}",
                FailureCategory.NAVIGATION_FAILURE,
            )
        try:
            response = await page.goto(
                absolute,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
            logs.append(f"navigate {absolute}")
            if response is not None and response.status >= 400:
                raise StepExecutionError(
                    f"application returned HTTP {response.status} for {absolute}",
                    FailureCategory.APPLICATION_HTTP_ERROR,
                )
        except PlaywrightTimeoutError as exc:
            raise StepExecutionError(
                f"navigation timed out: {absolute}",
                FailureCategory.NAVIGATION_FAILURE,
            ) from exc

    async def _action_click(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        await locator.click(timeout=self.action_timeout_ms)
        logs.append(f"click {step.target.describe() if step.target else ''}")

    async def _action_fill(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        if step.value is None:
            raise StepExecutionError("fill requires a value", FailureCategory.TEST_SETUP_FAILURE)
        await locator.fill(step.value, timeout=self.action_timeout_ms)
        logs.append(f"fill {step.target.describe() if step.target else ''}")

    async def _action_select_option(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        if step.value is None:
            raise StepExecutionError("select_option requires a value", FailureCategory.TEST_SETUP_FAILURE)
        await locator.select_option(step.value, timeout=self.action_timeout_ms)
        logs.append(f"select_option {step.target.describe() if step.target else ''}")

    async def _action_check(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        await locator.set_checked(True, timeout=self.action_timeout_ms)
        logs.append(f"check {step.target.describe() if step.target else ''}")

    async def _action_uncheck(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        await locator.set_checked(False, timeout=self.action_timeout_ms)
        logs.append(f"uncheck {step.target.describe() if step.target else ''}")

    async def _action_assert_visible(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        visible = await locator.is_visible()
        if not visible:
            raise StepExecutionError(
                f"element not visible: {step.target.describe() if step.target else ''}",
                FailureCategory.ASSERTION_FAILURE,
            )
        logs.append(f"assert_visible {step.target.describe() if step.target else ''}")

    async def _action_assert_text(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        if step.assertion_value is None:
            raise StepExecutionError("assert_text requires assertion_value", FailureCategory.TEST_SETUP_FAILURE)
        actual = (await locator.text_content() or "").strip()
        expected = step.assertion_value.strip()
        # Substring match: robust against dynamic surrounding text.
        if expected not in actual:
            raise StepExecutionError(
                f"text mismatch: expected {expected!r} in {actual!r}",
                FailureCategory.ASSERTION_FAILURE,
            )
        logs.append(f"assert_text {step.target.describe() if step.target else ''}")

    async def _action_assert_url(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        if step.value is None:
            raise StepExecutionError("assert_url requires a value", FailureCategory.TEST_SETUP_FAILURE)
        actual = page.url
        expected = step.value
        if expected.startswith("^") or expected.startswith("re:"):
            pattern = re.sub(r"^re:?", "", expected)
            if not re.search(pattern, actual):
                raise StepExecutionError(
                    f"url mismatch: expected pattern {pattern!r} in {actual!r}",
                    FailureCategory.ASSERTION_FAILURE,
                )
        elif actual.rstrip("/") != expected.rstrip("/") and expected not in actual:
            raise StepExecutionError(
                f"url mismatch: expected {expected!r}, actual {actual!r}",
                FailureCategory.ASSERTION_FAILURE,
            )
        logs.append(f"assert_url {expected}")

    async def _action_assert_enabled(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        if not await locator.is_enabled():
            raise StepExecutionError(
                f"element not enabled: {step.target.describe() if step.target else ''}",
                FailureCategory.ASSERTION_FAILURE,
            )
        logs.append(f"assert_enabled {step.target.describe() if step.target else ''}")

    async def _action_assert_disabled(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        if await locator.is_enabled():
            raise StepExecutionError(
                f"element not disabled: {step.target.describe() if step.target else ''}",
                FailureCategory.ASSERTION_FAILURE,
            )
        logs.append(f"assert_disabled {step.target.describe() if step.target else ''}")

    async def _action_assert_count(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step, require_single=False, allow_empty=True)
        if step.assertion_value is None:
            raise StepExecutionError("assert_count requires assertion_value", FailureCategory.TEST_SETUP_FAILURE)
        try:
            expected = int(step.assertion_value)
        except ValueError as exc:
            raise StepExecutionError(
                "assert_count assertion_value must be an integer",
                FailureCategory.TEST_SETUP_FAILURE,
            ) from exc
        actual = await locator.count()
        if actual != expected:
            raise StepExecutionError(
                f"count mismatch: expected {expected}, found {actual}",
                FailureCategory.ASSERTION_FAILURE,
            )
        logs.append(f"assert_count {expected}")

    async def _action_assert_attribute(self, page, step: Step, base_url: str, logs: list[str]) -> None:
        locator = await self._resolve(page, step)
        if not step.attribute:
            raise StepExecutionError("assert_attribute requires attribute", FailureCategory.TEST_SETUP_FAILURE)
        if step.assertion_value is None:
            raise StepExecutionError("assert_attribute requires assertion_value", FailureCategory.TEST_SETUP_FAILURE)
        actual = await locator.get_attribute(step.attribute)
        expected = step.assertion_value
        if actual is None or expected not in actual:
            raise StepExecutionError(
                f"attribute mismatch: {step.attribute}={actual!r}, expected containing {expected!r}",
                FailureCategory.ASSERTION_FAILURE,
            )
        logs.append(f"assert_attribute {step.attribute}={expected}")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _screenshot(self, page, name: str) -> str | None:
        try:
            os.makedirs(settings.SCREENSHOTS_DIR, exist_ok=True)
            path = os.path.join(settings.SCREENSHOTS_DIR, name)
            data = await page.screenshot(full_page=True)
            with open(path, "wb") as f:
                f.write(data)
            return path
        except PlaywrightError as exc:
            logger.warning("screenshot failed: %s", exc)
            return None

    def _collect_console(self, msg, collector: list[str], logs: list[str]) -> None:
        if msg.type in {"error", "warning"}:
            collector.append(f"[{msg.type}] {sanitize_for_llm(msg.text)}")
        logs.append(f"console[{msg.type}]: {sanitize_for_llm(msg.text)}")


# --------------------------------------------------------------------------- #
# Action registry: explicit, auditable list of supported actions.
# --------------------------------------------------------------------------- #
ACTION_REGISTRY: dict[str, Any] = {
    ActionType.NAVIGATE.value: TestExecutor._action_navigate,
    ActionType.CLICK.value: TestExecutor._action_click,
    ActionType.FILL.value: TestExecutor._action_fill,
    ActionType.SELECT_OPTION.value: TestExecutor._action_select_option,
    ActionType.CHECK.value: TestExecutor._action_check,
    ActionType.UNCHECK.value: TestExecutor._action_uncheck,
    ActionType.ASSERT_VISIBLE.value: TestExecutor._action_assert_visible,
    ActionType.ASSERT_TEXT.value: TestExecutor._action_assert_text,
    ActionType.ASSERT_URL.value: TestExecutor._action_assert_url,
    ActionType.ASSERT_ENABLED.value: TestExecutor._action_assert_enabled,
    ActionType.ASSERT_DISABLED.value: TestExecutor._action_assert_disabled,
    ActionType.ASSERT_COUNT.value: TestExecutor._action_assert_count,
    ActionType.ASSERT_ATTRIBUTE.value: TestExecutor._action_assert_attribute,
}

__all__ = ["TestExecutor", "ACTION_REGISTRY", "StepExecutionError"]
