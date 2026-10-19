"""Application configuration.

Reads environment variables (from .env when present) with sensible defaults.
All settings are purposely simple: no heavy settings library, just
python-dotenv + os.environ, so the project stays dependency-light.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

# Load .env from the project root if it exists (never fails if missing).
load_dotenv()


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, str(default))
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _env_list(name: str, default=None) -> list[str]:
    if default is None:
        default = []
    raw = _env(name, ",".join(default))
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


class Settings:
    """Runtime configuration for the Autonomous QA Testing Agent."""

    # --- Application ---
    APP_NAME: str = "Autonomous QA Testing Agent"
    APP_VERSION: str = "0.1.0"
    HOST: str = _env("QA_HOST", "127.0.0.1")
    PORT: int = _env_int("QA_PORT", 8000)
    DEBUG: bool = _env_bool("QA_DEBUG", True)
    LOG_LEVEL: str = _env("QA_LOG_LEVEL", "INFO")
    SECRET_KEY: str = _env("QA_SECRET_KEY", "dev-secret-change-me-in-production")

    # --- Persistence ---
    DATABASE_URL: str = _env("QA_DATABASE_URL", "data/qa_agent.db")

    # --- Artifacts ---
    ARTIFACTS_DIR: str = _env("QA_ARTIFACTS_DIR", "artifacts")
    SCREENSHOTS_DIR: str = _env("QA_SCREENSHOTS_DIR", "artifacts/screenshots")
    TRACES_DIR: str = _env("QA_TRACES_DIR", "artifacts/traces")
    LOGS_DIR: str = _env("QA_LOGS_DIR", "artifacts/logs")

    # --- Exploration limits ---
    MAX_CRAWL_PAGES: int = _env_int("QA_MAX_CRAWL_PAGES", 10)
    MAX_CRAWL_DEPTH: int = _env_int("QA_MAX_CRAWL_DEPTH", 3)
    MAX_ACTIONS_PER_RUN: int = _env_int("QA_MAX_ACTIONS_PER_RUN", 60)
    MAX_RUN_SECONDS: int = _env_int("QA_MAX_RUN_SECONDS", 300)

    # --- Timeouts (milliseconds) ---
    ACTION_TIMEOUT_MS: int = _env_int("QA_ACTION_TIMEOUT_MS", 10000)
    NAVIGATION_TIMEOUT_MS: int = _env_int("QA_NAVIGATION_TIMEOUT_MS", 30000)

    # --- Browser ---
    BROWSER: str = _env("QA_BROWSER", "chromium")
    HEADLESS: bool = _env_bool("QA_HEADLESS", True)

    # --- LLM provider (optional) ---
    # Modes: disabled | openai | groq | ollama
    LLM_MODE: str = _env("QA_LLM_MODE", "disabled")
    LLM_API_KEY: str = _env("QA_LLM_API_KEY", "")
    LLM_BASE_URL: str = _env("QA_LLM_BASE_URL", "")
    LLM_MODEL: str = _env("QA_LLM_MODEL", "")

    # --- Security ---
    # Hosts the agent may test. Loopback addresses are always allowed.
    ALLOWED_HOSTS: list[str] = _env_list(
        "QA_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "::1"]
    )
    ALLOWED_SCHEMES: list[str] = ["http", "https"]

    # --- Demo application ---
    DEMO_PORT: int = _env_int("QA_DEMO_PORT", 3000)


settings = Settings()

__all__ = ["settings", "Settings"]
