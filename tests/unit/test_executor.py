"""Unit tests for the test executor action registry and target resolution."""

import asyncio

import pytest
from playwright.async_api import async_playwright

from app.services.test_executor import ACTION_REGISTRY, StepExecutionError, TestExecutor
from app.schemas.test_case import ActionType, Step, TargetLocator
from app.schemas.test_result import FailureCategory


class TestActionRegistry:
    def test_all_actions_registered(self):
        expected = {
            ActionType.NAVIGATE.value,
            ActionType.CLICK.value,
            ActionType.FILL.value,
            ActionType.SELECT_OPTION.value,
            ActionType.CHECK.value,
            ActionType.UNCHECK.value,
            ActionType.ASSERT_VISIBLE.value,
            ActionType.ASSERT_TEXT.value,
            ActionType.ASSERT_URL.value,
            ActionType.ASSERT_ENABLED.value,
            ActionType.ASSERT_DISABLED.value,
            ActionType.ASSERT_COUNT.value,
            ActionType.ASSERT_ATTRIBUTE.value,
        }
        assert expected <= set(ACTION_REGISTRY.keys())
        # Every registered value maps to a callable.
        for name, handler in ACTION_REGISTRY.items():
            assert callable(handler), f"{name} is not callable"

    def test_no_arbitrary_code_actions(self):
        assert "execute_script" not in ACTION_REGISTRY
        assert "eval" not in ACTION_REGISTRY
        assert "shell" not in ACTION_REGISTRY


class TestStepExecutionError:
    def test_carries_category(self):
        exc = StepExecutionError("element missing", FailureCategory.ELEMENT_NOT_FOUND)
        assert exc.category == FailureCategory.ELEMENT_NOT_FOUND


@pytest.mark.asyncio
async def test_resolve_with_explicit_index():
    """An explicit index makes the choice deterministic among identical elements."""
    html = """
    <html><body>
      <button>Select room</button>
      <button>Select room</button>
      <button>Select room</button>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            executor = TestExecutor()
            base = page.get_by_role("button", name="Select room")
            assert await base.count() == 3
            locator = await executor._resolve(
                page,
                Step(action=ActionType.CLICK, target=TargetLocator(role="button", name="Select room", index=0)),
                require_single=True,
            )
            # Resolved locator is deterministic: exactly the first match.
            await locator.click()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_ambiguous_without_index_raises():
    html = "<html><body><button>Select room</button><button>Select room</button></body></html>"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            executor = TestExecutor()
            with pytest.raises(StepExecutionError) as exc:
                await executor._resolve(
                    page,
                    Step(action=ActionType.CLICK, target=TargetLocator(role="button", name="Select room")),
                    require_single=True,
                )
            assert exc.value.category == FailureCategory.ELEMENT_AMBIGUOUS
            assert "ambiguous" in str(exc.value).lower()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_not_found_raises():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content("<html><body></body></html>")
            executor = TestExecutor()
            with pytest.raises(StepExecutionError) as exc:
                await executor._resolve(
                    page,
                    Step(action=ActionType.CLICK, target=TargetLocator(role="button", name="Nope")),
                    require_single=True,
                )
            assert exc.value.category == FailureCategory.ELEMENT_NOT_FOUND
        finally:
            await browser.close()
