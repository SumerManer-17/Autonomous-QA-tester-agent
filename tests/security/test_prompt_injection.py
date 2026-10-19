"""Security tests: webpage content is data, not instructions (prompt injection)."""

from app.core.security import sanitize_for_llm


def test_script_tag_stripped_from_page_text():
    injected = "<img src=x onerror=alert(1)><script>fetch('http://evil')</script>Welcome!"
    cleaned = sanitize_for_llm(injected)
    assert "script" not in cleaned.lower()
    assert "onerror" not in cleaned.lower()
    assert "fetch" not in cleaned.lower()

def test_event_handlers_removed():
    cleaned = sanitize_for_llm('<div onclick="evil()">text</div>')
    assert "onclick" not in cleaned.lower()
