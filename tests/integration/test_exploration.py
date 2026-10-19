"""Integration tests for Playwright browser exploration of the demo site."""

import pytest

from app.services.browser_explorer import BrowserExplorer


@pytest.mark.asyncio
async def test_explore_discovers_pages(demo_server):
    async with BrowserExplorer() as explorer:
        result = await explorer.explore("http://localhost:3000/", max_pages=8, max_depth=3)

    assert result.target_url == "http://localhost:3000/"
    urls = {page.url for page in result.pages}
    assert "http://localhost:3000/" in urls or "http://localhost:3000/index.html" in urls
    assert any("register.html" in u for u in urls), urls
    assert any("login.html" in u for u in urls), urls
    assert any("search.html" in u for u in urls), urls
    assert result.screenshot_path is not None


@pytest.mark.asyncio
async def test_explore_collects_interactive_elements(demo_server):
    async with BrowserExplorer() as explorer:
        result = await explorer.explore("http://localhost:3000/register.html", max_pages=1, max_depth=0)

    page = result.pages[0]
    roles = {el.role for el in page.elements}
    assert "textbox" in roles
    assert "button" in roles
    names = {el.name for el in page.elements if el.name}
    assert any("email" in (n or "").lower() for n in names), names
    # data-testid on status elements should be collected too
    test_ids = {el.test_id for el in page.elements if el.test_id}
    assert "reg-email-error" in test_ids or "register-error" in test_ids, test_ids


@pytest.mark.asyncio
async def test_explore_respects_page_limit(demo_server):
    async with BrowserExplorer() as explorer:
        result = await explorer.explore("http://localhost:3000/", max_pages=2, max_depth=3)

    assert len(result.pages) <= 2
