"""Playwright-based browser explorer.

Deterministic inspection of a target application: opens pages, collects
interactive elements with accessibility information, records console errors
and failed network requests, and takes screenshots. It never fills forms or
clicks buttons during exploration (navigation to discovered links only), so
the interface is inspected before any interaction.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import is_same_origin, sanitize_for_llm, validate_target_url
from app.schemas.exploration import DiscoveredPage, ExplorationResult
from app.schemas.test_case import TargetLocator

logger = get_logger(__name__)

INTERACTIVE_SELECTORS = {
    "link": "a[href]",
    "button": "button, [role='button']",
    "textbox": (
        "input[type='text'], input[type='email'], input[type='password'], "
        "input[type='search'], input[type='tel'], input[type='url'], "
        "input[type='number'], textarea"
    ),
    "select": "select",
    "checkbox": "input[type='checkbox']",
    "radio": "input[type='radio']",
    # data-testid elements (status messages, confirmation areas) are stable
    # assertion targets even when they have no ARIA role.
    "testid": "[data-testid]",
}

ROLE_MAP = {
    "link": "link",
    "button": "button",
    "textbox": "textbox",
    "select": "combobox",
    "checkbox": "checkbox",
    "radio": "radio",
    "testid": "generic",
}


def normalize_url_for_crawl(url: str) -> str:
    """Strip fragments and normalize scheme/host/path so duplicates collapse."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}{path}{'?' + parsed.query if parsed.query else ''}"


