"""Shared pytest configuration and fixtures for the Autonomous QA Testing Agent.

Tests run fully deterministically without any LLM API key. A temporary SQLite
database and artifact directory are used per session, and the local DemoShop
server (port 3000) is spawned as a subprocess for integration tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
DEMO_SERVER = ROOT / "demo-app" / "server.py"
DEMO_PORT = 3000
DEMO_URL = f"http://127.0.0.1:{DEMO_PORT}"


# Set environment variables at import time so app.core.config.Settings()
# (instantiated when app modules are first imported) picks up the test DB.
_TEST_TMP = tempfile.mkdtemp(prefix="qa-agent-test-")
os.environ.setdefault("QA_DATABASE_URL", str(Path(_TEST_TMP) / "qa_agent.db"))
os.environ.setdefault("QA_ARTIFACTS_DIR", str(Path(_TEST_TMP) / "artifacts"))
os.environ.setdefault("QA_SCREENSHOTS_DIR", str(Path(_TEST_TMP) / "artifacts" / "screenshots"))
os.environ.setdefault("QA_TRACES_DIR", str(Path(_TEST_TMP) / "artifacts" / "traces"))
os.environ.setdefault("QA_LOGS_DIR", str(Path(_TEST_TMP) / "artifacts" / "logs"))
os.environ.setdefault("QA_LLM_MODE", "disabled")
os.environ.setdefault("QA_DEMO_PORT", str(DEMO_PORT))
os.environ.setdefault("QA_MAX_RUN_SECONDS", "300")


def _wait_for(url: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:  # nosec - expected while waiting
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"Service {url} did not become ready: {last}")


@pytest.fixture(scope="session", autouse=True)
def test_environment():
    """Ensure the throwaway test DB is initialized before tests run."""
    from app.repositories.database import init_db

    init_db()
    yield _TEST_TMP


@pytest.fixture(scope="session")
def api_client(test_environment):
    """FastAPI test client (initializes the DB via lifespan)."""
    from app.main import app  # noqa: WPS433

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def demo_server(test_environment):
    """Spawn the DemoShop server on port 3000 with no defects enabled."""
    proc = subprocess.Popen(
        [sys.executable, str(DEMO_SERVER), str(DEMO_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(f"{DEMO_URL}/__demo/defects")
        # Ensure a clean slate: no injected defects.
        _demo_put_defects([])
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _demo_put_defects(defects: list[str]) -> None:
    body = json.dumps({"defects": defects}).encode("utf-8")
    req = urllib.request.Request(
        f"{DEMO_URL}/__demo/defects",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status != 200:
            raise RuntimeError(f"defect control returned {resp.status}")


@pytest.fixture
def no_defects(demo_server):
    _demo_put_defects([])


@pytest.fixture
def invalid_email_defect(demo_server):
    _demo_put_defects(["invalid_email_accepted"])


@pytest.fixture
def run_pipeline():
    from app.services.run_pipeline import RunPipeline  # noqa: WPS433

    return RunPipeline()
