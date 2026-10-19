"""Unit tests: the agent must work without any LLM API key."""

from app.services.llm_provider import LLMManager, _extract_json, llm_manager


class TestLLMUnavailable:
    def test_manager_not_available_without_key(self):
        # In the test environment QA_LLM_MODE=disabled.
        assert llm_manager.is_available() is False
        assert llm_manager.provider is None

    def test_generate_json_returns_none(self):
        assert llm_manager.generate_json("prompt", "system") is None


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_json_in_markdown_fence(self):
        text = "```json\n{\"title\": \"x\"}\n```"
        assert _extract_json(text) == {"title": "x"}

    def test_garbage_returns_none(self):
        assert _extract_json("no json here") is None
        assert _extract_json("") is None
        assert _extract_json("{broken") is None
