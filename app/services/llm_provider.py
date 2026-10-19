"""Optional LLM provider for test generation and failure summarization.

The agent must work without any LLM API key. When no provider is configured
or the provider fails, callers fall back to deterministic generation and
rule-based analysis. Webpage content is always sanitized before it reaches a
prompt; secrets are never forwarded.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings
from app.core.security import sanitize_for_llm

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    def is_available(self) -> bool:  # pragma: no cover - interface
        ...

    @abstractmethod
    def generate_json(self, prompt: str, system: str, timeout: float = 30.0):
        """Return parsed JSON from the LLM, or None on any failure."""
        ...


class _BaseHttpProvider(LLMProvider):
    def __init__(self, name: str, base_url: str, api_key: str, model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @abstractmethod
    def _request(self, prompt: str, system: str, timeout: float):
        ...

    def generate_json(self, prompt: str, system: str, timeout: float = 30.0):
        if not self.is_available():
            return None
        try:
            raw = self._request(prompt, system, timeout)
        except Exception as exc:  # network, timeout, auth, etc.
            logger.warning("LLM provider %s unavailable: %s", self.name, exc)
            return None
        return _extract_json(raw)


class OpenAICompatibleProvider(_BaseHttpProvider):
    def _request(self, prompt: str, system: str, timeout: float):
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]


class GroqProvider(_BaseHttpProvider):
    """Groq uses the OpenAI-compatible chat completions schema."""

    def _request(self, prompt: str, system: str, timeout: float):
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]


class OllamaProvider(_BaseHttpProvider):
    def _request(self, prompt: str, system: str, timeout: float):
        url = f"{self.base_url}/api/generate"
        body = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
            data = response.json()
        return data.get("response", "")


def _extract_json(text: str):
    """Best-effort extraction of a JSON object/array from LLM output.

    Never raises: returns None when no parseable JSON is present.
    """
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find the first balanced JSON object or array.
    start = text.find("{")
    start_array = text.find("[")
    if start == -1 and start_array == -1:
        return None
    if start_array != -1 and (start == -1 or start_array < start):
        start = start_array
        end = text.rfind("]")
    else:
        end = text.rfind("}")
    if end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


class LLMManager:
    def __init__(self):
        self.provider: LLMProvider | None = self._build_provider()

    def _build_provider(self) -> LLMProvider | None:
        mode = (settings.LLM_MODE or "disabled").strip().lower()
        if mode == "disabled" or mode == "none":
            return None
        api_key = settings.LLM_API_KEY
        base_url = settings.LLM_BASE_URL or ""
        model = settings.LLM_MODEL or ""

        if mode == "openai":
            if not base_url:
                base_url = "https://api.openai.com/v1"
            return OpenAICompatibleProvider("openai", base_url, api_key, model)
        if mode == "groq":
            if not base_url:
                base_url = "https://api.groq.com/openai/v1"
            return GroqProvider("groq", base_url, api_key, model)
        if mode == "ollama":
            if not base_url:
                base_url = "http://localhost:11434"
            return OllamaProvider("ollama", base_url, api_key, model)
        logger.warning("Unknown LLM mode %s; running without LLM", mode)
        return None

    def is_available(self) -> bool:
        return self.provider is not None and self.provider.is_available()

    def generate_json(self, prompt: str, system: str, timeout: float = 30.0):
        if not self.provider:
            return None
        # Sanitize anything that might contain captured page content.
        safe_prompt = sanitize_for_llm(prompt)
        safe_system = sanitize_for_llm(system)
        return self.provider.generate_json(safe_prompt, safe_system, timeout)


llm_manager = LLMManager()

__all__ = ["LLMProvider", "LLMManager", "llm_manager", "_extract_json"]