class BrowserExplorer:
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

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        browser_factory = getattr(self._playwright, self.browser_name, None)
        if browser_factory is None:
            raise ValueError(f"Unsupported browser: {self.browser_name}")
        self._browser = await browser_factory.launch(headless=self.headless)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def explore(
        self,
        target_url: str,
        max_pages: int | None = None,
        max_depth: int | None = None,
    ) -> ExplorationResult:
        """Explore the target origin and return discovered interface info.

        Validates the target URL for safety before launching the browser.
        """
        safe_url = normalize_url_for_crawl(validate_target_url(target_url))
        max_pages = max_pages or settings.MAX_CRAWL_PAGES
        max_depth = max_depth or settings.MAX_CRAWL_DEPTH

        os.makedirs(settings.SCREENSHOTS_DIR, exist_ok=True)

        async with self:
            context = await self._browser.new_context(
                ignore_https_errors=True,
            )
            page = await context.new_page()
            page.set_default_timeout(self.action_timeout_ms)

            console_errors: list[str] = []
            network_errors: list[str] = []

            page.on("console", lambda msg: self._on_console(msg, console_errors))
            page.on("pageerror", lambda err: console_errors.append(str(err)))
            page.on(
                "requestfailed",
                lambda req: network_errors.append(
                    f"{req.method} {req.url} -> "
                    f"{req.failure.get('errorText') if req.failure else 'failed'}"
                ),
            )

            visited: set[str] = set()
            pages: list[DiscoveredPage] = []
            screenshot_path = await self._screenshot(page, "exploration-initial.png")

            await self._crawl_page(
                context=context,
                page=page,
                url=safe_url,
                depth=0,
                max_pages=max_pages,
                max_depth=max_depth,
                visited=visited,
                pages=pages,
                console_errors=console_errors,
                network_errors=network_errors,
            )

            await context.close()

        return ExplorationResult(
            target_url=safe_url,
            pages=pages,
            console_errors=console_errors,
            network_errors=network_errors,
            screenshot_path=screenshot_path,
        )

    # ------------------------------------------------------------------ #
    # Crawling
    # ------------------------------------------------------------------ #
    async def _crawl_page(
        self,
        context,
        page,
        url: str,
        depth: int,
        max_pages: int,
        max_depth: int,
        visited: set[str],
        pages: list[DiscoveredPage],
        console_errors: list[str],
        network_errors: list[str],
    ) -> None:
        url = normalize_url_for_crawl(url)
        if url in visited or len(pages) >= max_pages:
            return
        visited.add(url)

        try:
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms
            )
            if response is not None and response.status >= 400:
                console_errors.append(f"HTTP {response.status} GET {url}")
        except PlaywrightTimeoutError as exc:
            logger.warning("Navigation timeout for %s: %s", url, exc)
            return
        except PlaywrightError as exc:
            logger.warning("Navigation failed for %s: %s", url, exc)
            return

        try:
            title = await page.title()
        except PlaywrightError:
            title = None

        screenshot_path = await self._screenshot(page, f"page-{len(pages)}.png")
        elements = await self._collect_elements(page)

        pages.append(
            DiscoveredPage(
                url=page.url,
                title=title,
                depth=depth,
                screenshot_path=screenshot_path,
                console_errors=list(console_errors),
                network_errors=list(network_errors),
                elements=elements,
            )
        )

        if depth >= max_depth or len(pages) >= max_pages:
            return

        links = await self._discover_links(page, page.url)
        # Also discover GET form actions (read-only searches) so search
        # results and similar pages are reachable without submitting state.
        try:
            form_count = await page.locator("form[action]").count()
        except PlaywrightError:
            form_count = 0
        for index in range(min(form_count, 20)):
            try:
                action = await page.locator("form[action]").nth(index).get_attribute("action")
                method = await page.locator("form[action]").nth(index).get_attribute("method")
            except PlaywrightError:
                continue
            if not action or (method or "get").lower() == "post":
                continue
            absolute = normalize_url_for_crawl(urljoin(page.url, action))
            if is_same_origin(absolute, page.url) and absolute not in links:
                links.append(absolute)
        for link_url in links:
            if len(pages) >= max_pages:
                break
            await self._crawl_page(
                context=context,
                page=page,
                url=link_url,
                depth=depth + 1,
                max_pages=max_pages,
                max_depth=max_depth,
                visited=visited,
                pages=pages,
                console_errors=console_errors,
                network_errors=network_errors,
            )

    # ------------------------------------------------------------------ #
    # Element collection
    # ------------------------------------------------------------------ #
    async def _collect_elements(self, page) -> list[TargetLocator]:
        elements: list[TargetLocator] = []
        for role_key, selector in INTERACTIVE_SELECTORS.items():
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except PlaywrightError:
                continue
            for index in range(min(count, 50)):
                handle = locator.nth(index)
                info = await self._describe_element(handle, role_key, index)
                if info is not None:
                    elements.append(info)
        return elements

    async def _describe_element(
        self, handle, role_key: str, index: int
    ) -> TargetLocator | None:
        # Elements are collected regardless of current visibility: assertion
        # targets (success messages, errors) are often hidden until an action
        # runs. Visibility is asserted at execution time instead.
        info = await handle.evaluate(
            """(element) => {
            const getAttr = (name) => {
              const value = element.getAttribute(name);
              return value === null ? undefined : value;
            };
            const accessibleName = element.getAttribute('aria-label');
            const labelledBy = element.getAttribute('aria-labelledby');
            let name = accessibleName;
            if (!name && labelledBy) {
              const labelled = document.getElementById(labelledBy);
              if (labelled) name = labelled.textContent.trim();
            }
            const formLabel = element.closest('label');
            const labelText = formLabel ? formLabel.textContent.trim() : undefined;
            return {
              tag: element.tagName.toLowerCase(),
              explicitRole: element.getAttribute('role') || undefined,
              name: name || undefined,
              placeholder: getAttr('placeholder'),
              testId: getAttr('data-testid'),
              value: getAttr('value'),
              text: (element.textContent || '').trim().slice(0, 80) || undefined,
              label: labelText || undefined,
              id: getAttr('id'),
              nameAttr: getAttr('name'),
              type: getAttr('type'),
              visible: element.offsetParent !== null || element.getClientRects().length > 0,
            };
          }"""
        )
        if not info:
            return None

        role = info.get("explicitRole") or ROLE_MAP.get(role_key, role_key)
        name = info.get("name") or info.get("label") or info.get("text")
        target = TargetLocator(
            role=role,
            name=sanitize_for_llm(name) if name else None,
            label=sanitize_for_llm(info.get("label")) if info.get("label") else None,
            placeholder=(
                sanitize_for_llm(info.get("placeholder"))
                if info.get("placeholder")
                else None
            ),
            test_id=info.get("testId"),
            text=sanitize_for_llm(info.get("text")) if info.get("text") else None,
        )
        if not target.has_any():
            return None
        return target

    # ------------------------------------------------------------------ #
    # Link discovery
    # ------------------------------------------------------------------ #
    async def _discover_links(self, page, current_url: str) -> list[str]:
        links: list[str] = []
        try:
            count = await page.locator("a[href]").count()
        except PlaywrightError:
            return links
        for index in range(min(count, 100)):
            try:
                href = await page.locator("a[href]").nth(index).get_attribute("href")
            except PlaywrightError:
                continue
            if not href:
                continue
            absolute = normalize_url_for_crawl(urljoin(current_url, href))
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if not is_same_origin(absolute, current_url):
                continue
            if absolute not in links:
                links.append(absolute)
        return links

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _screenshot(self, page, name: str) -> str | None:
        try:
            path = os.path.join(settings.SCREENSHOTS_DIR, name)
            await page.screenshot(path=path, full_page=True)
            logger.info("Screenshot saved: %s", path)
            return path
        except PlaywrightError as exc:
            logger.warning("Screenshot failed: %s", exc)
            return None

    def _on_console(self, msg, collector: list[str]) -> None:
        if msg.type in {"error", "warning"}:
            collector.append(f"[{msg.type}] {sanitize_for_llm(msg.text)}")


__all__ = ["BrowserExplorer", "ExplorationResult"]
